from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = (ROOT / "scripts/native_rebuffer_patch.py").read_text()


class NativeRawFixed128Tests(unittest.TestCase):
    def test_fixed128_is_pre_demux_raw_source_policy(self):
        for token in (
            "NOVA_RAW_PREFETCH", "nova_raw_thread", "nova_raw_read",
            "nova_raw_seek", "nova_raw_open", "phase=pre_probe",
            "NOVA_RAW128:", "NOVA_RAW128_SEEK:",
            "NOVA_RAW_FIXED128_POLICY:",
            "NOVA_RAW_FALLBACK_CAP_BYTES   (128 * 1024 * 1024)",
            "raw->capacity_bytes = NOVA_RAW_FALLBACK_CAP_BYTES",
            "stats->buffer2_used", "stats->buffer2_size",
        ):
            self.assertIn(token, PATCH)

    def test_one_stable_raw_avio_is_installed_before_probe(self):
        start = PATCH.index("open_replacement = r'''static int ffmpeg_open_input")
        end = PATCH.index("static int ff_force_seek'''", start)
        block = PATCH[start:end]
        self.assertIn("nova_raw_open(", block)
        self.assertIn("avformat_open_input(&priv->fmt, url, NULL, options);", block)
        self.assertIn("mp4_tail_moov_safe", PATCH)
        self.assertIn("mp4_runtime_seek_race_safe", PATCH)

    def test_no_post_demux_producer_wall(self):
        self.assertNotIn("ff_p->buffer_size" + " = s->rebuffer_capacity_bytes", PATCH)
        self.assertIn(
            '"packet_queue_role": "upstream FFmpeg handoff/safety queue only; never used as a producer wall"',
            PATCH,
        )

    def test_fixed_ring_is_preallocated_and_reused(self):
        self.assertIn("uint8_t *ring;", PATCH)
        self.assertIn("raw->ring = av_malloc(NOVA_RAW_FALLBACK_CAP_BYTES)", PATCH)
        self.assertIn("raw->read_off", PATCH)
        self.assertIn("raw->write_off", PATCH)
        self.assertNotIn("NOVA_RAW_" + "CHUNK", PATCH)

    def test_network_producer_only_stops_for_fullness_or_lifecycle(self):
        start = PATCH.index("static void *nova_raw_thread")
        end = PATCH.index("static int nova_raw_read", start)
        producer = PATCH[start:end]
        for token in (
            "s->paused", "paused_internal", "rebuffering",
            "rebuffer_low_bytes", "rebuffer_resume_bytes",
            "video_time", "audio_time", "play_requested",
        ):
            self.assertNotIn(token, producer)
        self.assertIn("raw->used_bytes >= raw->capacity_bytes", producer)
        self.assertIn("avio_read(raw->source, raw->ring + write_off, want)", producer)

    def test_dynamic_2x_5x_are_playback_thresholds_only(self):
        self.assertIn("requested_low = 2 * nova_x", PATCH)
        self.assertIn("requested_resume = 5 * nova_x", PATCH)
        self.assertIn("resident < s->rebuffer_low_bytes", PATCH)
        self.assertIn("resident >= s->rebuffer_resume_bytes", PATCH)

    def test_seek_generation_and_ring_offset_are_serialized(self):
        start = PATCH.index("static void *nova_raw_thread")
        end = PATCH.index("static int nova_raw_read", start)
        producer = PATCH[start:end]
        lock = producer.index("pthread_mutex_lock(&raw->source_mutex);")
        generation = producer.index("generation = raw->generation", lock)
        write_off = producer.index("write_off = raw->write_off", lock)
        read = producer.index("avio_read(raw->source, raw->ring + write_off, want)", lock)
        unlock = producer.index("pthread_mutex_unlock(&raw->source_mutex);", read)
        self.assertLess(lock, generation)
        self.assertLess(lock, write_off)
        self.assertLess(write_off, read)
        self.assertLess(read, unlock)

    def test_return_shutdown_stops_raw_before_parser_join(self):
        for token in (
            "void nova_raw_request_stop(STREAM *s)",
            "NOVA_RAW_ABORT: reason=stream_stop",
            "NOVA_RAW_ABORT: reason=source_abort",
            '"stop RAW before parser join"',
            '"\\tnova_raw_request_stop( s );\\n"',
        ):
            self.assertIn(token, PATCH)

        producer_start = PATCH.index("static void *nova_raw_thread")
        producer_end = PATCH.index("static int nova_raw_read", producer_start)
        producer = PATCH[producer_start:producer_end]
        self.assertLess(
            producer.index("NOVA_RAW_ABORT: reason=source_abort"),
            producer.index("NOVA_RAW_RETRY:"),
        )
        self.assertIn("pthread_cond_broadcast(&raw->can_read);", PATCH)
        self.assertIn("pthread_cond_broadcast(&raw->can_write);", PATCH)

    def test_manual_pause_does_not_need_network_readahead_flag(self):
        self.assertIn("parser continues only during internal rebuffer", PATCH)
        self.assertNotIn("readahead_enabled", PATCH)


if __name__ == "__main__":
    unittest.main()
