from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = (ROOT / "scripts/native_rebuffer_patch.py").read_text()
ISO = (ROOT / "scripts/iso_single_stream_qos_patch.py").read_text()
THROUGHPUT = (ROOT / "scripts/stream_throughput_patch.py").read_text()
WORKFLOW = (ROOT / ".github/workflows/nova-video-player-mod.yml").read_text()


class DownloadArchitectureTests(unittest.TestCase):
    def test_native_patch_is_direct_final_fixed128_ring(self):
        for token in (
            "uint8_t *ring;",
            "raw->ring = av_malloc(NOVA_RAW_FALLBACK_CAP_BYTES)",
            "#define NOVA_RAW_IO_BYTES",
            "NOVA_RAW128:",
            "NOVA_RAW128_SEEK:",
            "NOVA_RAW_FIXED128_POLICY:",
        ):
            self.assertIn(token, NATIVE)
        legacy = (
            "NOVA_RAW_" + "CHUNK",
            "NOVA_RAW" + "10X",
            "dynamic raw " + "10X",
            "raw producer cap=" + "10X",
        )
        for token in legacy:
            self.assertNotIn(token, NATIVE)

    def test_raw_producer_is_playback_state_independent(self):
        start = NATIVE.index("static void *nova_raw_thread")
        end = NATIVE.index("static int nova_raw_read", start)
        producer = NATIVE[start:end]
        for token in (
            "s->paused", "paused_internal", "rebuffer_low_bytes",
            "rebuffer_resume_bytes", "video_time", "audio_time",
            "play_requested",
        ):
            self.assertNotIn(token, producer)
        self.assertIn("raw->used_bytes >= raw->capacity_bytes", producer)

    def test_seek_ring_offset_and_generation_are_serialized(self):
        start = NATIVE.index("static void *nova_raw_thread")
        end = NATIVE.index("static int nova_raw_read", start)
        producer = NATIVE[start:end]
        lock = producer.index("pthread_mutex_lock(&raw->source_mutex);")
        generation = producer.index("generation = raw->generation", lock)
        write_off = producer.index("write_off = raw->write_off", lock)
        read = producer.index("avio_read(raw->source, raw->ring + write_off, want)", lock)
        self.assertLess(lock, generation)
        self.assertLess(lock, write_off)
        self.assertLess(write_off, read)

    def test_raw_code_is_one_contiguous_final_implementation(self):
        self.assertEqual(NATIVE.count("RAW_CODE = r'''"), 1)
        self.assertEqual(NATIVE.count("PLAYBACK_SCHED = r'''"), 1)
        self.assertNotIn("RAW_CONSUMER =", NATIVE)
        start = NATIVE.index("RAW_CODE =")
        end = NATIVE.index("DYNAMIC_POLICY =", start)
        raw = NATIVE[start:end]
        for token in (
            "static void *nova_raw_thread",
            "static int nova_raw_read",
            "static int64_t nova_raw_seek",
            "static int nova_raw_open",
            "static void nova_raw_close",
        ):
            self.assertIn(token, raw)
        ps = NATIVE.index("PLAYBACK_SCHED =")
        pe = NATIVE.index("def patch_stream_h", ps)
        playback = NATIVE[ps:pe]
        self.assertNotIn("nova_raw_seek", playback)
        self.assertNotIn("nova_raw_open", playback)
        self.assertNotIn("nova_raw_close", playback)

    def test_download_qos_and_playback_yield_live_in_native_patch(self):
        for token in (
            "NOVA_RAW_SCHED:",
            "requested_nice = -8",
            "NOVA_PLAYBACK_SCHED:",
            "nova_playback_yield_sched",
            "sched_setaffinity",
            "cpuinfo_max_freq",
        ):
            self.assertIn(token, NATIVE)

    def test_iso_is_single_persistent_stream(self):
        for token in (
            "NOVA_ISO_SINGLE_STREAM", "parallelRange=0", "persistentRange=1",
            'nova_iso_boost_thread("iso-title", -8)',
            'nova_iso_boost_thread("iso-server", -4)',
        ):
            self.assertIn(token, ISO)

    def test_throughput_patch_is_live(self):
        self.assertIn("0x400000    # nova WebDAV playback read-ahead 4MiB", THROUGHPUT)
        self.assertIn("0x100000    # nova localhost copy 1MiB", THROUGHPUT)
        self.assertIn("stream_throughput_patch.apply", (ROOT / "scripts/granular_build.py").read_text())

    def test_workflow_has_no_second_native_transform(self):
        self.assertIn("python3 scripts/native_rebuffer_patch.py native-src/native/avos", WORKFLOW)
        self.assertIn("python3 scripts/iso_single_stream_qos_patch.py iso/nova_iso.c", WORKFLOW)
        self.assertNotIn("aggressive_" + "download_patch.py", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
