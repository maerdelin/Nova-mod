"""Observational startup-freeze instrumentation must never change playback.

The native build separately verifies actual anchored source patches and
log markers are present in each compiled Android ABI.
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import startup_freeze_trace_patch as trace


class StartupFreezeTraceTests(unittest.TestCase):
    def test_every_marker_has_real_source_location(self):
        markers = {
            "NOVA_SYNC_BOOT": trace.BOOT_LOG,
            "NOVA_SYNC_PUT": trace.PUT_LOG,
            "NOVA_SYNC_RENDER_CLOCK": trace.RENDER_CLOCK_LOG,
            "NOVA_SYNC_LATE": trace.LATE_LOG,
            "NOVA_SYNC_LATE_END": trace.RECOVER_LOG,
            "NOVA_SYNC_SEEK_RESET": trace.SEEK_LOG,
            "NOVA_SYNC_PCM_CORRECTION": trace.CORRECTION_LOG,
            "NOVA_SYNC_AUDIO_START": trace.AUDIO_START_LOG,
            "NOVA_SYNC_PCM_EVIDENCE": trace.PCM_EVIDENCE_LOG,
        }
        for marker, source in markers.items():
            self.assertIn(marker + ":", source, marker)

    def test_no_null_dereference_on_empty_render_queue(self):
        self.assertIn("if (f && !p->nova_trace_boot_logged)", trace.BOOT_LOG)
        self.assertIn("if (!p->nova_trace_start_ms)", trace.BOOT_LOG)
        self.assertIn("p->nova_trace_boot_logged = 1;", trace.BOOT_LOG)
        self.assertNotIn("NOVA_SYNC_BOOT", trace.RENDER_CLOCK_LOG)

    def test_log_rate_and_calibration_snapshots_are_bounded(self):
        self.assertIn("180000", trace.PUT_LOG)
        self.assertIn("1000", trace.PUT_LOG)
        self.assertIn("180000", trace.RENDER_CLOCK_LOG)
        self.assertIn("1000", trace.RENDER_CLOCK_LOG)
        self.assertIn("1000", trace.LATE_LOG)
        self.assertIn("p->nova_trace_correction_logs < 48", trace.CORRECTION_LOG)
        self.assertIn("oldOffNs=%lld", trace.PUT_LOG)
        self.assertIn("newOffNs=%lld", trace.PUT_LOG)
        self.assertIn("threshold", trace.PUT_LOG.lower())
        self.assertIn("offsetNs=%lld", trace.LATE_LOG)
        self.assertIn("deadlineNs=%lld", trace.LATE_LOG)

    def test_only_one_exact_source_anchor_is_accepted(self):
        self.assertEqual(trace.once("abc", "b", "new", "one"), "anewc")
        with self.assertRaisesRegex(RuntimeError, "found 0"):
            trace.once("abc", "z", "new", "missing")
        with self.assertRaisesRegex(RuntimeError, "found 2"):
            trace.once("abab", "ab", "new", "duplicate")

    def test_patch_does_not_modify_unrelated_source(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "fake.c"
            p.write_text("before\nTARGET\nafter\n")
            trace.change(p, [("diagnostic", "TARGET", "TARGET\n/* observational marker */")])
            self.assertEqual(p.read_text(),
                             "before\nTARGET\n/* observational marker */\nafter\n")
            with self.assertRaises(RuntimeError):
                trace.change(p, [("missing", "UNIQUE_ANCHOR", "foo")])


if __name__ == "__main__":
    unittest.main()
