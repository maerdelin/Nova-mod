import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = (ROOT / "scripts" / "stream_throughput_patch.py").read_text()
NATIVE = (ROOT / "scripts" / "native_rebuffer_patch.py").read_text()
BUILD = (ROOT / "scripts" / "granular_build.py").read_text()


class StreamThroughputStaticChecks(unittest.TestCase):
    def test_webdav_playback_upstream_is_four_mib(self):
        self.assertIn("WebdavFileEditor", PATCH)
        self.assertIn("->PLAYBACK:", PATCH)
        self.assertIn("if-eqz p2", PATCH)
        self.assertIn("0x400000    # nova WebDAV playback read-ahead 4MiB", PATCH)

    def test_localhost_copy_is_one_mib(self):
        self.assertIn("handleResponse()V", PATCH)
        self.assertIn("0x100000", PATCH)
        self.assertIn("localhost copy 1MiB", PATCH)
        self.assertIn("nova WebDAV source priority -8", PATCH)
        self.assertIn("Landroid/os/Process;->setThreadPriority(I)V", PATCH)

    def test_transport_tuning_does_not_own_raw_fixed128_policy(self):
        self.assertIn("NOVA_RAW_FALLBACK_LOW_BYTES", NATIVE)
        self.assertIn("NOVA_RAW_FALLBACK_RESUME_BYTES", NATIVE)
        self.assertIn("NOVA_RAW_FALLBACK_CAP_BYTES   (128 * 1024 * 1024)", NATIVE)
        self.assertIn("NOVA_RAW_FIXED128_POLICY:", NATIVE)
        self.assertNotIn("capacity = (int)(10 * nova_x)", NATIVE)
        self.assertNotIn("stream_throughput_patch", NATIVE)

    def test_build_applies_throughput_after_webdav_marker(self):
        self.assertIn("import stream_throughput_patch", BUILD)
        self.assertIn(
            "stream_throughput_patch.apply(candidate, args.reports / 'stream-throughput.json')",
            BUILD,
        )


if __name__ == "__main__":
    unittest.main()
