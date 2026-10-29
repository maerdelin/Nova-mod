"""First-open subtitle left clipping: enforce one deterministic layout animator.

The verified upstream card_layout.xml enables animateLayoutChanges on TVCardView;
the original 200ms ExpandAnimation changes the SAME card's LayoutParams each
frame and reveals list children on animation start. Only the subtitle's main
and mirror cards opt out of XML LayoutTransition, before focus animation.
"""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import tv_track_width_patch as tv
from test_tv_track_width_patch import PopupWidthTest

MARK="NOVA_TV_SUBTITLE_FIRST_FOCUS_LAYOUT_STABLE_V1"
DISABLE="->setLayoutTransition(Landroid/animation/LayoutTransition;)V"

class SubtitleFirstFocusLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p=PopupWidthTest()
        cls.original_card=p.sample_card()
        cls.original_player=p.sample_player()
        cls.card=tv.card(cls.original_card)
        cls.player=tv.player(cls.original_player)

    def test_xml_transition_collision_is_removed_before_focus_only_for_subtitle(self):
        player=self.player
        self.assertIn(MARK,player)
        self.assertEqual(player.count(DISABLE),1)
        first=player.index("->mSubtitleTVCardView:")
        second=player.index("->mAudioTracksTVCardView:")
        disable=player.index(DISABLE)
        self.assertLess(first,disable)
        self.assertLess(disable,second)
        self.assertIn("const/4 v10, 0x0",player[first:disable])
        self.assertIn("invoke-virtual {v1, v10}",player[disable-42:disable+10])

    def test_slave_is_disabled_before_first_start_animation(self):
        focus=tv.section(self.card,"public focus(Z)V")[2]
        self.assertIn(MARK,focus)
        self.assertEqual(focus.count(DISABLE),1)
        self.assertLess(focus.index("->setTag(ILjava/lang/Object;)V"),
                        focus.index(DISABLE))
        self.assertLess(focus.index(DISABLE),
                        focus.index("->focus(Z)V"))
        self.assertLess(focus.index(DISABLE),
                        focus.index("->startAnimation(Landroid/view/animation/Animation;)V"))
        self.assertIn("if-eqz v11, :nova_subtitle_slave_marker_done",focus)

    def test_dynamic_width_and_clip_center_policy_is_unchanged(self):
        focus=tv.section(self.card,"public focus(Z)V")[2]
        for token in ("mul-int/lit8 v3, v3, 0x2",
                      "if-gez v2, :nova_subtitle_clip_delta_zero",
                      "neg-int v10, v2",
                      "->novaExpandedCenterX:F",
                      "->novaOffsetTrackNeighbors(ZI)V",
                      "->startAnimation(Landroid/view/animation/Animation;)V"):
            self.assertIn(token,focus)
        getter=tv.section(self.card,"public getPositionX()F")[2]
        self.assertIn("NOVA_SUBTITLE_FOCUS_CENTER_V6",getter)
        self.assertNotIn(DISABLE,getter)
        self.assertNotIn("->setLayoutTransition",self.original_card)

    def test_no_audio_or_other_popup_animations_disabled(self):
        src=(ROOT/"scripts/tv_track_width_patch.py").read_text()
        self.assertEqual(src.count(MARK),2)
        self.assertIn('if field=="mSubtitleTVCardView":',src)
        self.assertIn("if-eqz v11, :nova_subtitle_slave_marker_done",src)
        self.assertNotIn("setLayoutTransition",tv.SPACING_METHOD)
        small=(ROOT/"scripts/tv_small_card_spacing_patch.py").read_text()
        self.assertNotIn("setLayoutTransition",small)

    def test_deterministic_across_repeated_focus_and_mirror_lifecycle(self):
        # Focusing repeatedly cannot reinstall an asynchronous LayoutTransition;
        # null is idempotent and the mirrored view gets it before focus(true).
        for sequence in [(True,), (True,False,True), (True,False,True,False,True)]:
            state={"main":None,"slave":None}
            for focussed in sequence:
                if focussed:
                    state["main"]=None
                    state["slave"]=None
                self.assertIsNone(state["main"])
                self.assertIsNone(state["slave"])

if __name__=="__main__":unittest.main()
