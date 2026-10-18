import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from audio_route_no_rebuild_patch import apply, _allow_prepared_to_continue, _replace_player_method


class AudioRouteNoRebuildTests(unittest.TestCase):
    def sample(self):
        return """.class public Lcom/archos/mediacenter/video/player/Player;
.super Ljava/lang/Object;
.method public onAudioOutputChanged()V
    .locals 2
    invoke-direct {p0}, Lcom/archos/mediacenter/video/player/Player;->suspendForSurface()V
    invoke-virtual {p0}, Lcom/archos/mediacenter/video/player/Player;->openVideo()V
    return-void
.end method

.method public onPrepared(Lcom/archos/mediacenter/IMediaPlayer;)V
    .locals 2
    invoke-virtual {p0}, Lcom/archos/mediacenter/video/player/Player;->onAudioOutputChanged()V
    return-void
    :goto_continue
    invoke-virtual {p0}, Lcom/archos/mediacenter/video/player/Player;->resume()V
    return-void
.end method

.method public setAudioTrack(I)Z
    .locals 1
    const/4 v0, 0x1
    return v0
.end method
"""

    def test_removes_reopen_but_preserves_track_switch(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "smali/com/archos/mediacenter/video/player/Player.smali"
            path.parent.mkdir(parents=True)
            path.write_text(self.sample())
            result = apply(Path(work))
            changed = path.read_text()
            self.assertEqual(result["status"], "PASS")
            self.assertIn(".method public setAudioTrack(I)Z", changed)
            self.assertEqual(changed.count("onAudioOutputChanged()V"), 2)
            self.assertIn("    nop\n    :goto_continue", changed)
            self.assertNotIn("->suspendForSurface()V", changed)
            self.assertIn("    .locals 0\n    return-void\n.end method", changed)

    def test_missing_return_does_not_silently_pass(self):
        with self.assertRaises(RuntimeError):
            _allow_prepared_to_continue(self.sample().replace(
                "->onAudioOutputChanged()V\n    return-void",
                "->onAudioOutputChanged()V\n    nop"
            ))

    def test_missing_reopen_does_not_silently_pass(self):
        with self.assertRaises(RuntimeError):
            _replace_player_method(self.sample().replace("->openVideo()V", "->refresh()V"))


if __name__ == "__main__":
    unittest.main()
