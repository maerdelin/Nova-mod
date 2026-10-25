"""Host-executable weak-network retry and byte-accurate resume tests.

Extract the PRODUCTION helpers to prove reconnects do not discard already
received bytes or re-read from offset zero, without emulating the full APK.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "iso/nova_transport.c").read_text()


class NativeWeakNetworkTests(unittest.TestCase):
    def test_retry_helpers_with_transient_open_seek_and_partial_read_errors(self):
        start = SOURCE.index("static int nova_weak_terminal_error")
        stop = SOURCE.index("/* ISO_META_CACHE_BEGIN", start)
        helpers = SOURCE[start:stop]
        prefix = r'''
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#define AVERROR(x) (-(x))
#define AVERROR_EOF (-7001)
#define AVERROR_EXIT (-7002)
#define AVERROR_HTTP_BAD_REQUEST (-7400)
#define AVERROR_HTTP_UNAUTHORIZED (-7401)
#define AVERROR_HTTP_FORBIDDEN (-7403)
#define AVERROR_HTTP_NOT_FOUND (-7404)
#define AVIO_FLAG_READ 1
#define NOVA_WEAK_RETRY_MAX_DELAY_MS 3000
#define LOGI(...) do {} while (0)
#define LOGE(...) do {} while (0)
typedef struct avio { int64_t pos; int error; int eof_reached; } AVIOContext;
typedef struct dict { int unused; } AVDictionary;
typedef struct avio_interrupt {
    int (*callback)(void *);
    void *opaque;
} AVIOInterruptCB;
#define NOVA_MODE_FILE 0
typedef struct nova_session {
    volatile int stopping;
    int mode;
    AVIOContext *upstream;
    char *upstream_url;
    char *upstream_headers;
    int64_t upstream_size;
    int64_t upstream_pos;
    int64_t file_cursor;
    int requires_origin_refresh;
    int file_http_mode;
    void *file_stream;
} nova_session;
static int open_count, fail_open_once, fail_open_404;
static int seek_count, fail_seek_once, fail_seek_einval_once, fail_seek_einval_always;
static int read_count, read_mode;
static int transport_interrupt(void *opaque) {
    return ((nova_session *)opaque)->stopping;
}
static int av_dict_set(AVDictionary **d, const char *k, const char *v, int flags) {
    (void)d; (void)k; (void)v; (void)flags; return 0;
}
static void av_dict_free(AVDictionary **d) { (void)d; }
static int avio_open2(AVIOContext **io, const char *url, int flags,
                      const AVIOInterruptCB *cb, AVDictionary **d) {
    (void)url; (void)flags; (void)cb; (void)d;
    open_count++;
    if (fail_open_404) return AVERROR_HTTP_NOT_FOUND;
    if (fail_open_once) { fail_open_once = 0; return -EIO; }
    *io = calloc(1, sizeof(**io)); assert(*io); return 0;
}
static void avio_closep(AVIOContext **io) { free(*io); *io = NULL; }
static int64_t avio_size(AVIOContext *io) { (void)io; return 1024 * 1024; }
static int64_t avio_seek(AVIOContext *io, int64_t p, int whence) {
    assert(whence == SEEK_SET);
    seek_count++;
    if (fail_seek_once) { fail_seek_once = 0; return -EIO; }
    if (fail_seek_einval_once || fail_seek_einval_always) {
        fail_seek_einval_once = 0;
        io->error = -EINVAL;
        io->eof_reached = 1;
        return -EINVAL;
    }
    if (p < 0 || p >= 1024 * 1024) return -EINVAL;
    io->pos = p; return p;
}
static int avio_read(AVIOContext *io, uint8_t *dst, int bytes) {
    read_count++;
    if (io->error) return io->error;
    if (io->eof_reached) return AVERROR_EOF;
    if (read_mode == 2) {
        read_mode = 0; io->error = -EIO; io->eof_reached = 1;
        return -EIO;
    }
    int got = bytes;
    if (got > 4096) got = 4096;
    if (read_mode == 1) { if (got > 1000) got = 1000; read_mode = 2; }
    if (io->pos + got > 1024 * 1024)
        got = 1024 * 1024 - (int)io->pos;
    for (int j = 0; j < got; j++)
        dst[j] = (uint8_t)((io->pos + j) % 251);
    io->pos += got;
    return got;
}
static void nova_file_java_close_active(nova_session *s){ s->file_stream=NULL; }
static int java_single_get_opens;
static int nova_file_java_open_at(nova_session *s,int64_t at){
    java_single_get_opens++;
    s->file_stream=(void *)1;
    s->upstream_pos=at;
    return 0;
}
static int nova_file_java_read(nova_session *s,uint8_t *dst,int n){
    int got=n>4096?4096:n;
    for(int j=0;j<got;j++)dst[j]=(uint8_t)((s->file_cursor+j)%251);
    return got;
}
static int fresh_origin_opens;
static int nova_file_open_fresh_at(nova_session *s,int64_t at){
    ++fresh_origin_opens;
    avio_closep(&s->upstream);
    s->upstream=calloc(1,sizeof(*s->upstream));
    assert(s->upstream);
    s->upstream->pos=at;
    s->upstream_pos=at;
    return 0;
}
static void expect_data(const uint8_t *data, int64_t offset, int n) {
    for (int i = 0; i < n; i++)
        assert(data[i] == (uint8_t)((offset + i) % 251));
}
'''
        suffix = r'''
int main(void) {
    nova_session s = {.upstream_url = "http://example.test/stream",
                      .upstream_headers = "", .upstream_pos = -1};
    uint8_t buf[8192];
    fail_open_once = 1;
    assert(nova_upstream_open_until_ready(&s) == 0);
    assert(open_count == 2 && s.upstream_pos == 0);
    assert(nova_upstream_read_exact_retry(&s, buf, 400000, 8192) == 8192);
    expect_data(buf, 400000, 8192);

    /* Two split reads with an error in between must resume at exact
     * absolute offset (400000+1000), never at the next 4MiB page. */
    read_mode = 1;
    assert(nova_upstream_read_exact_retry(&s, buf, 500000, 8192) == 8192);
    expect_data(buf, 500000, 8192);
    assert(open_count >= 3);

    /* File playback read retries must not lose the old offset when the
     * AVIOContext is dropped and upstream_pos temporarily becomes -1. */
    assert(nova_upstream_seek_retry(&s, 650000) == 0);
    s.file_cursor = 650000;
    read_mode = 2;
    int previous_opens = open_count;
    assert(nova_upstream_read_some_retry(&s, buf, 4096) == 4096);
    expect_data(buf, 650000, 4096);
    assert(open_count == previous_opens + 1 &&
           s.upstream_pos == 654096 && s.file_cursor == 654096);

    /* Exact failure from logs: valid in-range EINVAL, stale AVIO EOF. */
    previous_opens = open_count;
    fail_seek_einval_once = 1;
    assert(nova_file_seek_retry(&s, 720000) == 0);
    assert(open_count > previous_opens && s.upstream_pos == 720000);
    s.file_cursor = 720000;
    assert(nova_upstream_read_some_retry(&s, buf, 4096) == 4096);
    expect_data(buf, 720000, 4096);
    assert(s.file_cursor == 724096);

    /* Even a persistent invalid-range response must be bounded and must
     * never corrupt the previous committed position or block exit. */
    int64_t committed = s.file_cursor;
    fail_seek_einval_always = 1;
    assert(nova_file_seek_retry(&s, 730000) == AVERROR(EAGAIN));
    assert(s.file_cursor == committed);
    fail_seek_einval_always = 0;
    assert(nova_file_seek_retry(&s, 730000) == 0);
    s.file_cursor = 730000;

    /* A stale signed redirect must NEVER be reused for a new FILE range:
     * it refreshes the canonical logical resource and opens at the
     * requested offset BEFORE any attempt on the old URL. */
    s.requires_origin_refresh=1;
    previous_opens=fresh_origin_opens;
    assert(nova_file_seek_retry(&s, 780000)==0);
    assert(fresh_origin_opens==previous_opens+1);
    assert(s.upstream_pos==780000);
    s.file_cursor=780000;
    assert(nova_upstream_read_some_retry(&s,buf,4096)==4096);
    expect_data(buf,780000,4096);
    assert(fresh_origin_opens==previous_opens+1);
    s.requires_origin_refresh=0;

    /* New production path, not a failed-GET retry: ONE live data stream
     * is opened at an exact arbitrary offset, then reused for reads.
     * A large discontinuous second seek initiates a single new stream. */
    s.file_http_mode=1;
    int oldjava=java_single_get_opens;
    assert(nova_file_seek_retry(&s,800000)==0);
    assert(java_single_get_opens==oldjava+1);
    s.file_cursor=800000;
    assert(nova_upstream_read_some_retry(&s,buf,4096)==4096);
    expect_data(buf,800000,4096);
    assert(java_single_get_opens==oldjava+1);
    assert(nova_file_seek_retry(&s,800000)==0);
    assert(java_single_get_opens==oldjava+2);
    s.file_http_mode=0;
    s.file_stream=NULL;

    fail_seek_once = 1;
    assert(nova_upstream_seek_retry(&s, 700000) == 0);
    assert(s.upstream_pos == 700000);

    /* Do not spin forever on terminal invalid credentials / missing path. */
    nova_upstream_drop(&s);
    fail_open_404 = 1;
    assert(nova_upstream_seek_retry(&s, 100) == -1);
    fail_open_404 = 0;
    assert(s.upstream == NULL);

    s.stopping = 1;
    assert(nova_upstream_read_some_retry(&s, buf, 4096) == AVERROR_EXIT);
    puts("native weak retry: connection, seek, partial data, file resume, cancellation PASS");
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "weak_retry.c"
            exe = Path(td) / "weak_retry"
            src.write_text(prefix + helpers + suffix)
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", str(src), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True, timeout=15)


if __name__ == "__main__":
    unittest.main()
