"""Regression checks for startup-only zero-to-zero seek suppression."""
import re
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import direct_transport_apply as d

class StartupZeroSeekTests(unittest.TestCase):
    def test_iso_guard_untouched(self):
        s=d.PROXY_HEAD
        old=re.search(r"(?ms)^\.method public static shouldSkipInitialZeroSeek\(I\)Z\n.*?^\.end method$",s)
        self.assertIsNotNone(old)
        self.assertIn("->sIso:Z",old.group())
        self.assertIn("->sSkipInitialZeroSeek:Z",old.group())
        self.assertIn("if-nez p0, :no",old.group())
    def test_noniso_classifier(self):
        s=d.PROXY_HEAD
        new=re.search(r"(?ms)^\.method public static isNonIsoDirectWebdav\(\)Z\n.*?^\.end method$",s)
        self.assertIsNotNone(new)
        self.assertIn("->sForceAvos:Z",new.group())
        self.assertIn("->sIso:Z",new.group())
        self.assertNotIn("sput-",new.group())
    def test_scoped_guard_and_delegation(self):
        w=d.FACTORY
        self.assertIn("NOVA_NONISO_DUP_ZERO_SKIP_V1:",w)
        for key in ["if-nez p1, :delegate","isNonIsoDirectWebdav()Z","isInPlaybackState()Z","isBusy()Z","getDuration()I","getCurrentPosition()I"]:
            self.assertIn(key,w)
        self.assertEqual(w.count("invoke-virtual {p0, p1}, Lcom/archos/mediacenter/video/player/Player;->seekTo(I)V"),1)
        self.assertLess(w.index("NOVA_NONISO_DUP_ZERO_SKIP_V1:"),w.index(":delegate"))
    def test_only_player_service_startup_is_wrapped(self):
        sample=(".class public Lcom/archos/mediacenter/video/player/PlayerService;\n.super Ljava/lang/Object;\n"
                ".method private postPreparedAndVideoDb()V\n    .locals 2\n"
                "    invoke-virtual {v0, v1}, Lcom/archos/mediacenter/video/player/Player;->seekTo(I)V\n"
                "    return-void\n.end method\n"
                ".method public manualSeek(I)V\n    .locals 1\n"
                "    invoke-virtual {v0, p1}, Lcom/archos/mediacenter/video/player/Player;->seekTo(I)V\n"
                "    return-void\n.end method\n")
        patched=d.patch_service(sample)
        self.assertEqual(patched.count("DirectPlayerFactory;->seekTo"),1)
        self.assertIn("invoke-virtual {v0, p1}, Lcom/archos/mediacenter/video/player/Player;->seekTo(I)V",patched)
    def test_nonzero_seek_always_delegated(self):
        w=d.FACTORY
        self.assertLess(w.index("if-nez p1, :delegate"),w.index("isNonIsoDirectWebdav()Z"))
        self.assertIn("    :delegate\n    invoke-virtual {p0, p1}",w)
if __name__=="__main__": unittest.main()
