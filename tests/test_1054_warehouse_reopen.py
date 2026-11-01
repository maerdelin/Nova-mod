"""NOVA 1054 Shared42 replay / partial-open resource ownership regressions.

Run the REAL 1054 warehouse allocator implementation in a tiny native host
harness. A 4MiB test pool keeps CI inexpensive; all allocation, refcount,
idle-cache, recycling, madvise, and failure branches are production code.
This is NOT proof that Run632 failed from malloc: 1053 did not log errno.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WarehouseReopen1054(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = (ROOT / "iso/nova_transport.c").read_text()
        cls.direct = (ROOT / "scripts/direct_transport_native_patch.py").read_text()
        cls.shared = (ROOT / "scripts/shared42_native_patch.py").read_text()
        cls.raw = (ROOT / "scripts/native_rebuffer_patch.py").read_text()

    def test_real_native_pool_caches_and_replays_without_reallocating(self):
        src = self.c
        structs = src[src.index("typedef struct nova_wh_page"):src.index("/* NOVA_1054_WAREHOUSE_REUSE_V1:")]
        block = src[src.index("static pthread_mutex_t g_warehouse_idle_lock"):src.index("static nova_shared_warehouse *nova_shared_warehouse_from_data")]
        self.assertIn("madvise", block)
        self.assertIn("NOVA_1054_OS_ALLOC_FORENSICS", block)
        self.assertIn("getrlimit(RLIMIT_AS", block)
        self.assertIn("/proc/self/maps", block)
        self.assertIn("g_warehouse_idle=NULL;", block)
        self.assertIn("if(__atomic_sub_fetch(&w->refs,1u,__ATOMIC_ACQ_REL)!=0u)return;", block)
        ctest = r"""
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <unistd.h>
#define NOVA_WH_PAGES 64
#define NOVA_WH_PAGE_BYTES (64u*1024u)
#define NOVA_WH_TOTAL_BYTES (4u*1024u*1024u)
#define NOVA_WH_FREE 0
#define NOVA_WH_RAW 2
#define LOGI(...) fprintf(stderr, __VA_ARGS__)
#define LOGE(...) fprintf(stderr, __VA_ARGS__)
""" + structs + r"""
static int malloc_calls=0,fail_malloc=0;
static void *test_malloc(size_t n){
    ++malloc_calls;
    if(fail_malloc){errno=ENOMEM;return NULL;}
    return malloc(n);
}
#define malloc test_malloc
""" + block + r"""
#undef malloc
int main(void){
    nova_shared_warehouse *w=nova_shared_warehouse_new();
    assert(w && malloc_calls==1 && w->free_count==NOVA_WH_PAGES);
    w->pages[3].state=NOVA_WH_RAW;
    w->free_count=1;
    w->data[8192]=0xa9;
    nova_shared_warehouse_unref(w);

    for(int i=0;i<80;++i){
        nova_shared_warehouse *next=nova_shared_warehouse_new();
        assert(next==w);
        assert(next->free_count==NOVA_WH_PAGES);
        assert(next->pages[3].state==NOVA_WH_FREE);
        assert(next->data[8192]==0); /* madvise drops idle media pages */
        next->data[8192]=0xa9;
        nova_shared_warehouse_unref(next);
    }
    assert(malloc_calls==1); /* no repeated contiguous 128MiB requests */

    nova_shared_warehouse *active=nova_shared_warehouse_new();
    nova_shared_warehouse *parallel=nova_shared_warehouse_new();
    assert(active && parallel && parallel!=active && malloc_calls==2);

    fail_malloc=1;
    assert(nova_shared_warehouse_new()==NULL);
    assert(malloc_calls==3);
    nova_shared_warehouse_unref(active); /* new idle cache */
    nova_shared_warehouse_unref(parallel); /* second allocation freed */
    nova_shared_warehouse *reused=nova_shared_warehouse_new();
    assert(reused==active && malloc_calls==3);
    /* Independent RAW reference must prevent reuse when transport closes. */
    __atomic_add_fetch(&reused->refs,1u,__ATOMIC_ACQ_REL);
    nova_shared_warehouse_unref(reused);
    assert(nova_shared_warehouse_new()==NULL);
    assert(malloc_calls==4);
    nova_shared_warehouse_unref(reused);
    assert(nova_shared_warehouse_new()==active);
    printf("NOVA_1054_NATIVE_REOPEN_PASS allocations=%d\n",malloc_calls);
    return 0;
}
"""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "pool.c").write_text(ctest)
            cp = subprocess.run(
                ["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                 "-pthread", str(root/"pool.c"), "-o", str(root/"pool")],
                text=True, capture_output=True)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            for i in range(3):
                run = subprocess.run([str(root/"pool")], text=True,
                                     capture_output=True, timeout=15)
                self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
                self.assertIn("NOVA_1054_NATIVE_REOPEN_PASS", run.stdout)

    def test_direct_source_partial_init_owns_and_releases_resources(self):
        src = self.direct
        initial = src.index("raw->transport_handle = dlopen")
        owns = src.index("raw->direct_transport = 1;", initial)
        symbols = src.index("raw->direct_read = ", initial)
        self.assertLess(initial, owns)
        self.assertLess(owns, symbols)
        self.assertIn('nova_direct_init_fail(raw,"transport_dlopen"', src)
        self.assertIn('nova_direct_init_fail(raw,"avio_buffer_alloc"', src)
        self.assertIn('nova_direct_init_fail(raw,"avio_context_alloc"', src)
        self.assertIn('if(raw->shared_base && raw->shared_release)', self.shared)
        self.assertIn('nova_direct_init_fail(raw,"shared128_acquire"', self.shared)
        self.assertIn('nova_direct_init_fail(raw,"shared_page_symbols"', self.shared)
        self.assertIn('nova_direct_init_fail(raw,"transport_symbols"', self.shared)
        self.assertIn('NOVA_1054_FF_INPUT_FAIL', self.raw)
        self.assertIn('NOVA_1054_RAW_INIT_FAIL', self.raw)

    def test_no_iso_or_media_policy_changes(self):
        self.assertIn("NOVA_1053_ISO_PUMP_GUARD_V1", self.c)
        self.assertIn("NOVA_SHARED42_MKV_PAGE_VIEW_V1", self.c)
        self.assertIn("NOVA_ISO_PARALLEL_V1", self.c)
        self.assertIn("NOVA_STARTUP_BUFFER_PREARM_V1", self.raw)
        self.assertIn("raw->capacity_bytes=86 * 1024 * 1024;", self.shared)
        self.assertIn("raw->page_queued >= 1376", self.shared)


if __name__ == "__main__":
    unittest.main()
