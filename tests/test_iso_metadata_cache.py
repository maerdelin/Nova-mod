"""Run588 ISO scan-only 4-MiB x 8 LRU cache regression tests.

Simulate disjoint UDF block reads against fake random-access upstream bytes.
This does NOT touch or emulate the RAW128 pre-demux movie data pipeline.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "iso" / "nova_transport.c").read_text()
BEGIN = "static void nova_iso_meta_release(nova_session *s)"
END = "/* ISO_META_CACHE_END */"

class IsoScanOnlyCacheTests(unittest.TestCase):
    def test_proven_run506_cache_shape_and_lifetime(self):
        self.assertIn("#define NOVA_ISO_META_PAGE_BYTES (4 * 1024 * 1024)", SOURCE)
        self.assertIn("#define NOVA_ISO_META_PAGE_COUNT 8", SOURCE)
        self.assertIn("if (s->iso_meta_active && s->upstream_size > 0)", SOURCE)
        self.assertIn("if (blocks > 0)", SOURCE)
        self.assertIn('LOGI("ISO_META_CACHE: fallback_direct=1', SOURCE)
        self.assertIn('retain_pages=1 weak_page_bytes=%d', SOURCE)
        self.assertIn('#define NOVA_ISO_WEAK_PAGE_BYTES (256 * 1024)', SOURCE)
        self.assertIn('int offset = (int)(pos - entry->start);', SOURCE)
        self.assertIn('nova_upstream_read_exact_retry(s, (uint8_t *)buf, target, bytes)', SOURCE)
        self.assertIn('phase=metadata_only', SOURCE)
        self.assertIn("nova_iso_meta_release(s);", SOURCE)
        # Keep old native HTTP bridge deleted and disk playback RAW untouched.
        self.assertNotIn("connect_loopback(", SOURCE)
        self.assertNotIn("CACHE_MODE playback", SOURCE)

    def test_cache_hit_and_lru_with_mock_upstream(self):
        a = SOURCE.index(BEGIN)
        b = SOURCE.index(END, a)
        snippet = SOURCE[a:b]
        prefix = r'''
#include <assert.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define LOGI(...) fprintf(stderr, __VA_ARGS__)
#define UDF_BLOCK 2048
#define NOVA_ISO_META_PAGE_BYTES (4 * 1024 * 1024)
#define NOVA_ISO_META_PAGE_COUNT 8
#define NOVA_ISO_WEAK_PAGE_BYTES (256 * 1024)

typedef struct mock_io {
    int64_t pos;
    int64_t size;
    int seeks;
    int reads;
    int fail_reads;
} mock_io;

typedef struct nova_iso_meta_page {
    int64_t start;
    int length;
    uint64_t touched;
    uint8_t *data;
} nova_iso_meta_page;

typedef struct nova_session {
    int iso_meta_active;
    int iso_meta_degraded;
    int64_t upstream_size;
    int64_t upstream_pos;
    mock_io *upstream;
    nova_iso_meta_page iso_meta_pages[NOVA_ISO_META_PAGE_COUNT];
    uint64_t iso_meta_tick, iso_meta_reads, iso_meta_hits;
    uint64_t iso_meta_misses, iso_meta_fetched;
    int iso_meta_window_bytes;
    int64_t iso_meta_last_miss_end;
    int iso_meta_peak_window;
} nova_session;

static int64_t avio_seek(mock_io *io, int64_t offset, int whence) {
    assert(whence == SEEK_SET);
    assert(offset >= 0 && offset <= io->size);
    io->pos = offset;
    ++io->seeks;
    return io->pos;
}
static int read_exact(mock_io *io, uint8_t *dst, int bytes) {
    if (io->fail_reads > 0) {
        --io->fail_reads;
        return -1;
    }
    assert(io->pos + bytes <= io->size);
    for (int i = 0; i < bytes; i++)
        dst[i] = (uint8_t)((io->pos + i) % 251);
    io->pos += bytes;
    ++io->reads;
    return bytes;
}
'''
        suffix = r'''
int main(void) {
    mock_io io = {.pos=0, .size=(int64_t)48 * 1024 * 1024};
    nova_session s = {.iso_meta_active=1, .upstream_size=io.size, .iso_meta_window_bytes=256*1024, .iso_meta_last_miss_end=-1,
                      .upstream_pos=0, .upstream=&io};
    uint8_t buf[4096];
    int64_t page = NOVA_ISO_META_PAGE_BYTES;
    assert(nova_iso_meta_read(&s,buf,4096,2048)==1);
    assert(io.seeks==1 && io.reads==1);
    assert(buf[0]==(uint8_t)(4096 % 251));
    assert(nova_iso_meta_read(&s,buf,8192,2048)==1);
    assert(io.seeks==1 && s.iso_meta_hits==1);
    assert(nova_iso_meta_read(&s,buf,9*page+4096,2048)==1);
    assert(io.seeks==2);
    /* One failed prefetch must not discard previous fully fetched pages.
     * The first 256KiB page must remain readable after a failed prefetch. */
    io.fail_reads = 1;
    assert(nova_iso_meta_read(&s,buf,10*page+4096,2048)==-1);
    assert(s.iso_meta_degraded == 1);
    int cached_reads = io.reads;
    assert(nova_iso_meta_read(&s,buf,40000,2048)==1);
    assert(io.reads == cached_reads);
    assert(buf[0]==(uint8_t)(40000 % 251));
    assert(nova_iso_meta_read(&s,buf,10*page+4096,2048)==1);
    assert(io.reads == cached_reads+1);
    assert(buf[0]==(uint8_t)((10*page+4096) % 251));
    /* Exercise two adjacent pages in one UDF block fetch. */
    assert(nova_iso_meta_read(&s,buf,page-2048,4096)==2);
    assert(io.seeks>=3);
    /* Touch first page so LRU evicts the oldest other page. */
    assert(nova_iso_meta_read(&s,buf,4096,2048)==1);
    int old_seeks=io.seeks;
    for (int i=2; i<10; ++i) {
        assert(nova_iso_meta_read(&s,buf,i*page+4096,2048)==1);
    }
    assert(io.seeks >= old_seeks+7);
    assert(s.iso_meta_misses==(uint64_t)io.reads);
    /* Fill all eight slots, then deliberately fail the next miss. The
     * selected LRU slot must retain its old bytes and index on failure. */
    mock_io io2 = {.pos=0, .size=(int64_t)48 * 1024 * 1024};
    nova_session e = {.iso_meta_active=1, .upstream_size=io2.size, .iso_meta_window_bytes=256*1024, .iso_meta_last_miss_end=-1,
                      .upstream_pos=0, .upstream=&io2};
    for (int i=0; i<8; i++)
        assert(nova_iso_meta_read(&e,buf,i*page+2048,2048)==1);
    assert(io2.reads==8 && e.iso_meta_misses==8);
    io2.fail_reads = 1;
    assert(nova_iso_meta_read(&e,buf,10*page+2048,2048)==-1);
    assert(e.iso_meta_degraded==1);
    int keeps = io2.reads;
    assert(nova_iso_meta_read(&e,buf,2048,2048)==1);
    assert(io2.reads==keeps);
    assert(buf[0]==(uint8_t)(2048%251));
    nova_iso_meta_release(&e);
    nova_iso_meta_release(&s);
    assert(!s.iso_meta_active);
    for(int i=0;i<NOVA_ISO_META_PAGE_COUNT;++i)
        assert(s.iso_meta_pages[i].data==NULL);
    assert(nova_iso_meta_read(&s,buf,4096,2048)==-1);
    puts("ISO metadata cache 4MiB x8: hit/miss/LRU/boundary/release PASS");
}
'''
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "cache_test.c"
            binary = Path(td) / "cache_test"
            source.write_text(prefix + snippet + suffix)
            subprocess.run(
                ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                 str(source), "-o", str(binary)],
                check=True)
            subprocess.run([str(binary)], check=True, timeout=20)

if __name__=="__main__":
    unittest.main()
