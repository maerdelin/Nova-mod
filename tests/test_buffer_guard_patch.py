import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYER_PATCH = (ROOT / "scripts/buffer_guard_patch.py").read_text()
NATIVE_PATCH = (ROOT / "scripts/native_rebuffer_patch.py").read_text()
BUILD = (ROOT / "scripts/granular_build.py").read_text()


class RawBufferArchitectureChecks(unittest.TestCase):
    def test_packet_queue_is_only_fixed_handoff_safety(self):
        self.assertIn("PACKET_HANDOFF_MIB = 24", PLAYER_PATCH)
        self.assertIn('"webdav_special_packet_buffer": False', PLAYER_PATCH)
        self.assertNotIn("0x80", PLAYER_PATCH)
        self.assertIn("setStreamBufferSize(I)V", PLAYER_PATCH)

    def test_raw_source_owns_dynamic_2x_5x_10x(self):
        for token in (
            "low = (int)(2 * nova_x)",
            "resume = (int)(5 * nova_x)",
            "capacity = (int)(10 * nova_x)",
            "nova_raw_set_policy",
            "NOVA_RAW_10X_POLICY:",
        ):
            self.assertIn(token, NATIVE_PATCH)
        self.assertNotIn("ff_p->buffer_size = s->rebuffer_capacity_bytes", NATIVE_PATCH)

    def test_buffering_events_remain_standard_media_info(self):
        self.assertIn("STREAM_BUFFERING_START", NATIVE_PATCH)
        self.assertIn("STREAM_BUFFERING_END", NATIVE_PATCH)
        self.assertIn("MEDIA_INFO_BUFFERING_START", NATIVE_PATCH)
        self.assertIn("MEDIA_INFO_BUFFERING_END", NATIVE_PATCH)

    def test_build_overlays_only_rebuilt_avos_for_native_change(self):
        self.assertIn("overlay_native", BUILD)
        self.assertIn("libavos.so", BUILD)
        self.assertNotIn("NovaAsyncReadAheadInputStream", BUILD)


if __name__ == "__main__":
    unittest.main()
