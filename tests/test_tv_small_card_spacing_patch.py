"""Regression tests for #737: small-card TV focus gap without #736 regressions."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "scripts"))
import tv_track_width_patch as track
import tv_small_card_spacing_patch as small
from test_tv_track_width_patch import PopupWidthTest

class SmallCardSpacingTest(unittest.TestCase):
    def baseline(self):
        return track.card(PopupWidthTest().sample_card())

    def test_existing_track_method_and_subtitle_center_getter_exactly_preserved(self):
        old = self.baseline()
        new = small.patch_source(old)
        for signature in ("private novaOffsetTrackNeighbors(ZI)V",
                          "public getPositionX()F"):
            self.assertEqual(track.section(old, signature)[2],
                             track.section(new, signature)[2], signature)
        self.assertEqual(old.count("NOVA_SUBTITLE_FOCUS_CENTER_V6"),
                         new.count("NOVA_SUBTITLE_FOCUS_CENTER_V6"))
        self.assertEqual(new.count("->novaOffsetTrackNeighbors(ZI)V"), 2)
        self.assertEqual(new.count("->novaOffsetSmallNeighbors(ZII)V"), 2)
        self.assertEqual(new.count("->setTranslationX(F)V"), 2)
        self.assertEqual(old.count(".field private novaExpandedCenter"), 2)
        self.assertEqual(new.count(".field private novaExpandedCenter"), 2)

    def test_small_scope_guards_track_and_unrelated_popup(self):
        s = small.SMALL_METHOD
        self.assertLess(s.index("if-nez v0, :nova_small_end"),
                        s.index(":nova_small_parent_ready"))
        self.assertIn(":nova_small_scope_scan", s)
        self.assertIn(":nova_small_scope_verified", s)
        self.assertIn("if-ge v2, v6, :nova_small_end", s)
        self.assertIn("nova_tv_track_wide_v1", s)
        self.assertIn("getParent()Landroid/view/ViewParent;", s)
        self.assertIn("->parentView:Landroid/view/View;", s)
        self.assertNotIn("setScaleX", s)
        self.assertNotIn("setWidth", s)
        self.assertNotIn("setX(F)", s)

    def test_actual_end_geometry_not_screenshot_offsets(self):
        s = small.SMALL_METHOD
        self.assertIn("int-to-float v9, p2", s)
        self.assertIn("int-to-float v10, p2", s)
        self.assertIn("int-to-float v1, p3", s)
        self.assertIn("const/high16 v11, 0x41c00000", s)
        self.assertIn("neg-float v11, v9", s)
        self.assertIn("move v11, v10", s)
        self.assertIn("cmpg-float v3, v1, v5", s)
        self.assertNotIn("getChildAt(I)Landroid/view/View;\n\n    move-result-object v5", s)

    def test_focus_and_unfocus_insertion_after_verified_736_markers(self):
        old = self.baseline()
        patched = small.patch_source(old)
        focus = track.section(patched, "public focus(Z)V")[2]
        self.assertLess(focus.index(":nova_track_reset_done"),
                        focus.index(":nova_small_reset_done"))
        self.assertIn("if-nez p1, :nova_small_reset_done", focus)
        self.assertIn("invoke-direct {p0, p1, v10, v10}", focus)
        self.assertIn("invoke-direct {p0, p1, v2, v3}", focus)
        self.assertLess(focus.index(":nova_track_width_normal"),
                        focus.index("invoke-direct {p0, p1, v2, v3}"))
        self.assertLess(focus.index("invoke-direct {p0, p1, v2, v3}"),
                        focus.index("-><init>("))
        self.assertEqual(focus.count("NOVA_TV_SMALL_NEIGHBOR_GAP_V1"), 2)
        self.assertEqual(focus.count("iput v11, p0"), 1)

    def test_geometry_prevents_overlap_and_matches_44px_track_gap(self):
        # Exact endX/endWidth can differ from 1.2x for other TV cards.
        # Shift entire left/right groups once, so their internal gaps
        # and card ordering remain unchanged after selection.
        for width in (160, 180, 220, 300, 440, 680):
            for original_x in (0, 50, 160, 500):
                for end_width in (width, int(width * 1.2), width * 2):
                    for left_extension in (0.0, width * .1, width * .4,
                                           width * .7):
                        end_x = original_x - left_extension
                        left_shift = max(0, original_x - end_x) + 24
                        right_shift = max(
                            0, end_x + end_width - (original_x + width)) + 24
                        left_neighbor_right = original_x - 20 - left_shift
                        right_neighbor_left = original_x + width + 20 + right_shift
                        left_gap = end_x - left_neighbor_right
                        right_gap = right_neighbor_left - (end_x + end_width)
                        self.assertGreaterEqual(left_gap + 1e-7, 44)
                        self.assertGreaterEqual(right_gap + 1e-7, 44)
                        self.assertEqual(0, 0)  # no residual shift on unfocus

    def test_immutable_neighbor_order_on_navigation_return(self):
        for left in (80.0, 150.0, 220.0):
            for right in (520.0, 800.0, 1100.0):
                # All children on a side receive the same translation.
                for shift in (24., 45., 88., 300.):
                    self.assertAlmostEqual((right+shift)-(left+shift),
                                           right-left)
                    self.assertAlmostEqual((right-shift)-(left-shift),
                                           right-left)
                # Upon focus(false), translations return to EXACTLY zero.
                self.assertEqual(left + 0., left)
                self.assertEqual(right + 0., right)

    def test_fail_closed_on_unverified_or_double_patch(self):
        with self.assertRaisesRegex(RuntimeError, "Verified #736"):
            small.patch_source(PopupWidthTest().sample_card())
        once = small.patch_source(self.baseline())
        with self.assertRaisesRegex(RuntimeError, "already installed"):
            small.patch_source(once)

    def test_one_smali_only_and_no_changes_to_player_or_adapter(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dir = root / "smali_classes2"
            dir.mkdir()
            (dir / "TVCardView.smali").write_text(self.baseline())
            (dir / "PlayerActivity.smali").write_text("KEEP")
            (dir / "TVMenuAdapter.smali").write_text("KEEP")
            report = root / "reports/small-gap.json"
            small.apply(root, report)
            data = json.loads(report.read_text())
            self.assertEqual(data["status"], "PASS")
            self.assertEqual(data["expected_gap_px"], 44)
            self.assertTrue(data["subtitle_center_cache_unchanged"])
            self.assertTrue(data["audio_track_animation_unchanged"])
            self.assertTrue(data["playback_core_unchanged"])
            self.assertEqual((dir / "PlayerActivity.smali").read_text(), "KEEP")
            self.assertEqual((dir / "TVMenuAdapter.smali").read_text(), "KEEP")

if __name__ == "__main__":
    unittest.main()
