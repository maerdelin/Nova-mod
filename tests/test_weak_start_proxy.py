"""Regression checks for Test branch weak-network start on Player URI entrypoint."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from direct_transport_apply import WEAK_START, PROXY_HEAD, PROXY_RESOLVE, patch_player_uri_gate

class WeakStartProxyTests(unittest.TestCase):
    def test_webdav_worker_dispatches_to_ui_after_resolving(self):
        self.assertIn('.method public static maybeStart(Lcom/archos/mediacenter/video/player/Player;Landroid/net/Uri;)Z', WEAK_START)
        self.assertIn('Ljava/lang/Thread;->start()V', WEAK_START)
        self.assertIn('Landroid/os/Handler;->post(Ljava/lang/Runnable;)Z', WEAK_START)
        self.assertIn('WeakStartProxy;->current(I)Z', WEAK_START)
        self.assertIn('Lcom/archos/mediacenter/video/player/Player;->setVideoURI', WEAK_START)
        self.assertIn('Lcom/archos/mediacenter/video/player/WeakStartProxy;->cancel()V', PROXY_HEAD)
        self.assertIn('.method public static resolve(Landroid/net/Uri;)Landroid/net/Uri;', PROXY_RESOLVE)
        self.assertNotIn('.method public static declared-synchronized resolve(', PROXY_RESOLVE)
        self.assertIn('const-string v1, "novatransport"', PROXY_RESOLVE)
        self.assertIn('const-string v3, "&nova_iso=1&"', PROXY_HEAD)

    def test_player_entry_gate_locals_and_original_method_preserved(self):
        method = """.class public Lcom/archos/mediacenter/video/player/Player;
.super Ljava/lang/Object;
.method public setVideoURI(Landroid/net/Uri;Ljava/util/Map;)V
    .locals 2
    invoke-static {p1}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->armForUri(Landroid/net/Uri;)V
    return-void
.end method
.method public onPrepared()V
    .locals 0
    return-void
.end method
"""
        changed = patch_player_uri_gate(method)
        self.assertIn('    .locals 3', changed)
        self.assertIn('invoke-static/range {p0 .. p1}, Lcom/archos/mediacenter/video/player/WeakStartProxy;->maybeStart', changed)
        self.assertIn('    move-result v2\n    if-eqz v2, :nova_weak_start_sync\n    return-void', changed)
        self.assertLess(changed.index('->maybeStart'),changed.index('->armForUri'))
        self.assertIn('.method public onPrepared()V\n    .locals 0\n    return-void', changed)
        self.assertEqual(changed.count('NOVA_WEAK_START'), 1)
        with self.assertRaisesRegex(RuntimeError, 'ambiguous'):
            patch_player_uri_gate(method.replace('setVideoURI', 'noSuchMethod'))
        with self.assertRaisesRegex(RuntimeError, 'ambiguous'):
            patch_player_uri_gate(method + method)

    def test_register_count_includes_instance_uri_and_map(self):
        method = """.method public setVideoURI(Landroid/net/Uri;Ljava/util/Map;)V
    .registers 7
    return-void
.end method
"""
        changed = patch_player_uri_gate(method)
        self.assertIn('    .registers 8', changed)
        self.assertIn('    move-result v4', changed)

if __name__ == '__main__':
    unittest.main()
