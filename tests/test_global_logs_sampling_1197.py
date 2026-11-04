#!/usr/bin/env python3
"""1197 source-level regression: no OFF diagnostic sampling on identified paths."""
from __future__ import annotations
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "global_logs_sampling_1197_patch", ROOT / "scripts/global_logs_sampling_1197_patch.py")
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)


class OffSamplingRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before_t = (ROOT / "iso/nova_transport.c").read_text()
        cls.before_l = (ROOT / "iso/nova_literange4.inc").read_text()
        cls.after_t = PATCH.patch_transport(cls.before_t)
        cls.after_l = PATCH.patch_literange(cls.before_l)

    def test_iso_counters_and_timing_guarded(self):
        source = self.after_t
        for part in (
            "if(nova_global_log_enabled()) ++s->iso_meta_reads;",
            "if(nova_global_log_enabled()) ++s->iso_meta_hits;",
            "if(nova_global_log_enabled()) ++s->iso_meta_misses;",
            "if(nova_global_log_enabled()) s->iso_meta_fetched += (uint64_t)got;",
            "if (nova_global_log_enabled() && page_bytes > s->iso_meta_peak_window)",
            "int64_t fetch_start_ms=nova_global_log_enabled()?nova_iso_uptime_ms():0;",
            "int64_t fetch_seek_ms=fetch_start_ms && nova_global_log_enabled()?",
            "int64_t scan_start_ms = nova_global_log_enabled()?nova_iso_uptime_ms():0;",
            "int64_t select_start_ms = nova_global_log_enabled()?nova_iso_uptime_ms():0;",
            "int64_t iso_start_ms = (iso && nova_global_log_enabled()) ? nova_iso_uptime_ms() : 0;",
        ):
            self.assertIn(part, source, part)
        self.assertEqual(source.count(
            "stage_start_ms = nova_global_log_enabled()?nova_iso_uptime_ms():0;"), 2)

    def test_literange_diagnostic_only_sampling_guarded(self):
        source = self.after_l
        for part in (
            "if(nova_global_log_enabled()) p->owner->received_sample_bytes+=(uint64_t)bytes;",
            "if(nova_global_log_enabled()) e->committed_sample_bytes+=(uint64_t)take;",
            "if(nova_global_log_enabled() && waited_ms>=NOVA_LITE_WAIT_TRIGGER_MS)",
            "uint64_t delivered=0, received=0;",
            "if(nova_global_log_enabled()){\n        delivered=e->committed_sample_bytes",
        ):
            self.assertIn(part, source, part)

    def test_business_control_and_data_paths_byte_identical(self):
        # These branches and media-byte accounting MUST NOT be changed.
        for text in (
            "entry->touched = ++s->iso_meta_tick;",
            "s->iso_meta_window_bytes*=2;",
            "read_exact(s->upstream, staging, request)",
            "if (select_main_title(s) < 0)",
            "__atomic_add_fetch(&s->startup_wire_bytes",
        ):
            self.assertEqual(self.after_t.count(text), self.before_t.count(text), text)
        for text in (
            "if(target>0 && s->multi_active_lanes<2",
            "s->multi_active_lanes=2;",
            "s->multi_committed_cursor+=take;",
            "nova_lite_schedule(s);",
            "__atomic_add_fetch(&p->owner->session->startup_wire_bytes",
            "e->last_sample_ms=now;",
        ):
            self.assertEqual(self.after_l.count(text), self.before_l.count(text), text)

    def test_fail_closed_on_source_drift(self):
        with self.assertRaisesRegex(RuntimeError, "expected 1 exact source anchor"):
            PATCH.patch_transport(self.before_t.replace("++s->iso_meta_reads;", "++s->iso_meta_reads /* changed */;"))
        with self.assertRaisesRegex(RuntimeError, "expected 1 exact source anchor"):
            PATCH.patch_literange(self.before_l.replace(
                "p->owner->received_sample_bytes+=(uint64_t)bytes;",
                "p->owner->received_sample_bytes += (uint64_t)bytes;"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
