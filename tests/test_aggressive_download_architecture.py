from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = (ROOT / "scripts/aggressive_download_patch.py").read_text()
WORKFLOW = (ROOT / ".github/workflows/nova-video-player-mod.yml").read_text()
THROUGHPUT = (ROOT / "scripts/stream_throughput_patch.py").read_text()


class AggressiveDownloadArchitectureTests(unittest.TestCase):
    def test_raw_warehouse_is_preallocated_ring(self):
        for token in (
            "NOVA_AGGRESSIVE_RAW_RING",
            "raw->ring = av_malloc(NOVA_RAW_FALLBACK_CAP_BYTES)",
            "NOVA_RAW_IO_BYTES             (128 * 1024)",
            "raw->used_bytes >= raw->capacity_bytes",
        ):
            self.assertIn(token, PATCH)
        start = PATCH.index("RAW_PRODUCER =")
        end = PATCH.index("RAW_CONSUMER =", start)
        producer = PATCH[start:end]
        self.assertNotIn("amalloc(sizeof(NOVA_RAW_CHUNK))", producer)

    def test_raw_producer_has_no_playback_flow_control(self):
        start = PATCH.index("RAW_PRODUCER =")
        end = PATCH.index("RAW_CONSUMER =", start)
        producer = PATCH[start:end]
        for forbidden in (
            "s->paused", "paused_internal", "rebuffer_low_bytes",
            "rebuffer_resume_bytes", "video_time", "audio_time",
            "play_requested",
        ):
            self.assertNotIn(forbidden, producer)
        self.assertIn("raw->used_bytes >= raw->capacity_bytes", producer)
        self.assertIn("NOVA_RAW_RETRY:", producer)

    def test_download_threads_get_fast_cpu_and_priority_requests(self):
        for token in (
            "NOVA_RAW_SCHED:",
            "requested_nice = -8",
            'nova_iso_boost_thread("iso-title", -8)',
            'nova_iso_boost_thread("iso-server", -4)',
            "sched_setaffinity",
            "cpuinfo_max_freq",
        ):
            self.assertIn(token, PATCH)

    def test_parser_and_decode_yield_resources(self):
        self.assertIn('nova_playback_yield_sched("parser", 5)', PATCH)
        self.assertIn('nova_playback_yield_sched("decode", 8)', PATCH)
        self.assertIn("reservedFast0", PATCH)
        self.assertIn("reservedFast1", PATCH)

    def test_parallel_range_is_hard_banned_and_single_stream_is_required(self):
        forbidden = (
            "PREFETCH_WORKERS",
            "iso_prefetch_worker",
            "prefetch_threads",
            "prefetch_generation",
            "parallel_range=1",
            "PREFETCH_BEGIN worker=",
            "PREFETCH_READY worker=",
            "PREFETCH_DISCARD worker=",
        )
        for token in forbidden:
            self.assertNotIn(token, PATCH)
        self.assertIn("NOVA_ISO_SINGLE_STREAM", PATCH)
        self.assertIn("parallelRange=0", PATCH)
        self.assertIn("persistentRange=1", PATCH)
        self.assertIn('nova_iso_boost_thread("iso-title", -8)', PATCH)
        self.assertIn("PARALLEL_BANNED_SOURCE", AUDIT)

    def test_seek_generation_safety_is_preserved(self):
        self.assertIn("generation = raw->generation", PATCH)
        self.assertIn("generation != raw->generation", PATCH)
        self.assertNotIn("prefetch_generation", PATCH)

    def test_workflow_applies_aggressive_patch_before_builds(self):
        native = "python3 scripts/aggressive_download_patch.py --native native-src/native/avos"
        iso = "python3 scripts/aggressive_download_patch.py --iso iso/nova_iso.c"
        self.assertIn(native, WORKFLOW)
        self.assertIn(iso, WORKFLOW)

    def test_localhost_copy_is_one_mib(self):
        self.assertIn("0x100000    # nova localhost copy 1MiB", THROUGHPUT)
        self.assertIn('"localhost_copy_bytes": 1048576', THROUGHPUT)
        self.assertIn("0x400000    # nova WebDAV playback read-ahead 4MiB", THROUGHPUT)
        self.assertIn('"webdav_playback_upstream_bytes": 4194304', THROUGHPUT)
        self.assertIn("Landroid/os/Process;->setThreadPriority(I)V", THROUGHPUT)


if __name__ == "__main__":
    unittest.main()
