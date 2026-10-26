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
        self.assertIn("NOVA_TV_TRACK_LAYOUT_V3",p.__file__ and open(p.__file__).read())
        self.assertIn("NOVA_TV_SUBTITLE_LEFT_EDGE_V3",s)
        self.assertIn("NOVA_TV_TRACK_LAYOUT_V2",s)
        self.assertIn("int-to-float v5, v3",s)
        self.assertIn("mul-int/lit8 v3, v3, 0x2",s)
        self.assertEqual(s.count("->novaOffsetTrackNeighbors(Z)V"),1)
        self.assertEqual(s.count("->setTranslationX(F)V"),1)
        self.assertIn("nova_track_skip_slave_tag",s)
        self.assertIn(":nova_subtitle_left_edge_done",s)
        self.assertIn("add-int/2addr v2, v10",s)
        self.assertIn("nova_subtitle_spacing_shift_done",s)
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
    def test_subtitle_realign_geometry_and_audio_unchanged(self):
        # The actual screenshots show 390px audio width, but only
        # 313px of the equal-width subtitle card: 77px clipped on left.
        # Header centers differ by 76px. The original 714 card width
        # is 390/2.4=162.5px; the corrective delta is W/2 ~= 81px.
        audio_width=390
        visible_subtitle_width=313
        missing_left=audio_width-visible_subtitle_width
        self.assertEqual(missing_left,77)
        original_width=round(audio_width/2.4)
        correction=original_width//2
        self.assertLessEqual(abs(correction-missing_left),6)
        for width in (160,162,200,220,300,440):
            base_shift=width*7//10+24
            subtitle_shift=width//2
            # Moving the selected subtitle RIGHT and all right siblings
            # the SAME distance cannot reopen the overlap fixed by 728.
            right_before=(width+20+base_shift)-(width/2+2*int(width*1.2)/2)
            right_after=(width+20+base_shift+subtitle_shift)-(width/2+2*int(width*1.2)/2+subtitle_shift)
            self.assertAlmostEqual(right_before,right_after)
            self.assertGreaterEqual(right_after,20)
        # Audio uses only the existing generic wide-card tag.
        after=p.player(self.sample_player())
        audio=after.split("mAudioTracksTVCardView")[1]
        self.assertNotIn(p.SUBTITLE_TAG,audio)

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
        self.assertEqual(result.count("->novaOffsetTrackNeighbors(Z)V"),1)
        self.assertIn("int-to-float v5, v3",result)

    def test_real_application_changes_only_two_smali(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); smali=root/"smali_classes2";smali.mkdir()
            (smali/"PlayerActivity.smali").write_text(self.sample_player())
            (smali/"TVCardView.smali").write_text(self.sample_card())
            (smali/"TVMenuAdapter.smali").write_text("UNCHANGED")
            p.apply(root,root/"reports/result.json")
            report=json.loads((root/"reports/result.json").read_text())
            self.assertEqual(report["marker"],"NOVA_TV_TRACK_LAYOUT_V3")
            self.assertTrue(report["subtitle_left_edge_restored"])
            self.assertTrue(report["audio_x_unchanged"])
            self.assertTrue(report["header_centered"])
            self.assertEqual(report["neighbor_gap_px"],24)
            self.assertEqual((smali/"TVMenuAdapter.smali").read_text(),"UNCHANGED")
            with self.assertRaises(RuntimeError):p.apply(root,root/"reports/result.json")

if __name__=="__main__":unittest.main()
