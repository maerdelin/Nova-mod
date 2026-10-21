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
            "nova_raw_adopt",
            "phase=post_probe",
            "NOVA_RAW10X:",
            "NOVA_RAW_10X_POLICY:",
            "capacity = (int)(10 * nova_x)",
            "stats->buffer2_used",
            "stats->buffer2_size",
        ):
            self.assertIn(token, PATCH)

    def test_probe_keeps_native_ffmpeg_url_io_until_after_format_parse(self):
        open_start = PATCH.index("open_replacement = r'''static int ffmpeg_open_input")
        open_end = PATCH.index("static int ff_force_seek'''", open_start)
        open_block = PATCH[open_start:open_end]
        self.assertIn("Keep FFmpeg's native URL AVIO through open+probe", open_block)
        self.assertIn("return avformat_open_input(&priv->fmt, url, NULL, options);", open_block)
        self.assertNotIn("nova_raw_adopt(", open_block)

        self.assertIn('"\\tif (_parse_format(s->etype, ff_p)) goto ErrorExit4;\\n\\n"', PATCH)
        self.assertIn('"\\tif (_parse_format(s->etype, ff_p)) goto ErrorExit4;\\n"', PATCH)
        self.assertIn('"\\t\\tint nova_raw_result = nova_raw_adopt(\\n"', PATCH)
        self.assertIn('"adopt native raw producer only after FFmpeg probe"', PATCH)
        self.assertIn("mp4_tail_moov_safe", PATCH)

    def test_no_post_demux_10x_wall(self):
        self.assertNotIn("ff_p->buffer_size" + " = s->rebuffer_capacity_bytes", PATCH)
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
