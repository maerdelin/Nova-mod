"""NOVA #977: no speculative 4MiB curl before actual MKV first frame.

Source contracts are backed by a real signed-APK stalled-CDN smoke test.
The original 2026-10-30 trace had http=302 curl=28 and zero bytes for
10.28 s after a valid first canonical Java range.
"""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class StartupMkvCanonicalFirst(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.transport=(ROOT/"iso/nova_transport.c").read_text()
        cls.patch=(ROOT/"scripts/native_rebuffer_patch.py").read_text()
        cls.lite=(ROOT/"iso/nova_literange4.inc").read_text()

    def test_mkv_only_until_first_render_and_bounded_failsafe(self):
        t=self.transport
        read=t.split("int nova_transport_read(uint64_t generation, uint8_t *dst, int size)\n{",1)[1]
        read=read.split("__attribute__((visibility(\"default\")))",1)[0]
        self.assertIn("startup_mkv_canonical = s->file_http_mode &&",read)
        self.assertIn("!__atomic_load_n(&s->startup_first_frame_ready",read)
        self.assertIn("!__atomic_load_n(&s->startup_probe_complete",read)
        self.assertIn("s->startup_canonical_bytes < 32ULL*1024ULL*1024ULL",read)
        self.assertIn("if (s->multi_seek_guard || startup_mkv_canonical)",read)
        self.assertIn("nova_mkv_single_get_read(s, dst, size)",read)
        self.assertIn("nova_multi_stop(s,\"startup-canonical-first\",0)",read)
        self.assertLess(read.index("if (s->multi_seek_guard || startup_mkv_canonical)"),
                        read.index("} else if (s->multi_active)"))
        self.assertIn("NOVA_STARTUP_MKV_CANONICAL_FIRST_V1",read)

    def test_actual_first_frame_callback_uses_generation(self):
        t=self.transport
        cb=t.split("void nova_transport_mark_first_frame(",1)[1].split(
            "int nova_transport_set_target_bps(",1)[0]
        self.assertIn("session_acquire(generation)",cb)
        self.assertIn("s->mode==NOVA_MODE_FILE && s->file_http_mode",cb)
        self.assertIn("__atomic_exchange_n(&s->startup_first_frame_ready,1",cb)
        self.assertIn("session_release(s)",cb)
        p=self.patch
        self.assertIn("nova_startup_mkv_first_frame(s->src.url)",p)
        self.assertIn("NOVA_STARTUP_TRACE first_frame_sink",p)
        self.assertIn("dlsym(transport,\"nova_transport_mark_first_frame\")",p)
        self.assertIn("strncmp(url,\"novatransport://\",16)",p)

    def test_required_abi_exports_are_explicit(self):
        for member,return_type in (("nova_transport_set_target_bps","int"),
                                   ("nova_transport_mark_first_frame","void")):
            self.assertIn(
                '__attribute__((visibility("default")))\n'+return_type+' '+member+'(',
                self.transport,
                'AVOS resolves this symbol via dlsym before RAW startup'
            )

    def test_existing_progressive_raw_and_w2_unmodified(self):
        p=self.patch
        self.assertIn("pthread_create(&raw->thread, NULL, nova_raw_thread, raw)",p)
        self.assertIn("raw->used_bytes >= raw->capacity_bytes",p)
        self.assertIn("pthread_cond_wait(&raw->can_write, &raw->mutex)",p)
        self.assertIn("NOVA_RAW_FIXED128_POLICY",p)
        t=self.transport
        self.assertIn("nova_multi_start(s, s->file_cursor, 1)",t)
        self.assertIn("nova_multi_recoverable_range_error",t)
        self.assertIn("NOVA_MULTI_SEEK_GUARD_BEGIN",t)
        self.assertIn("NOVA_MULTI_HTTP403_COOLDOWN",t)
        self.assertIn("NOVA_LITERANGE4_START",self.lite)
        self.assertIn("CURLOPT_SSL_VERIFYPEER,1L",self.lite)

if __name__=="__main__":
    unittest.main()
