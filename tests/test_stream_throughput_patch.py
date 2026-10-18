import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = (ROOT / "scripts" / "stream_throughput_patch.py").read_text()
NATIVE = (ROOT / "scripts" / "native_rebuffer_patch.py").read_text()
BUILD = (ROOT / "scripts" / "granular_build.py").read_text()


class StreamThroughputStaticChecks(unittest.TestCase):
    def test_webdav_playback_upstream_is_one_mib(self):
        self.assertIn("WebdavFileEditor", PATCH)
        self.assertIn("->PLAYBACK:", PATCH)
        self.assertIn("if-eqz p2", PATCH)
        self.assertIn("const {mode}, 0x100000", PATCH)

    def test_localhost_copy_is_128_kib(self):
        self.assertIn("handleResponse()V", PATCH)
        self.assertIn("0x20000", PATCH)
        self.assertIn("localhost copy 128KiB", PATCH)

    def test_native_rebuffer_policy_is_not_changed(self):
        self.assertIn("NOVA_REBUFFER_LOW_BYTES    (24 * 1024 * 1024)", NATIVE)
        self.assertIn("NOVA_REBUFFER_RESUME_BYTES (45 * 1024 * 1024)", NATIVE)
        self.assertNotIn("stream_throughput_patch", NATIVE)

    def test_build_applies_throughput_after_webdav_marker(self):
        self.assertIn("import stream_throughput_patch", BUILD)
        self.assertIn(
            "stream_throughput_patch.apply(candidate, args.reports / 'stream-throughput.json')",
            BUILD,
        )


if __name__ == "__main__":
    unittest.main()
