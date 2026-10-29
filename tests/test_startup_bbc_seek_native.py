"""Execute the actual patched AVOS C functions with controlled clocks/I/O.

CI supplies the pinned, fully patched native tree. No copied implementation
of the skip condition or RAW deadline logic is tested here.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


def function(source, name):
    match = re.search(r"(?m)^(?:static )?(?:int|int64_t|void) " + name + r"\([^;]*?\)\n\{", source)
    if not match:
        raise AssertionError("missing native function " + name)
    return source[match.start():source.index("\n}", match.end()) + 2]


COMMON = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>
#define serprintf(...) fprintf(stderr, __VA_ARGS__)
#define AVOS_ERR_OK 0
#define STREAM_SEEK_FORWARD 0
#define STREAM_SEEK_BACKWARD 1
#define STREAM_SEEK_RELAXED 2
#define ETYPE_MPEG_TS 3
#define STREAM_POS_MAX 1000
#define AVERROR(x) (-(x))
#define AVERROR_EOF (-10000)
#define AVERROR_EXIT (-10001)
#define AVSEEK_SIZE 0x10000
#define AVSEEK_FORCE 0x20000
typedef struct {
    struct { char url[256]; } src;
    int seek_epoch, video_time, audio_time, no_duration, etype, current;
    int raw_prefetch_eof;
} STREAM;
'''


class NativeSeekCorrectness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get("NOVA_PATCHED_AVOS_ROOT")
        if not root:
            raise unittest.SkipTest("run after native patches with NOVA_PATCHED_AVOS_ROOT")
        cls.root = Path(root)
        cls.parser = (cls.root / "Source/stream_parser_ffmpeg.c").read_text()
        cls.video = (cls.root / "Source/avos_mp_video.c").read_text()
        if not shutil.which("cc"):
            raise AssertionError("C compiler is required for native seek acceptance")

    def execute(self, code):
        with tempfile.TemporaryDirectory(prefix="nova-seek-native-") as tmp:
            source = Path(tmp) / "test.c"
            binary = Path(tmp) / "test"
            source.write_text(COMMON + code)
            compiled = subprocess.run(["cc", "-std=c11", "-D_POSIX_C_SOURCE=200809L",
                                       "-Wall", "-Werror", "-Wno-unused-function",
                                       "-pthread", str(source), "-o", str(binary)],
                                      capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(ran.returncode, 0, ran.stderr)

    def test_queued_zero_decides_on_native_worker_state(self):
        code = r'''
typedef struct {} avos_mp_t;
typedef struct { STREAM *s; } avos_mp_video_t;
static int calls;
static int is_stream_seekable(avos_mp_t *mp, avos_mp_video_t *v) { return 1; }
static int stream_get_current_pos(STREAM *s, int *total) { return s->current; }
static int stream_seek_pos(STREAM *s, int pos, int dir, int flags) { ++calls; return 0; }
'''
        code += function(self.video, "avos_mp_video_seek")
        code += r'''
static void check(STREAM s, int request, int expect) {
    avos_mp_t mp; avos_mp_video_t v={&s}; calls=0;
    assert(avos_mp_video_seek(&mp,&v,request)==0); assert(calls==expect);
}
int main(void) {
    STREAM s={.src={"novatransport://9/stream?nova_direct=1"},
              .seek_epoch=1,.video_time=0,.audio_time=-1,.current=0};
    check(s,0,0); /* Java saw -1; worker now owns prepared frame zero. */
    check(s,5000,1); /* saved nonzero resume and user seeks */
    s.current=-1; check(s,0,1); /* first real seek still required */
    s.current=0; s.seek_epoch=0; check(s,0,1);
    s.seek_epoch=1; s.audio_time=0; check(s,0,1); /* established playback */
    s.audio_time=-1; s.video_time=50; check(s,0,1);
    s.video_time=0; s.no_duration=1; check(s,0,1);
    s.no_duration=0; strcpy(s.src.url,"novatransport://9/main.m2ts"); check(s,0,1);
    strcpy(s.src.url,"/sdcard/local.mkv"); check(s,0,1);
    strcpy(s.src.url,"novatransport://9/stream-other"); check(s,0,1);
    return 0;
}
'''
        self.execute(code)

    def test_slow_range_does_not_exhaust_new_packet_scan(self):
        code = r'''
typedef struct {} AVIOContext;
typedef struct {
    STREAM *s; AVIOContext *source;
    pthread_mutex_t mutex,source_mutex;
    pthread_cond_t can_read,can_write;
    int64_t source_size,consumer_pos,read_off,write_off,used_bytes;
    int64_t mkv_seek_started_us,mkv_seek_deadline_us;
    uint64_t mkv_seek_bytes;
    unsigned generation;
    int mkv_single_get,mkv_seek_active,mkv_seek_failed,eof,error;
    /* The extracted production reset now also drains shared RAW pages. */
    void *shared_base;
    int shared_pages;
    int page_queue[2048],page_head,page_tail,page_queued,page_head_consumed;
    void (*page_release)(void *,int);
} NOVA_RAW_PREFETCH;
static int64_t now_us, delay_us, seek_result;
static int64_t av_gettime_relative(void) { return now_us; }
static int64_t avio_seek(AVIOContext *s,int64_t pos,int whence) {
    now_us+=delay_us; return seek_result<0 ? seek_result : pos;
}
'''
        for name in ["nova_raw_reset_locked", "nova_mkv_seek_guard_failed", "nova_raw_seek"]:
            code += function(self.parser, name) + "\n"
        code += r'''
int main(void) {
    STREAM stream={0}; NOVA_RAW_PREFETCH raw={0};
    raw.s=&stream; raw.source_size=3000000000LL;
    pthread_mutex_init(&raw.mutex,0); pthread_mutex_init(&raw.source_mutex,0);
    pthread_cond_init(&raw.can_read,0); pthread_cond_init(&raw.can_write,0);
    raw.mkv_single_get=raw.mkv_seek_active=1;
    raw.mkv_seek_started_us=now_us=1000;
    raw.mkv_seek_deadline_us=now_us+45000000;
    raw.mkv_seek_bytes=4096; raw.used_bytes=12000;
    delay_us=13000000; /* field log: slow indexed Range above 12 seconds */
    assert(nova_raw_seek(&raw,999999,SEEK_SET)==999999);
    assert(!nova_mkv_seek_guard_failed(&raw));
    assert(raw.consumer_pos==999999 && raw.used_bytes==0 && raw.generation==1);
    assert(raw.mkv_seek_bytes==4096); /* aggregate scan limit not reset */
    assert(raw.mkv_seek_deadline_us==45001000); /* absolute bound not extended */
    now_us+=12000001; assert(nova_mkv_seek_guard_failed(&raw));
    raw.mkv_seek_started_us=now_us;
    raw.mkv_seek_failed=1;
    assert(nova_raw_seek(&raw,1111111,SEEK_SET)==1111111);
    assert(nova_mkv_seek_guard_failed(&raw)); /* success cannot erase prior failure */
    raw.mkv_seek_failed=0; raw.mkv_seek_started_us=now_us;
    raw.mkv_seek_bytes=67108865; assert(nova_mkv_seek_guard_failed(&raw));
    raw.mkv_seek_bytes=0; now_us=raw.mkv_seek_deadline_us;
    raw.mkv_seek_started_us=now_us; assert(nova_mkv_seek_guard_failed(&raw));
    raw.mkv_seek_active=0; assert(!nova_mkv_seek_guard_failed(&raw));
    raw.mkv_seek_active=1; raw.mkv_single_get=0;
    assert(!nova_mkv_seek_guard_failed(&raw)); /* ISO/MP4 do not enter MKV guard */
    raw.mkv_single_get=1; raw.mkv_seek_failed=0; seek_result=-5;
    unsigned generation=raw.generation; int64_t position=raw.consumer_pos;
    assert(nova_raw_seek(&raw,2222222,SEEK_SET)==-5);
    assert(raw.generation==generation && raw.consumer_pos==position);
    assert(raw.mkv_seek_failed==1);
    return 0;
}
'''
        self.execute(code)


if __name__ == "__main__":
    unittest.main()
