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
            "NOVA_REBUFFER_LOW_BYTES    (24 * 1024 * 1024)",
            "NOVA_REBUFFER_RESUME_BYTES (45 * 1024 * 1024)",
            "pst->buffer_used",
            "pst->buffer_size >= NOVA_REBUFFER_ARM_BYTES",
            "STREAM_PARSER_STATS",
        ):
            self.assertIn(token, NATIVE_PATCH)

    def test_rebuffer_pause_keeps_parser_alive(self):
        self.assertIn(
            "!s->paused || s->rebuffering || s->play_n_video_frames",
            NATIVE_PATCH,
        )
        self.assertIn("stream_pause( s )", NATIVE_PATCH)
        self.assertIn("stream_un_pause( s, 0 )", NATIVE_PATCH)
        self.assertIn("_rebuffer_thread", NATIVE_PATCH)

    def test_manual_pause_is_separate_from_internal_buffering(self):
        self.assertIn("rebuffer_user_paused", NATIVE_PATCH)
        self.assertIn("manual pause issued while buffering", NATIVE_PATCH)
        self.assertIn("video->s->rebuffering", NATIVE_PATCH)

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
