import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import iso_patch

class IsoPatchTests(unittest.TestCase):
    def test_player_injection(self):
        text = """.class public Lcom/archos/mediacenter/video/player/Player;
.super Ljava/lang/Object;
.method private synthetic lambda$openVideo$9(Landroid/net/Uri;Landroid/content/Context;)V
    .locals 2
    invoke-static {p1, p2}, Lcom/archos/filecorelibrary/NetworkInitialization;->awaitReadyForSmb(Landroid/net/Uri;Landroid/content/Context;)V
    invoke-interface {v0, p2, p1}, Lcom/archos/medialib/IMediaPlayer;->setDataSource(Landroid/content/Context;Landroid/net/Uri;)V
    return-void
.end method
"""
        out, status = iso_patch.patch_player_text(text)
        self.assertIn('BlurayIsoProxy;->resolve', out)
        self.assertIn('move-result-object p1', out)
        self.assertTrue(status.startswith('.method '))

    def test_native_source_uses_real_crlf_escapes(self):
        source = (Path(__file__).resolve().parents[1] / 'iso' / 'nova_iso.c').read_text()
        self.assertIn("header[i] == '\\r'", source)
        self.assertIn('"\\r\\n"', source)
        self.assertNotIn("header[i] == '\\\\\\\\r'", source)

    def test_native_url_marks_iso_proxy(self):
        source = (Path(__file__).resolve().parents[1] / 'iso' / 'nova_iso.c').read_text()
        self.assertIn('main.m2ts?mpegts&nova_iso=1', source)

    def test_avos_builder_is_iso_scoped(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts' / 'build_iso_avos.sh').read_text()
        self.assertIn('nova_iso=1', source)
        self.assertIn('skip_estimate_duration_from_pts', source)
        self.assertIn('"10000000"', source)

    def test_proxy_smali_has_native_bridge(self):
        self.assertIn('System;->loadLibrary', iso_patch.PROXY_SMALI)
        self.assertIn('StreamOverHttp;-><init>', iso_patch.PROXY_SMALI)
        self.assertIn('nativeOpen', iso_patch.PROXY_SMALI)

if __name__ == '__main__':
    unittest.main()
