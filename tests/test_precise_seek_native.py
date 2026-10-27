"""Execute the patched precision/preview/clock C, including long GOPs."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


def function(src,name):
    m=re.search(r"(?m)^(?:static )?(?:int|unsigned|void) "+name+r"\([^;]*?\)\n\{",src)
    if not m:raise AssertionError("missing function "+name)
    return src[m.start():src.index("\n}",m.end())+2]


COMMON=r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <assert.h>
typedef long long INT64;
#define serprintf(...) fprintf(stderr,__VA_ARGS__)
#define DBG if(0)
#define THREAD_IDLE 1
#define THREAD_RUNNING 2
static double speed=1.0;
#define RST_TO_TS_DELTA(x,t) ((t)((x)/speed))
#define TS_TO_RST_TIME(x,t) ((t)((x)*speed))
typedef struct {int valid,msPerFrame;} VIDEO;
typedef struct {int async;const char *name;void *seek;} DEC;
typedef struct {int index,time,epoch,blit_time,locked;} VIDEO_FRAME;
typedef struct SINK {int (*get)(struct SINK *,VIDEO_FRAME **);void *put_time;} SINK;
typedef struct {int count;} QUEUE;
typedef struct {
 struct {char url[256];} src;
 VIDEO *video; DEC *video_dec;
 int no_duration,seek_use_target_sync,seek_epoch;
 int nova_precise_state,nova_precise_epoch,nova_precise_target_ts;
 int nova_precise_target_rst,nova_precise_presented_ts;
 unsigned nova_precise_due_ms;
 int seek_preview_superseded,seek_preview_refining;
 int64_t seek_preview_refine_deadline_ms;
 int open,engine_thread_started,engine_tstate,seek_force_video_drop;
 int play_n_video_frames,play_n_video_one,play_n_video_time,play_n_old_time;
 int video_error,error,video_time,audio_time,duration,aborted;
 SINK *video_sink;
 int video_sink_count,vtime_post_sink,video_drop,nova_diag_drop_sink;
 QUEUE decode_q,locked_q;
} STREAM;
static uint64_t clock_ms=10000;
static int ticks,deliver_tick,cancel_tick,abort_tick;
static STREAM *current;
static int64_t atime64(void){return (int64_t)clock_ms;}
static int fake_clock_gettime(int id,struct timespec *t){
 t->tv_sec=clock_ms/1000;t->tv_nsec=(clock_ms%1000)*1000000;return 0;
}
#define clock_gettime fake_clock_gettime
static int stream_abort(STREAM *s){return s->aborted;}
static void stream_yield(void);
static char *ms_to_hms_string(int t,char *b,int n){b[0]=0;return b;}
static int thread_state_set(int *s,int v){int old=*s;*s=v;return old;}
static void _stream_resync(STREAM *s){}
static int _stream_wait_for_idle(STREAM *s,int timeout){return 0;}
'''


class PreciseNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=os.environ.get("NOVA_PATCHED_AVOS_ROOT")
        if not root:raise unittest.SkipTest("requires fully patched native source")
        cls.source=(Path(root)/"Source/stream_video.c").read_text()
        a=cls.source.index("static int nova_precise_scope(")
        b=cls.source.index("static void _video_init(",a)
        cls.helpers=cls.source[a:b]

    def run_c(self,body,preview=False,queue=False):
        yield_code=r'''
static void stream_yield(void){
 ++ticks;clock_ms+=2;
 if(current && cancel_tick && ticks>=cancel_tick)current->seek_preview_superseded=1;
 if(current && abort_tick && ticks>=abort_tick)current->aborted=1;
 if(current && deliver_tick && ticks==deliver_tick){
  int pts=current->nova_precise_target_ts+2;
  if(nova_precise_seek_admit(current,pts,current->seek_epoch)){
   nova_precise_seek_submitted(current,pts,current->seek_epoch,(INT64)(clock_ms+50)*1000000);
   current->play_n_video_frames=0;current->play_n_video_one=0;
  }
 }
}
'''
        c=COMMON+self.helpers+yield_code
        if preview:c+=function(self.source,"_stream_play_n_frames")
        if queue:
            c+=r'''
#define DBGQ if(0)
static int frames_dropped;
static VIDEO_FRAME returned;
static int get_count;
static int sink_get(SINK *s,VIDEO_FRAME **f){if(get_count++)return -1;*f=&returned;return 0;}
static int nova_sfdec2_claim_no_output_return(STREAM *s,VIDEO_FRAME *f){return f->index==7;}
static void frame_q_put(QUEUE *q,VIDEO_FRAME *f){q->count++;}
static int frame_q_count(QUEUE *q){return q->count;}
static VIDEO_FRAME *frame_q_get_unlocked(QUEUE *q){return NULL;}
'''
            # The production declaration has external linkage.
            c=c.replace('static int nova_sfdec2_claim_no_output_return(',
                        'int nova_sfdec2_claim_no_output_return(')
            c+=function(self.source,"_queue_sink_frames")
        c+="\nint main(void){\n"+r'''
 VIDEO video={1,40};DEC dec={1,"sfdec2",(void*)1};
 STREAM s={.src={"novatransport://7/stream?nova_direct=1"},.video=&video,.video_dec=&dec,
           .seek_epoch=3,.open=1,.engine_thread_started=1,.engine_tstate=THREAD_IDLE};
 current=&s;
'''+body+"\nreturn 0;}\n"
        with tempfile.TemporaryDirectory(prefix="nova-precise-") as t:
            p=Path(t)/"test.c";exe=Path(t)/"test";p.write_text(c)
            result=subprocess.run(["cc","-std=c11","-D_POSIX_C_SOURCE=200809L","-Wall","-Werror",
                "-Wno-unused-function","-Wno-unused-variable",str(p),"-o",str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0,run.stderr)

    def test_frame_floor_due_time_and_backwards_generation(self):
        self.run_c(r'''
 assert(nova_precise_scope(&s,2725880));
 nova_precise_begin(&s,2725880,2725880);
 assert(nova_precise_ui_time(&s,2720242)==2725880);
 assert(!nova_precise_seek_admit(&s,2720242,3));
 nova_precise_seek_submitted(&s,2720242,3,(INT64)clock_ms*1000000);
 assert(s.nova_precise_state==1); /* indexed keyframe is not completion */
 nova_precise_seek_submitted(&s,2725882,2,(INT64)clock_ms*1000000);
 assert(s.nova_precise_state==1); /* stale previous epoch */
 nova_precise_seek_submitted(&s,2725882,3,(INT64)(clock_ms+100)*1000000);
 assert(s.nova_precise_state==2);
 assert(nova_precise_wait(&s,clock_ms+500));
 assert(clock_ms>=10100 && s.nova_precise_state==3);
 assert(nova_precise_ui_time(&s,2720242)==2725880);
 assert(nova_precise_ui_time(&s,2726000)==2726000);
 s.seek_epoch=4;nova_precise_begin(&s,476080,476080);
 assert(nova_precise_ui_time(&s,470642)==476080); /* intentional backwards seek */
 nova_precise_seek_submitted(&s,2725882,3,(INT64)clock_ms*1000000);
 assert(s.nova_precise_state==1);
 nova_precise_seek_submitted(&s,476082,4,(INT64)clock_ms*1000000);
 assert(nova_precise_wait(&s,clock_ms+500));
 ''')

    def test_long_gop_preview_does_not_accept_one_second_partial(self):
        self.run_c(r'''
 nova_precise_begin(&s,476080,476080);
 s.seek_preview_refining=1;s.seek_force_video_drop=1;s.play_n_video_one=1;
 deliver_tick=2200; /* target arrives after 4.4s, beyond old preview deadline */
 assert(_stream_play_n_frames(&s,10,476080,0));
 assert(clock_ms>=14400 && s.play_n_video_time==476080);
 assert(nova_precise_wait(&s,clock_ms+1000));
 assert(s.nova_precise_state==3 && s.nova_precise_presented_ts==476082);
 ''',preview=True)

    def test_latest_request_cancels_and_never_completes_old_target(self):
        self.run_c(r'''
 nova_precise_begin(&s,476080,476080);
 s.seek_preview_refining=1;s.seek_force_video_drop=1;
 deliver_tick=4000;cancel_tick=30;
 assert(!_stream_play_n_frames(&s,10,476080,0));
 assert(clock_ms<10100 && !nova_precise_wait(&s,clock_ms+30000));
 assert(s.nova_precise_state==4);
 nova_precise_seek_submitted(&s,476082,3,(INT64)clock_ms*1000000);
 assert(s.nova_precise_state==4);
 ''',preview=True)

    def test_stop_and_timeout_are_not_successful_seek(self):
        self.run_c(r'''
 nova_precise_begin(&s,476080,476080);abort_tick=20;
 assert(!nova_precise_wait(&s,clock_ms+30000));assert(s.nova_precise_state==4);
 s.aborted=0;abort_tick=0;nova_precise_begin(&s,476080,476080);
 assert(!nova_precise_wait(&s,clock_ms+50));assert(s.nova_precise_state==5);
 nova_precise_begin(&s,476080,476080);
 nova_precise_seek_submitted(&s,476082,3,(INT64)clock_ms*1000000);
 s.video_error=1;
 assert(!nova_precise_wait(&s,clock_ms+50));assert(s.nova_precise_state==7);
 ''')

    def test_timestamp_gap_and_speed_domain(self):
        self.run_c(r'''
 nova_precise_begin(&s,476080,476080);
 assert(!nova_precise_seek_admit(&s,476400,3));assert(s.nova_precise_state==6);
 speed=2.0;nova_precise_begin(&s,476080,238040);
 assert(!nova_precise_seek_admit(&s,238039,3));
 assert(nova_precise_seek_admit(&s,238041,3));
 assert(nova_precise_ui_time(&s,470642)==476080);
 ''')

    def test_scope_zero_iso_local_and_special_sync_are_preserved(self):
        self.run_c(r'''
 assert(!nova_precise_scope(&s,0));
 strcpy(s.src.url,"novatransport://7/main.m2ts");assert(!nova_precise_scope(&s,5000));
 strcpy(s.src.url,"/sdcard/test.mkv");assert(!nova_precise_scope(&s,5000));
 strcpy(s.src.url,"novatransport://7/stream");s.no_duration=1;assert(!nova_precise_scope(&s,5000));
 s.no_duration=0;s.seek_use_target_sync=1;assert(!nova_precise_scope(&s,5000));
 s.seek_use_target_sync=0;dec.async=0;assert(!nova_precise_scope(&s,5000));
 ''')

    def test_monotonic_clock_wrap(self):
        self.run_c(r'''
 clock_ms=0xfffffff0ULL;nova_precise_begin(&s,5000,5000);
 nova_precise_seek_submitted(&s,5002,3,(INT64)(clock_ms+100)*1000000);
 assert(nova_precise_wait(&s,(int64_t)clock_ms+500));
 assert(clock_ms>=0x100000000ULL && s.nova_precise_state==3);
 ''')

    def test_empty_wrapper_return_does_not_rewind_presentation_clock(self):
        self.run_c(r'''
 SINK sink={sink_get};s.video_sink=&sink;s.vtime_post_sink=1;
 s.video_time=476080;s.video_sink_count=1;
 returned=(VIDEO_FRAME){.index=7,.time=470642,.epoch=3,.blit_time=-1};
 get_count=0;_queue_sink_frames(&s);
 assert(s.video_time==476080 && s.video_sink_count==1 && s.decode_q.count==1);
 returned=(VIDEO_FRAME){.index=2,.time=476120,.epoch=3,.blit_time=1};
 get_count=0;_queue_sink_frames(&s);
 assert(s.video_time==476120 && s.video_sink_count==0 && s.decode_q.count==2);
 ''',queue=True)


if __name__=="__main__":unittest.main()
