import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYER_PATCH = (ROOT / "scripts" / "buffer_guard_patch.py").read_text()
NATIVE_PATCH = (ROOT / "scripts" / "native_rebuffer_patch.py").read_text()
BUILD = (ROOT / "scripts" / "granular_build.py").read_text()


class NativeRebufferStaticChecks(unittest.TestCase):
    def test_java_only_marks_webdav_buffer_size(self):
        self.assertIn('"webdav_native_buffer_mib": 128', PLAYER_PATCH)
        self.assertIn("setStreamBufferSize(I)V", PLAYER_PATCH)
        self.assertNotIn("PLAYER_NATIVE_PAUSE", PLAYER_PATCH)
        self.assertNotIn("PLAYER_NATIVE_RESUME", PLAYER_PATCH)
        self.assertNotIn("NovaPrefetchInputStream", PLAYER_PATCH)

    def test_native_uses_real_parser_queue_bytes(self):
        for token in (
            "pst->buffer_used",
            "pst->buffer_size == s->rebuffer_capacity_bytes",
            "used < s->rebuffer_low_bytes",
            "used >= s->rebuffer_resume_bytes",
            "STREAM_PARSER_STATS",
            "s->rebuffer_low_bytes = (int)(2 * nova_x)",
            "s->rebuffer_resume_bytes = (int)(5 * nova_x)",
            "s->rebuffer_capacity_bytes = (int)(10 * nova_x)",
            "ff_p->buffer_size = s->rebuffer_capacity_bytes",
            "NOVA_DYNAMIC_BUFFER: mode=average",
            "NOVA_DYNAMIC_BUFFER: mode=fallback",
        ):
            self.assertIn(token, NATIVE_PATCH)

    def test_rebuffer_pause_keeps_parser_alive(self):
        self.assertIn(
            "!s->paused || __atomic_load_n( &s->rebuffering, __ATOMIC_ACQUIRE )",
            NATIVE_PATCH,
        )
        self.assertIn("stream_pause( s )", NATIVE_PATCH)
        self.assertIn("stream_un_pause( s, 0 )", NATIVE_PATCH)
        self.assertIn("_rebuffer_thread", NATIVE_PATCH)

    def test_rebuffer_cannot_enter_during_prepare_or_preroll(self):
        self.assertIn("rebuffer_play_requested", NATIVE_PATCH)
        self.assertIn("rebuffer_frame_seen", NATIVE_PATCH)
        self.assertIn("play_requested && frame_seen", NATIVE_PATCH)
        self.assertIn("real play arms rebuffer lifecycle", NATIVE_PATCH)
        self.assertIn("prove first frame reached video sink", NATIVE_PATCH)
        self.assertIn("reset rebuffer first-frame proof on seek", NATIVE_PATCH)

        def can_enter(play_requested, frame_seen, paused, used):
            return (
                play_requested
                and frame_seen
                and not paused
                and used < 24 * 1024 * 1024
            )

        self.assertFalse(can_enter(False, False, False, 0))
        self.assertFalse(can_enter(True, False, False, 0))
        self.assertFalse(can_enter(False, True, False, 0))
        self.assertFalse(can_enter(True, True, True, 0))
        self.assertTrue(can_enter(True, True, False, 0))

    def test_manual_pause_is_separate_from_internal_buffering(self):
        self.assertIn("rebuffer_user_paused", NATIVE_PATCH)
        self.assertIn("Manual pause issued while buffering", NATIVE_PATCH)
        self.assertIn("manual pause disarms rebuffer lifecycle", NATIVE_PATCH)
        self.assertIn(
            "__atomic_store_n(&video->s->rebuffer_play_requested, 0, __ATOMIC_RELEASE)",
            NATIVE_PATCH,
        )

    def test_run340_start_swallow_regression_is_gated(self):
        start_marker = NATIVE_PATCH.index("real play arms rebuffer lifecycle")
        window = NATIVE_PATCH[max(0, start_marker - 2500):start_marker + 500]
        self.assertIn(
            "__atomic_store_n(&video->s->rebuffer_play_requested, 1, __ATOMIC_RELEASE)",
            window,
        )
        self.assertIn(
            "__atomic_store_n(&video->s->rebuffer_frame_seen, 0, __ATOMIC_RELEASE)",
            window,
        )
        self.assertIn(
            "__atomic_load_n(&video->s->rebuffering, __ATOMIC_ACQUIRE)",
            window,
        )

    def test_native_buffering_events_are_standard_media_info(self):
        self.assertIn("STREAM_BUFFERING_START", NATIVE_PATCH)
        self.assertIn("STREAM_BUFFERING_END", NATIVE_PATCH)
        self.assertIn("MEDIA_INFO_BUFFERING_START", NATIVE_PATCH)
        self.assertIn("MEDIA_INFO_BUFFERING_END", NATIVE_PATCH)

    def test_old_java_prefetch_chain_is_not_built(self):
        self.assertNotIn("import prefetch_guard_patch", BUILD)
        self.assertNotIn("prefetch_guard_patch.apply", BUILD)
        self.assertNotIn("fix_generated_guard.apply", BUILD)
        self.assertIn("overlay_native", BUILD)
        self.assertIn("libavos.so", BUILD)


if __name__ == "__main__":
    unittest.main()
