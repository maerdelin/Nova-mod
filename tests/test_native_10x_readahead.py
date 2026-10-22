from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = (ROOT / "scripts/native_rebuffer_patch.py").read_text()


class NativeRawFixed128Tests(unittest.TestCase):
    def test_fixed_128m_is_pre_demux_raw_source_policy(self):
        for token in (
            "NOVA_RAW_PREFETCH",
            "nova_raw_thread",
            "nova_raw_read",
            "nova_raw_seek",
            "nova_raw_open",
            "phase=pre_probe",
            "NOVA_RAW10X:",
            "NOVA_RAW_FIXED128_POLICY:",
            "NOVA_RAW_FALLBACK_CAP_BYTES   (128 * 1024 * 1024)",
            "raw->capacity_bytes = NOVA_RAW_FALLBACK_CAP_BYTES",
            "stats->buffer2_used",
            "stats->buffer2_size",
        ):
            self.assertIn(token, PATCH)

    def test_mp4_probe_uses_one_stable_raw_avio_from_open(self):
        open_start = PATCH.index("open_replacement = r'''static int ffmpeg_open_input")
        open_end = PATCH.index("static int ff_force_seek'''", open_start)
        open_block = PATCH[open_start:open_end]
        self.assertIn("nova_raw_open(", open_block)
        self.assertIn("avformat_open_input(&priv->fmt, url, NULL, options);", open_block)
        self.assertIn("phase=pre_probe", PATCH)
        self.assertNotIn("nova_raw_adopt(", PATCH)
        self.assertNotIn("avio_closep(&probe_source);", PATCH)
        self.assertIn("mp4_tail_moov_safe", PATCH)


    def test_no_post_demux_dynamic_capacity_wall(self):
        self.assertNotIn("ff_p->buffer_size" + " = s->rebuffer_capacity_bytes", PATCH)
        self.assertNotIn("NOVA_10X_PACKET_CAP_BYPASS", PATCH)
        self.assertNotIn("readahead_enabled", PATCH)
        self.assertIn(
            '"packet_queue_role": "upstream FFmpeg handoff/safety queue only; never resized to 10X"',
            PATCH,
        )

    def test_network_producer_only_uses_fixed_warehouse_fullness_for_flow_control(self):
        start = PATCH.index("static void *nova_raw_thread")
        end = PATCH.index("static int nova_raw_read", start)
        producer = PATCH[start:end]
        for forbidden in (
            "s->paused", "paused_internal", "rebuffering",
            "rebuffer_low_bytes", "rebuffer_resume_bytes",
            "video_time", "audio_time", "play_requested",
        ):
            self.assertNotIn(forbidden, producer)
        self.assertIn("raw->used_bytes >= raw->capacity_bytes", producer)
        self.assertIn("int64_t room = raw->capacity_bytes - raw->used_bytes", producer)
        self.assertIn("avio_read(raw->source, chunk->data, want)", producer)
        self.assertIn("raw->capacity_bytes = NOVA_RAW_FALLBACK_CAP_BYTES", PATCH)
        self.assertNotIn("capacity = (int)(10 * nova_x)", PATCH)

    def test_2x_5x_remain_playback_thresholds_only(self):
        self.assertIn("requested_low = 2 * nova_x", PATCH)
        self.assertIn("requested_resume = 5 * nova_x", PATCH)
        self.assertIn("resident < s->rebuffer_low_bytes", PATCH)
        self.assertIn("resident >= s->rebuffer_resume_bytes", PATCH)
        self.assertIn("NOVA_RAW_FIXED128_POLICY:", PATCH)

    def test_raw_network_interrupt_ignores_parser_seek_interrupt(self):
        start = PATCH.index("static int nova_raw_interrupt")
        end = PATCH.index("static void nova_raw_free_chunks_locked", start)
        interrupt = PATCH[start:end]
        self.assertIn("stream_abort(raw->s)", interrupt)
        self.assertNotIn("upstream_interrupt.callback", interrupt)
        self.assertNotIn("raw->upstream_interrupt.opaque", interrupt)

    def test_producer_generation_snapshot_is_serialized_with_source_position(self):
        start = PATCH.index("static void *nova_raw_thread")
        end = PATCH.index("static int nova_raw_read", start)
        producer = PATCH[start:end]
        lock = producer.index("pthread_mutex_lock(&raw->source_mutex);")
        generation = producer.index("generation = raw->generation;", lock)
        read = producer.index("int got = avio_read(raw->source, chunk->data, want);", generation)
        unlock = producer.index("pthread_mutex_unlock(&raw->source_mutex);", read)
        self.assertLess(lock, generation)
        self.assertLess(generation, read)
        self.assertLess(read, unlock)
        self.assertNotIn("generation = raw->generation;", producer[:lock])
        self.assertIn("NOVA_RAW10X_SEEK:", PATCH)
        self.assertIn("mp4_runtime_seek_race_safe", PATCH)

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
