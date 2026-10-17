import unittest
from scripts import rebuffer_after_start as r

OLD = ("initialHold","beforeNativeStart","awaitBudget","bufferStartHeldCurrent","HARD_GATE")

class CleanMainRebufferTests(unittest.TestCase):
    def test_no_old_hard_gate_terms(self):
        blob = r.REBUFFER_SMALI + r.PLAYER_METHODS + r.SESSION_METHOD
        for term in OLD:
            self.assertNotIn(term, blob)

    def test_exact_watermarks(self):
        self.assertIn("CAPACITY:I = 0x4000000", r.REBUFFER_SMALI)
        self.assertIn("LOW:I = 0x1800000", r.REBUFFER_SMALI)
        self.assertIn("RESUME:I = 0x2d00000", r.REBUFFER_SMALI)
        self.assertIn("PAUSE buffer<24MiB", r.REBUFFER_SMALI)
        self.assertIn("RESUME buffer>45MiB_or_eof", r.REBUFFER_SMALI)

    def test_protection_is_post_start_only(self):
        fixture = """.class public Lcom/archos/mediacenter/video/player/Player;
.field public static sPlayer:Lcom/archos/mediacenter/video/player/Player;
.method public start(I)V
    .locals 4
    invoke-interface {v3}, Lcom/archos/medialib/IMediaPlayer;->start()V

    iput v0, p0, Lcom/archos/mediacenter/video/player/Player;->mCurrentState:I
    return-void
.end method
.method public pause(I)V
    .locals 1
    return-void
.end method
.method public stopPlayback()V
    .locals 1
    return-void
.end method
.method public onCompletion(Lcom/archos/medialib/IMediaPlayer;)V
    .locals 1
    return-void
.end method
"""
        out,_=r.patch_player(fixture)
        start=r._find_method(out," start(I)V").group(0)
        native=start.index("IMediaPlayer;->start()V")
        active=start.index("NovaRebufferInputStream;->onPlaybackStarted()V")
        self.assertLess(native, active)
        self.assertNotIn("onPlaybackStarted()V", start[:native])

    def test_manual_pause_and_stop_disarm(self):
        self.assertIn("onPlaybackStopped()V", r.patch_player)
        self.assertTrue(callable(r.patch_player))

    def test_only_long_playback_webdav_is_eligible(self):
        self.assertIn("supersedableMediaRequest:Z", r.SESSION_METHOD)
        self.assertIn("ReadMode;->PLAYBACK", r.SESSION_METHOD)
        self.assertIn('"webdav"', r.SESSION_METHOD)
        self.assertIn('"webdavs"', r.SESSION_METHOD)
        self.assertIn("0x800000", r.SESSION_METHOD)

    def test_art_verification_entry_loads_both_classes(self):
        self.assertIn("NovaRebufferInputStream;", r.REBUFFER_SMALI)
        self.assertIn("const-class v0, Lcom/archos/mediacenter/video/player/Player;", r.REBUFFER_SMALI)

if __name__ == "__main__":
    unittest.main()
