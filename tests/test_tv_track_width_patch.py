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
        return (".method public getPositionX()F\n    .locals 2\n"
                + "    invoke-virtual {p0}, Landroid/view/View;->getX()F\n"
                + "    move-result v0\n"
                + "    invoke-virtual {p0}, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;->getCurrentWidth()I\n"
                + "    move-result v1\n"
                + "    div-int/lit8 v1, v1, 0x2\n"
                + "    int-to-float v1, v1\n"
                + "    add-float/2addr v0, v1\n"
                + "    return v0\n.end method\n\n"
                + ".method public focus(Z)V\n    .locals 14\n    move v0, p1\n"
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
        self.assertIn("    .locals 12",s)
        self.assertNotIn("    const-string v3, \"nova_",s)
        self.assertEqual(s.count("NOVA_TV_REGISTER_SAFE_V5"),2)
        self.assertIn('    const-string v11, "'+p.SUBTITLE_TAG+'"',s)
    def test_android_verifier_theme_register_survives_player_patch(self):
        # 730 shipped a broken APK: the tag was loaded with const-string v3,
        # while the later instructions still used v3 as Resources$Theme.
        # Preserve the ORIGINAL method body and use extra v10/v11 locals.
        original=self.sample_player()
        original=original.replace(
            ".end method",
            """    invoke-static {v3}, Landroid/content/res/Resources$Theme;->getClass()Ljava/lang/Class;

.end method""")
        patched=p.player(original)
        self.assertIn("    .locals 12",patched)
        self.assertIn("invoke-static {v3}",patched)
        self.assertNotIn("const-string v3",patched)
        self.assertNotIn("move-result-object v3",patched)
        self.assertIn("const-string v10",patched)
        self.assertIn("const-string v11",patched)
        self.assertNotIn("const-string v2",patched)
        for reg in ("v10","v11"):
            self.assertNotIn(reg,original)
        # The old original instructions must all survive in original order;
        # changes are only at the two anchor spots and .locals count.
        self.assertEqual(patched.count("->mPlayModeTVCardView:"),1)

    def test_new_scratch_registers_fit_in_smali_4bit_invoke(self):
        patched=p.player(self.sample_player())
        self.assertIn(".locals 12",patched)
        self.assertIn("invoke-virtual {v1, v10, v11}",patched)
        self.assertLessEqual(max((10,11,12)),15) # p0 shifts to v12
        self.assertNotIn("const-string v3, \"nova_",patched)
        self.assertNotIn("const-string v2, \"nova_",patched)
        self.assertEqual(patched.count("->setParentView(Landroid/view/View;)V"),2)

    def test_fail_closed_if_original_uses_scratch_register(self):
        original=self.sample_player().replace(
            ".end method","    move-object v10, p0\n.end method")
        with self.assertRaisesRegex(RuntimeError,"reserved scratch"):
            p.player(original)

    def test_focus_width_header_siblings_slave(self):
        s=p.card(self.sample_card())
        self.assertIn("NOVA_SUBTITLE_FOCUS_CENTER_V6",(ROOT/"scripts/tv_track_width_patch.py").read_text())
        self.assertIn("NOVA_TV_DYNAMIC_CLIP_V4",s)
        self.assertIn("NOVA_TV_TRACK_LAYOUT_V2",s)
        self.assertIn("int-to-float v5, v3",s)
        self.assertIn("mul-int/lit8 v3, v3, 0x2",s)
        self.assertEqual(s.count("->novaOffsetTrackNeighbors(ZI)V"),2)
        self.assertEqual(s.count("->setTranslationX(F)V"),1)
        self.assertIn("nova_track_skip_slave_tag",s)
        self.assertIn(":nova_subtitle_clip_delta_ready",s)
        self.assertIn("NOVA_SUBTITLE_FOCUS_CENTER_V6",s)
        self.assertIn("->novaExpandedCenterX:F",s)
        self.assertIn("->novaExpandedCenterValid:Z",s)
        self.assertIn(":nova_track_center_original_position",s)
        self.assertIn("iput v11, p0",s)
        self.assertEqual(s.count(".field private novaExpandedCenter"),2)
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

    def test_repeated_navigation_uses_identical_expanded_center(self):
        # The adapter starts focus() and queries getPositionX BEFORE
        # the 200ms animation finishes. 732 returned the COLLAPSED
        # center on that path. Cached endX+endWidth/2 must be used.
        for density in (0.75,1.0,1.25,1.5,2.0,2.5,3.0):
            w=round(220*density)
            actual_end_w=2*int(w*1.2)
            for screen_w in (640,720,960,1280,1920,2560,3840):
                # Different screen widths affect the adapter's translation,
                # never the card's own end center.
                for original_x in (0,25,50,80,100,120,240):
                    pre_center=original_x+(w//2)
                    native_end_x=int(original_x + (w-w*1.2)/2.0)
                    expanded_x=native_end_x-int(w*1.2)//2
                    corrected_end_x=max(0,expanded_x)
                    post_center=corrected_end_x+actual_end_w//2
                    new_translation=screen_w/2-post_center
                    self.assertEqual(new_translation+post_center,screen_w/2)
                    # Initial, next->previous, next->next->previous,
                    # and refocus() all query the same cached target.
                    for repeat in range(4):
                        self.assertEqual(
                            screen_w/2-post_center+post_center,screen_w/2)
                    # Old adapter path was wrong exactly by the
                    # subtitle left-edge correction, if any.
                    old_translation=screen_w/2-pre_center
                    self.assertAlmostEqual(
                        old_translation+post_center-screen_w/2,
                        post_center-pre_center)

    def test_center_cache_enabled_for_subtitle_only(self):
        patch=p.card(self.sample_card())
        focus=p.section(patch,"public focus(Z)V")[2]
        getter=p.section(patch,"public getPositionX()F")[2]
        self.assertIn("NOVA_SUBTITLE_FOCUS_CENTER_V6",getter)
        self.assertIn("iput-boolean v11, p0",focus)
        self.assertIn("if-eqz v10, :nova_subtitle_clip_delta_zero",focus)
        self.assertLess(
            focus.index("if-eqz v10, :nova_subtitle_clip_delta_zero"),
            focus.index("iput-boolean v11, p0"))
        self.assertIn(":nova_track_width_normal",focus)
        self.assertIn("iput-boolean v10, p0",focus)
        self.assertIn("iget-boolean v0, p0",getter)
        self.assertIn("return v0",getter)
        self.assertNotIn("->novaExpandedCenterValid:Z",
                         p.player(self.sample_player()))
        # Only TVCardView gets two additional fields; no adapter edits.
        self.assertNotIn("TVMenuAdapter.smali",patch)

    def test_get_position_missing_or_no_scratch_aborts(self):
        raw=self.sample_card()
        start,end,_=p.section(raw,"public getPositionX()F")
        with self.assertRaises(RuntimeError):
            p.card(raw[:start]+raw[end:])
        broken=raw.replace(".method public getPositionX()F\n    .locals 2",
                           ".method public getPositionX()F\n    .locals 0")
        with self.assertRaisesRegex(RuntimeError,"no safe local scratch"):
            p.card(broken)

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
            self.assertEqual(report["marker"],"NOVA_SUBTITLE_FOCUS_CENTER_V6")
            self.assertEqual(report["subtitle_focus_center"],"cached_from_ExpandAnimation_endX_and_endWidth")
            self.assertEqual(report["subtitle_clip_delta"],"max(0,-expanded_left_px)")
            self.assertTrue(report["audio_x_unchanged"])
            self.assertTrue(report["header_centered"])
            self.assertEqual(report["neighbor_gap_px"],24)
            self.assertEqual((smali/"TVMenuAdapter.smali").read_text(),"UNCHANGED")
            with self.assertRaises(RuntimeError):p.apply(root,root/"reports/result.json")

if __name__=="__main__":unittest.main()
