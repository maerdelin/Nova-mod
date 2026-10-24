"""Guard the asynchronous weak-network transport handoff (Test branch).

The native transport may retry indefinitely when connectivity is recoverable.
It must not be invoked synchronously from the Activity/Service main thread.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from direct_transport_apply import (WEAK_START, PROXY_HEAD, PROXY_RESOLVE,
                                    patch_service_async_start)


class WeakStartProxyTests(unittest.TestCase):
    def test_webdav_worker_posts_on_main_without_sync_resolution(self):
        self.assertIn("Ljava/lang/Thread;->start()V", WEAK_START)
        self.assertIn("Landroid/os/Handler;->post(Ljava/lang/Runnable;)Z", WEAK_START)
        self.assertIn("WeakStartProxy;->current(I)Z", WEAK_START)
        self.assertIn("Lcom/archos/mediacenter/video/player/Player;->setVideoURI", WEAK_START)
        self.assertIn("Lcom/archos/mediacenter/video/player/WeakStartProxy;->cancel()V", PROXY_HEAD)
        self.assertIn('.method public static resolve(Landroid/net/Uri;)Landroid/net/Uri;', PROXY_RESOLVE)
        self.assertNotIn('.method public static declared-synchronized resolve(', PROXY_RESOLVE)
        self.assertIn('const-string v1, "novatransport"', PROXY_RESOLVE)
        self.assertIn('const-string v3, "&nova_iso=1&"', PROXY_HEAD)

    def test_only_initial_service_video_open_is_redirected(self):
        original = """.class public Lcom/archos/mediacenter/video/player/PlayerService;
.super Landroid/app/Service;
.method private onStreamingUriOK()V
    .locals 3
    iget-object v0, p0, Lcom/archos/mediacenter/video/player/PlayerService;->mPlayer:Lcom/archos/mediacenter/video/player/Player;
    iget-object v1, p0, Lcom/archos/mediacenter/video/player/PlayerService;->mStreamingUri:Landroid/net/Uri;
    const/4 v2, 0x0
    invoke-virtual {v0, v1, v2}, Lcom/archos/mediacenter/video/player/Player;->setVideoURI(Landroid/net/Uri;Ljava/util/Map;)V
    return-void
.end method
.method public onPrepared()V
    .locals 0
    return-void
.end method
"""
        changed = patch_service_async_start(original)
        self.assertIn("invoke-static {v0, v1}, Lcom/archos/mediacenter/video/player/WeakStartProxy;->start", changed)
        self.assertIn(".method public onPrepared()V\n    .locals 0\n    return-void", changed)
        with self.assertRaisesRegex(RuntimeError, "missing"):
            patch_service_async_start(original.replace("onStreamingUriOK()V", "invalidMethod()V"))
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            patch_service_async_start(original.replace(
                "    return-void\n.end method",
                "    invoke-virtual {v0, v1, v2}, Lcom/archos/mediacenter/video/player/Player;->setVideoURI(Landroid/net/Uri;Ljava/util/Map;)V\n    return-void\n.end method", 1))


if __name__ == "__main__":
    unittest.main()
