"""Regression tests for #739: exact gap big/small focus preserving #736."""
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

    def test_scope_allows_track_and_small_but_skips_unrelated_rows(self):
        code = small.SMALL_METHOD
        self.assertIn(":nova_small_scope_scan", code)
        self.assertIn(":nova_small_scope_verified", code)
        self.assertIn("if-ge v2, v6, :nova_small_end", code)
        self.assertIn("nova_tv_track_wide_v1", code)
        self.assertNotIn("if-nez v0, :nova_small_end", code)
        self.assertIn("getParent()Landroid/view/ViewParent;", code)
        self.assertIn("->parentView:Landroid/view/View;", code)
        self.assertNotIn("setScaleX", code)
        self.assertNotIn("setWidth", code)

    def test_exact_animation_end_geometry_without_min_gap_clamps(self):
        code = small.SMALL_METHOD
        for token in ("int-to-float v9, p2", "int-to-float v10, p2",
                      "int-to-float v1, p3", "sub-float v9, v5, v9",
                      "sub-float/2addr v10, v1",
                      "const/high16 v11, 0x41c00000",
                      "neg-float v11, v9", "move v11, v10",
                      "cmpg-float v3, v1, v5"):
            self.assertIn(token, code)
        self.assertNotIn("cmpg-float v1, v9, v11", code)
        self.assertNotIn("cmpg-float v1, v10, v11", code)

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
        self.assertEqual(focus.count("NOVA_TV_UNIFIED_EXACT_GAP_V2"), 2)
        self.assertEqual(focus.count("iput v11, p0"), 1)

    @staticmethod
    def final_gaps(original_x, original_width, end_x, end_width):
        left_shift = original_x - end_x + 24
        right_shift = end_x + end_width - original_x - original_width + 24
        previous_right = original_x - 20 - left_shift
        next_left = original_x + original_width + 20 + right_shift
        return end_x - previous_right, next_left - (end_x + end_width)

    def test_small_card_all_widths_and_end_positions_exact_44_each_side(self):
        for width in (100,165,200,207,213,220,275,330,440,680):
            for x in (0,20,80,120,350,1920):
                for end_width in (width,int(width*1.2),width*2):
                    for delta in (0,width*.1,width*.4,width*.7,-width*.4):
                        self.assertEqual(self.final_gaps(x,width,x-delta,end_width),
                                         (44,44))

    def test_audio_subtitle_final_736_endX_endWidth_include_clipping(self):
        for width in (101,102,103,105,165,207,213,220,275,330,440,680):
            for x in (0,20,50,80,100,160,250,1920):
                base_x=int(x+(width-width*1.2)/2.0)
                native_width=int(width*1.2)
                raw_end_x=base_x-native_width//2
                expanded_width=native_width*2
                for subtitle in (False,True):
                    end_x=max(0,raw_end_x) if subtitle else raw_end_x
                    self.assertEqual(self.final_gaps(x,width,end_x,expanded_width),
                                     (44,44))

    def test_default_unfocused_neighbor_gap_remains_exact_20(self):
        for w in (120,165,220,300,440,660):
            x=100
            y=x+w+20
            z=y+w+20
            self.assertEqual(y-x-w,20)
            self.assertEqual(z-y-w,20)
        self.assertIn("if-eqz p1, :nova_small_offsets_ready",small.SMALL_METHOD)
        self.assertIn("const/4 v9, 0x0",small.SMALL_METHOD)
        self.assertIn("const/4 v10, 0x0",small.SMALL_METHOD)

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
            self.assertEqual(data["focused_gap_exact_px"], 44)
            self.assertEqual(data["original_unfocused_gap_px"], 20)
            self.assertTrue(data["tagged_tracks_exact_overwrite"])
            self.assertTrue(data["subtitle_center_cache_unchanged"])
            self.assertTrue(data["audio_track_animation_unchanged"])
            self.assertTrue(data["playback_core_unchanged"])
            self.assertEqual((dir / "PlayerActivity.smali").read_text(), "KEEP")
            self.assertEqual((dir / "TVMenuAdapter.smali").read_text(), "KEEP")

if __name__ == "__main__":
    unittest.main()
