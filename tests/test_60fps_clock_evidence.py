#!/usr/bin/env python3
"""Ensure 60fps evidence branch logs source CPU/page pressure, changes no W2 policy."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class EvidenceOnly(unittest.TestCase):
    def test_unmodified_w2_range_policy(self):
        lite=(ROOT/"iso/nova_literange4.inc").read_text()
        self.assertIn("#define NOVA_LITE_SLOTS 2",lite)
        self.assertIn("s->multi_active_lanes=2;",lite)
        self.assertIn("NOVA_LITERANGE4_PAIR_ENABLE",lite)
        self.assertNotIn("NOVA_W2_RAW_PRESSURE_GUARD_V1",lite)
        self.assertNotIn("nova_60fps_w1_control",lite)
        self.assertIn("NOVA_WH_FUTURE_PAGES",lite)
        self.assertIn("NOVA_60FPS_W2_IO_CPU_V1",lite)
        self.assertIn("CLOCK_THREAD_CPUTIME_ID",lite)
        self.assertIn("futurePages=%d",lite)
        self.assertIn("rawPages=%d",lite)
        self.assertIn("stagedPages=%d",lite)
        self.assertIn("freePages=%d",lite)
        self.assertIn("nova_lite_staged_pages(e)",lite)

    def test_w2_observations_do_not_affect_policy(self):
        lite=(ROOT/"iso/nova_literange4.inc").read_text()
        start=lite.index("/* NOVA_60FPS_W2_IO_CPU_V1")
        end=lite.index('/* W=2 only, never the obsolete',start)
        snippet=lite[start:end]
        self.assertNotRegex(snippet,r"\b(curl_multi_|curl_easy_|nova_lite_schedule|nova_multi_start|nova_wh_page_alloc|nova_wh_page_free)\b")
        self.assertNotIn("multi_active_lanes=",snippet)
        self.assertNotIn("CURL_WRITEFUNC_PAUSE",snippet)
        self.assertIn("LOGI",snippet)

    def test_clock_sampling_remains_read_only(self):
        trace=(ROOT/"scripts/startup_freeze_trace_patch.py").read_text()
        self.assertIn("1200000",trace)
        self.assertIn("NOVA_60FPS_CLOCK_CPU_V1",trace)
        self.assertIn("threadCpuUs=%lld",trace)
        self.assertIn("p->render_offset_ns",trace)
        self.assertIn("p->venc_put_time",trace)
        self.assertIn("p->venc_ref_time",trace)
        self.assertIn('"clock_algorithm_changed": False',trace)
        self.assertIn('"video_drop_threshold_changed": False',trace)

if __name__=="__main__":
    unittest.main()
