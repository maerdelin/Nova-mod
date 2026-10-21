from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = (ROOT / "scripts/native_rebuffer_patch.py").read_text()


class NativeRaw10XTests(unittest.TestCase):
    def test_10x_is_pre_demux_raw_source_policy(self):
        for token in (
            "NOVA_RAW_PREFETCH",
            "nova_raw_thread",
            "nova_raw_read",
            "nova_raw_seek",
            "NOVA_RAW10X:",
            "NOVA_RAW_10X_POLICY:",
            "capacity = (int)(10 * nova_x)",
            "stats->buffer2_used",
            "stats->buffer2_size",
        ):
            self.assertIn(token, PATCH)

    def test_no_post_demux_10x_wall(self):
        self.assertNotIn("ff_p->buffer_size = s->rebuffer_capacity_bytes", PATCH)
        self.assertNotIn("NOVA_10X_PACKET_CAP_BYPASS", PATCH)
        self.assertNotIn("readahead_enabled", PATCH)
        self.assertIn(
            '"packet_queue_role": "upstream FFmpeg handoff/safety queue only; never resized to 10X"',
            PATCH,
        )

    def test_network_producer_does_not_depend_on_pause_or_decoder(self):
        start = PATCH.index("static void *nova_raw_thread")
        end = PATCH.index("static int nova_raw_read", start)
        producer = PATCH[start:end]
        self.assertNotIn("s->paused", producer)
        self.assertNotIn("video_time", producer)
        self.assertNotIn("audio_time", producer)
        self.assertIn("raw->used_bytes >= raw->capacity_bytes", producer)

    def test_manual_pause_needs_no_parser_readahead_flag(self):
        self.assertIn("parser continues only during internal rebuffer", PATCH)
        self.assertIn("__atomic_load_n( &s->rebuffering", PATCH)
        self.assertNotIn("readahead_enabled", PATCH)

    def test_playback_controller_uses_raw_plus_packet_resident_bytes(self):
        self.assertIn("pst->buffer_used +", PATCH)
        self.assertIn("pst->buffer2_used", PATCH)
        self.assertIn("resident < s->rebuffer_low_bytes", PATCH)
        self.assertIn("resident >= s->rebuffer_resume_bytes", PATCH)
        self.assertIn("source_eof", PATCH)

    def test_no_java_fifo_or_parallel_downloader(self):
        self.assertFalse((ROOT / "webdav_fixes/src/com/archos/filecorelibrary/NovaAsyncReadAheadInputStream.java").exists())
        self.assertFalse((ROOT / "webdav_fixes/src/com/archos/filecorelibrary/NovaAheadInputStream.java").exists())
        self.assertFalse((ROOT / "scripts/readahead_patch.py").exists())


if __name__ == "__main__":
    unittest.main()
