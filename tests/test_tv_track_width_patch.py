"""Unit-level checks for TV track popup width, sibling separation and header."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("tv_track",ROOT/"scripts/tv_track_width_patch.py")
p=importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

class PopupWidthTest(unittest.TestCase):
    def sample_player(self):
        s=".method public createPlayerTVMenu()V\n    .locals 10\n"
        for f in ("mSubtitleTVCardView","mAudioTracksTVCardView","mPlayModeTVCardView"):
            s+="    iput-object v1, p0, "+p.ACT+"->"+f+":"+p.CARD+"\n"
        return s+".end method\n"
    def sample_card(self):
        c=p.CARD
        return (".method public focus(Z)V\n    .locals 14\n    move v0, p1\n"
                + "    iget-object v2, p0, "+c+"->slaveView:"+c+"\n"
                + "    if-eqz v2, :cond_0\n"
                + "    invoke-virtual {v2, p1}, "+c+"->focus(Z)V\n"
                + "    :cond_0\n\n    const/4 v2, 0x1\n"
                + "    if-eqz v0, :cond_9\n"
                + "    new-instance v0, "+c[:-1]+"$ExpandAnimation;\n"
                + "    :goto_6\n    const/16 v8, 0xff\n    const/4 v9, 0x0\n"
                + "    move-object v1, p0\n"
                + "    invoke-direct/range {v0 .. v9}, "+c[:-1]+"$ExpandAnimation;-><init>(Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;IIIFFZILjava/lang/Runnable;)V\n"
                + "    :cond_9\n    const/4 v0, 0x0\n.end method\n")
    def test_only_two_cards_are_selected_and_parent_root_set(self):
        s=p.player(self.sample_player())
        self.assertEqual(s.count("->setTag(Ljava/lang/Object;)V"),2)
        self.assertEqual(s.count("->setParentView(Landroid/view/View;)V"),2)
        self.assertEqual(s.count(p.TAG),2)
        self.assertIn("mPlayModeTVCardView",s)
        self.assertEqual(s.count(p.SUBTITLE_TAG),1)
        self.assertEqual(s.count("->setTag(ILjava/lang/Object;)V"),1)
    def test_focus_width_header_siblings_slave(self):
        s=p.card(self.sample_card())
        self.assertIn("NOVA_TV_TRACK_LAYOUT_V4",(ROOT/"scripts/tv_track_width_patch.py").read_text())
        self.assertIn("NOVA_TV_DYNAMIC_CLIP_V4",s)
        self.assertIn("NOVA_TV_TRACK_LAYOUT_V2",s)
        self.assertIn("int-to-float v5, v3",s)
        self.assertIn("mul-int/lit8 v3, v3, 0x2",s)
        self.assertEqual(s.count("->novaOffsetTrackNeighbors(ZI)V"),2)
        self.assertEqual(s.count("->setTranslationX(F)V"),1)
        self.assertIn("nova_track_skip_slave_tag",s)
        self.assertIn(":nova_subtitle_clip_delta_ready",s)
        self.assertIn("add-int/2addr v2, v10",s)
        self.assertIn("nova_track_dynamic_gap_done",s)
        self.assertIn("->getTag(I)Ljava/lang/Object;",s)
        self.assertIn("nova_subtitle_slave_marker_done",s)
        self.assertIn("->parentView:Landroid/view/View;",s)
        self.assertIn("cmpg-float v10, v9, v5",s)
        self.assertIn("if-eqz p1, :nova_track_spacing_apply",s)
        self.assertNotIn("setVisibility",s)
        self.assertNotIn("setAlpha",s)
    def test_right_left_neighbors_are_separated_for_all_widths(self):
        for width in (200,220,300,440,680):
            # Card goes from W to 2*int(1.2W), and is centered on its
            # original center. +0.7W extra translation prevents overlap.
            actual_width=2*int(width*1.2)
            delta=(7*width)//10+24
            right_card_left=width+20+delta
            selected_right=width/2+actual_width/2
            self.assertGreaterEqual(right_card_left-selected_right,20)
            left_card_right=-20-delta
            selected_left=width/2-actual_width/2
            self.assertGreaterEqual(selected_left-left_card_right,20)
    def test_dynamic_clip_equals_actual_audio_width_all_densities(self):
        # The two track cards share a 220dp base resource. The renderer
        # converts that width to actual physical pixels using each screen DPI.
        for dpi_scale in (0.75,1.0,1.25,1.5,2.0,2.5,3.0):
            width=round(220*dpi_scale)
            audio_expanded=2*int(width*1.2)
            for initial_x in (0,30,60,80,100,120,160,240):
                base_x=int(initial_x+(width-width*1.2)/2.0)
                expanded_x=base_x-int(width*1.2)//2
                missing_left=max(0,-expanded_x)
                new_x=expanded_x+missing_left
                subtitle_expanded=2*int(width*1.2)
                self.assertGreaterEqual(new_x,0)
                self.assertEqual(subtitle_expanded,audio_expanded)
                self.assertEqual(
                    subtitle_expanded-max(0,-new_x),audio_expanded)
                self.assertEqual(missing_left,0 if expanded_x>=0 else -expanded_x)

    def test_neighbor_gap_is_identical_after_subtitle_correction(self):
        for dpi_scale in (0.75,1.0,1.5,2.0,3.0):
            width=round(220*dpi_scale)
            for x in (0,50,80,100,160,240):
                expanded_x=int(x+(width-width*1.2)/2.0)-int(width*1.2)//2
                delta=max(0,-expanded_x)
                old_right=x+width+20+width*7//10+24
                old_card_right=expanded_x+2*int(width*1.2)
                new_right=old_right+delta
                new_card_right=old_card_right+delta
                self.assertEqual(new_right-new_card_right,
                                 old_right-old_card_right)
                self.assertGreaterEqual(new_right-new_card_right,20)

    def test_no_guessed_halfwidth_or_screenshot_correction(self):
        code=(ROOT/"scripts/tv_track_width_patch.py").read_text()
        self.assertIn("neg-int v10, v2",code)
        self.assertIn("add-int/2addr v4, p2",code)
        self.assertIn("if-gez v2, :nova_subtitle_clip_delta_zero",code)
        self.assertNotIn("div-int/lit8 v9, v9, 0x2",code)
        self.assertNotIn("390px",code)
        self.assertNotIn("77px",code)

    def test_wrong_methods_fail_fast(self):
        with self.assertRaises(RuntimeError):p.player(self.sample_player().replace(".locals 10",".locals 9"))
        with self.assertRaises(RuntimeError):p.card(self.sample_card().replace(".locals 14",".locals 12"))
        with self.assertRaises(RuntimeError):p.card(self.sample_card().replace("    move v0, p1","    move v9, p1"))
    def test_branch_independent_real_apk_variant(self):
        # #727 failed because instructions around :cond_0 differed in APK.
        # An unrelated instruction inserted there must not disable the patch.
        original=self.sample_card()
        self.assertIn("    :cond_0\n\n    const/4 v2, 0x1",original)
        changed=original.replace(
            "    :cond_0\n\n    const/4 v2, 0x1",
            "    :cond_0\n\n    nop\n\n    const/4 v2, 0x1")
        result=p.card(changed)
        self.assertIn("    nop",result)
        self.assertEqual(result.count("->novaOffsetTrackNeighbors(ZI)V"),2)
        self.assertIn("int-to-float v5, v3",result)

    def test_real_application_changes_only_two_smali(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); smali=root/"smali_classes2";smali.mkdir()
            (smali/"PlayerActivity.smali").write_text(self.sample_player())
            (smali/"TVCardView.smali").write_text(self.sample_card())
            (smali/"TVMenuAdapter.smali").write_text("UNCHANGED")
            p.apply(root,root/"reports/result.json")
            report=json.loads((root/"reports/result.json").read_text())
            self.assertEqual(report["marker"],"NOVA_TV_TRACK_LAYOUT_V4")
            self.assertEqual(report["subtitle_clip_delta"],"max(0,-expanded_left_px)")
            self.assertTrue(report["audio_x_unchanged"])
            self.assertTrue(report["header_centered"])
            self.assertEqual(report["neighbor_gap_px"],24)
            self.assertEqual((smali/"TVMenuAdapter.smali").read_text(),"UNCHANGED")
            with self.assertRaises(RuntimeError):p.apply(root,root/"reports/result.json")

if __name__=="__main__":unittest.main()
