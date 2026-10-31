#!/usr/bin/env python3
"""Fail closed if #967 W1-only A/B accidentally changes anything but W2 gating."""
import pathlib
import re
import unittest


class W1Control(unittest.TestCase):
    def test_second_range_blocked_at_both_activation_sites(self):
        src = pathlib.Path("iso/nova_literange4.inc").read_text()
        self.assertIn("static volatile int nova_60fps_w1_control = 1;", src)
        self.assertIn("if(nova_60fps_w1_control)lanes=1;", src)
        self.assertRegex(src, r"if\(target>0 && s->multi_active_lanes<2 && !s->multi_seek_guard &&\s*!nova_60fps_w1_control &&")
        self.assertEqual(src.count("NOVA_LITERANGE4_PAIR_ENABLE x="), 1)
        self.assertIn("NOVA_60FPS_W1_AB: second HTTP Range disabled", src)

    def test_full_dual_code_and_shared42_remain_for_ab(self):
        src = pathlib.Path("iso/nova_literange4.inc").read_text()
        native = pathlib.Path("scripts/shared42_native_patch.py").read_text()
        transport = pathlib.Path("iso/nova_transport.c").read_text()
        self.assertIn("#define NOVA_LITE_SLOTS 2", src)
        self.assertIn("curl_multi_perform(e->multi,&running)", src)
        self.assertIn("NOVA_SHARED42_AVOS", native)
        self.assertIn("#define NOVA_WH_STAGE_BYTES (42u * 1024u * 1024u)", transport)
        self.assertIn("#define NOVA_WH_RAW_BYTES (86u * 1024u * 1024u)", transport)

    def test_no_unintended_clock_or_render_patches(self):
        src = pathlib.Path("iso/nova_literange4.inc").read_text()
        self.assertNotIn("render_offset_ns", src)
        self.assertNotIn("speed_cadence", src)
        self.assertNotIn("pcmSlew", src)


if __name__ == "__main__":
    unittest.main()
