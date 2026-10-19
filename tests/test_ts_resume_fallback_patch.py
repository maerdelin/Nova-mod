"""Regression tests for TS out-of-range bookmark startup fallback."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.ts_resume_fallback_patch import ANCHOR, is_invalid_startup_bookmark, transform


class TestTSResumeFallback(unittest.TestCase):
    def test_real_invalid_bookmarks(self):
        self.assertTrue(is_invalid_startup_bookmark(True, True, 0, 933206))
        self.assertTrue(is_invalid_startup_bookmark(True, True, 0, 5336807))

    def test_only_startup_ts_no_duration(self):
        self.assertFalse(is_invalid_startup_bookmark(False, True, 0, 933206))
        self.assertFalse(is_invalid_startup_bookmark(True, False, 0, 933206))
        self.assertFalse(is_invalid_startup_bookmark(True, True, 100, 933206))
        self.assertFalse(is_invalid_startup_bookmark(True, True, 0, 1000))
        self.assertFalse(is_invalid_startup_bookmark(True, True, 0, 0))

    def test_patcher_is_narrow(self):
        source = "BEGIN\nint avos_mp_video_seek(void) {\n" + ANCHOR + "\n}\nEND\n"
        result = transform(source)
        self.assertEqual(result.count(ANCHOR), 1)
        self.assertIn("NOVA_TS_RESUME_FALLBACK:", result)
        self.assertIn("pos > STREAM_POS_MAX", result)
        self.assertIn("video->s->etype == ETYPE_MPEG_TS", result)
        self.assertIn("video->s->no_duration && wind_start == 0", result)
        self.assertLess(result.index("NOVA_TS_RESUME_FALLBACK:"), result.index(ANCHOR))
        self.assertTrue(result.startswith("BEGIN\n"))
        self.assertTrue(result.endswith("\nEND\n"))

    def test_fails_closed_if_anchors_change(self):
        with self.assertRaises(RuntimeError):
            transform("missing")
        source = "int avos_mp_video_seek(void) {\n" + ANCHOR + "\n}\n"
        with self.assertRaises(RuntimeError):
            transform(transform(source))


if __name__ == "__main__":
    unittest.main()
