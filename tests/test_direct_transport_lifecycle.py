"""Exercise production close functions on host and scope final-APK evidence."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from smoke_direct_webdav import back_close_complete, reopened_frame


class DirectLifecycleTests(unittest.TestCase):
    def test_old_player_release_cannot_close_global_transport(self):
        from direct_transport_apply import verify_release_ownership
        original = ".method public release()V\n    .locals 0\n    return-void\n.end method\n"
        self.assertEqual(verify_release_ownership(original), original)
        unsafe = original.replace("    return-void", "    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->close()V\n    return-void")
        with self.assertRaisesRegex(RuntimeError, "must not close global"):
            verify_release_ownership(unsafe)

    def test_close_evidence_is_ordered_scoped_and_generation_specific(self):
        abort = 'NovaTransport: ABORT generation=7 reason=close\n'
        close = 'NovaTransport: CLOSE generation=7 complete=1\n'
        self.assertTrue(back_close_complete('MARK\n' + abort + close, 'MARK', 7))
        for text in (abort + close + 'MARK', 'MARK\n' + abort,
                     'MARK\n' + close + abort, 'MARK\n' + abort + close.replace('=7', '=8')):
            self.assertFalse(back_close_complete(text, 'MARK', 7))
        self.assertFalse(back_close_complete('MARK\n' + abort + close, 'MARK', 70))

    def test_reopen_requires_new_generation_and_new_frame(self):
        frame = 'NOVA_DIRECT_SOURCE_OPEN:\nNOVA_RAW128_OPEN: phase=pre_probe\nfirst_frame_sink'
        opened = 'OPEN_READY mode=file generation=8\n'
        self.assertTrue(reopened_frame('MARK\n' + opened + frame, 'MARK', 7))
        for text in (opened + frame + 'MARK', 'MARK\n' + opened,
                     'MARK\n' + opened.replace('=8', '=7') + frame):
            self.assertFalse(reopened_frame(text, 'MARK', 7))

    def test_native_close_drains_calls_and_preserves_new_generation(self):
        source = (ROOT / 'iso/nova_transport.c').read_text()
        # Extract only the lifecycle functions. Shared-page transport ABI
        # exports are tested separately and require the real page allocator.
        start = source.index('static nova_session *session_acquire')
        exposed = source.index('/* Raw prefetcher', start)
        cleanup = source.index('static void session_free', exposed)
        finish = source.index('static nova_session *session_create', cleanup)
        acquire_free = source[start:exposed] + source[cleanup:finish]
        close = source[source.index('static void transport_close'):source.index('JNIEXPORT void JNICALL', source.index('static void transport_close'))]
        release = source[source.index('static void nova_iso_meta_release'):source.index('static int nova_iso_meta_read')]
        harness = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define NOVA_ISO_META_PAGE_COUNT 8
typedef struct nova_iso_meta_page {
    int64_t start;
    int length;
    uint64_t touched;
    uint8_t *data;
} nova_iso_meta_page;
typedef struct nova_session {
    uint64_t generation;
    volatile int stopping;
    int active_calls;
    pthread_cond_t idle;
    pthread_mutex_t io_lock;
    void *bd, *upstream;
    int iso_meta_active;
    char *upstream_url;
    char *upstream_headers;
    void *warehouse;
    uint8_t *iso_startup_replay;
    nova_iso_meta_page iso_meta_pages[NOVA_ISO_META_PAGE_COUNT];
} nova_session;
static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static nova_session *g_session;
static nova_session *g_opening_session;
static pthread_mutex_t evidence_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t evidence_ready = PTHREAD_COND_INITIALIZER;
static int aborted, closed, freed;
static void log_event(const char *format, ...) {
    pthread_mutex_lock(&evidence_lock);
    if (!strncmp(format, "ABORT", 5)) aborted++;
    if (!strncmp(format, "CLOSE", 5)) { assert(freed > closed); closed++; }
    pthread_cond_broadcast(&evidence_ready);
    pthread_mutex_unlock(&evidence_lock);
}
#define LOGI(...) log_event(__VA_ARGS__)
static void bd_close(void *p) { (void)p; }
static void nova_file_release_java(nova_session *s) { (void)s; }
static void nova_multi_destroy(nova_session *s) { (void)s; }
/* The host lifecycle harness does not exercise page allocation; it
 * verifies that the session relinquishes its one warehouse reference. */
static void nova_shared_warehouse_unref(void *w) { (void)w; }
static void avio_closep(void **p) {
    *p = NULL;
    pthread_mutex_lock(&evidence_lock);
    freed++;
    pthread_mutex_unlock(&evidence_lock);
}
'''
        harness += release + acquire_free + close + r'''
static nova_session *make_session(uint64_t generation) {
    nova_session *s = calloc(1, sizeof(*s));
    s->generation = generation;
    s->upstream = (void *)1;
    s->iso_meta_active = 1;
    s->iso_meta_pages[0].data = malloc(32);
    assert(s->iso_meta_pages[0].data);
    s->iso_startup_replay = malloc(128);
    assert(s->iso_startup_replay);
    pthread_mutex_init(&s->io_lock, NULL);
    pthread_cond_init(&s->idle, NULL);
    return s;
}
static void *closer(void *unused) { (void)unused; transport_close(0, 0); return NULL; }
int main(void) {
    g_session = make_session(7);
    transport_close(6, 1);
    assert(g_session && !g_session->stopping && !aborted && !closed);
    nova_session *inflight = session_acquire(7);
    assert(inflight);
    pthread_t thread;
    pthread_create(&thread, NULL, closer, NULL);
    pthread_mutex_lock(&evidence_lock);
    while (!aborted) pthread_cond_wait(&evidence_ready, &evidence_lock);
    assert(!closed && !freed);
    pthread_mutex_unlock(&evidence_lock);
    assert(!session_acquire(7));
    session_release(inflight);
    pthread_join(thread, NULL);
    assert(aborted == 1 && closed == 1 && freed == 1);
    transport_close(0, 0);
    assert(closed == 1);
    /* Pending opens must see cancellation before they can publish. */
    nova_session *opening = make_session(99);
    g_opening_session = opening;
    transport_close(0, 0);
    assert(opening->stopping && g_opening_session == opening);
    session_free(opening);
    assert(g_opening_session == NULL);
    g_session = make_session(8);
    transport_close(7, 1);
    assert(g_session && g_session->generation == 8);
    transport_close(8, 1);
    /* Pending open was released without a published CLOSE event. */
    assert(!g_session && aborted == 2 && closed == 2 && freed == 3);
    puts("native close: drain, detach, idempotence, stale generation PASS");
}
'''
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'lifecycle.c'
            binary = Path(td) / 'lifecycle'
            src.write_text(harness)
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-pthread', '-fsanitize=address,undefined', str(src), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
