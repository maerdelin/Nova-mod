import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("tv_track",ROOT/"scripts/tv_track_width_patch.py")
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
class PopupWidthTest(unittest.TestCase):
    def test_two_target_cards_only(self):
        base=".method public createPlayerTVMenu()V\n    .locals 10\n"
        for name in ("mSubtitleTVCardView","mAudioTracksTVCardView","mPlayModeTVCardView"):
            base+="    iput-object v1, p0, "+p.ACT+"->"+name+":"+p.CARD+"\n"
        result=p.player(base+".end method\n")
        self.assertEqual(result.count("->setTag(Ljava/lang/Object;)V"),2)
        self.assertIn("mPlayModeTVCardView",result)
    def test_focused_animation_only(self):
        signature="    invoke-direct/range {v0 .. v9}, "+p.CARD[:-1]+"$ExpandAnimation;-><init>(XXXX)V"
        old=".method public focus(Z)V\n    .locals 14\n    if-eqz v0, :cond_9\n    move-object v1, p0\n\n"+signature+"\n    :cond_9\n.end method\n"
        new=p.card(old)
        self.assertNotIn("TVCardView;$ExpandAnimation",new)
        self.assertIn("mul-int/lit8 v3, v3, 0x2",new)
        self.assertIn("sub-int/2addr v2, v10",new)
        self.assertIn(":cond_9",new)
        self.assertEqual(new.count("nova_track_width_normal"),2)
    def test_no_generic_xml_change(self):
        s=(ROOT/"scripts/granular_build.py").read_text()
        self.assertIn("tv_track_width_patch.apply(candidate,",s)
        self.assertIn("other_card_widths_unchanged",Path(p.__file__).read_text())
if __name__=="__main__":unittest.main()
