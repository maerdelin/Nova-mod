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

    def test_iso_only_player_factory_patch(self):
        text = """.class public Lcom/archos/mediacenter/video/player/Player;
.super Ljava/lang/Object;
.method public setVideoURI(Landroid/net/Uri;Ljava/util/Map;)V
    .locals 1
    return-void
.end method
.method public openVideo()V
    .locals 3
    invoke-static {v0, v1}, Lcom/archos/medialib/MediaFactory;->createPlayer(Landroid/content/Context;Z)Lcom/archos/medialib/IMediaPlayer;
    move-result-object v2
    return-void
.end method
"""
        out, status = iso_patch.patch_force_avos_player_text(text)
        self.assertIn('BlurayIsoProxy;->armForUri', out)
        self.assertIn('IsoPlayerFactory;->create', out)
        self.assertNotIn('MediaFactory;->createPlayer(Landroid/content/Context;Z)', out)
        self.assertEqual(status, 'applied')

    def test_initial_zero_seek_is_skipped_only_through_player_service_wrapper(self):
        text = """.class public Lcom/archos/mediacenter/video/player/PlayerService;
.super Ljava/lang/Object;
.method private postPreparedAndVideoDb()V
    .locals 2
    sget-object v0, Lcom/archos/mediacenter/video/player/Player;->sPlayer:Lcom/archos/mediacenter/video/player/Player;
    const/4 v1, 0x0
    invoke-virtual {v0, v1}, Lcom/archos/mediacenter/video/player/Player;->seekTo(I)V
    return-void
.end method
"""
        out, status = iso_patch.patch_initial_zero_seek_player_service_text(text)
        self.assertIn('invoke-static {v0, v1}, Lcom/archos/mediacenter/video/player/IsoPlayerFactory;->seekTo', out)
        self.assertNotIn('invoke-virtual {v0, v1}, Lcom/archos/mediacenter/video/player/Player;->seekTo(I)V', out)
        self.assertEqual(status, 'applied')

    def test_iso_initial_zero_seek_guard_is_one_shot(self):
        self.assertIn('.field private static sSkipInitialZeroSeek:Z', iso_patch.PROXY_SMALI)
        self.assertIn('shouldSkipInitialZeroSeek(I)Z', iso_patch.PROXY_SMALI)
        self.assertIn('SEEK_ZERO_SKIP iso=1', iso_patch.ISO_FACTORY_SMALI)
        self.assertIn('Player;->seekTo(I)V', iso_patch.ISO_FACTORY_SMALI)

    def test_stream_over_http_source_uri_patch(self):
        text = """.class public Lcom/archos/filecorelibrary/StreamOverHttp;
.super Ljava/lang/Object;
.field private final mUri:Landroid/net/Uri;
.method private copyStream(Ljava/io/InputStream;Ljava/io/OutputStream;[BJ)V
    .locals 1
    invoke-virtual {p2}, Ljava/io/OutputStream;->flush()V
    return-void
.end method
"""
        out, status = iso_patch.patch_stream_over_http_text(text)
        self.assertIn('getSourceUri()Landroid/net/Uri;', out)
        self.assertIn('->mUri:Landroid/net/Uri;', out)
        self.assertNotIn('Ljava/io/OutputStream;->flush()V', out)
        self.assertEqual(status, 'applied')

    def test_stream_http_session_wraps_primary_webdav_input(self):
        text = """.class public Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;
.super Ljava/lang/Object;
.field final synthetic this$0:Lcom/archos/filecorelibrary/StreamOverHttp;
.field private supersedableMediaRequest:Z
.field private partialResponse:Z
.field private requestedStart:J
.field private requestedEnd:J
.field private length:J
.method private publishInput(Ljava/io/InputStream;)V
    .locals 1
    return-void
.end method
"""
        out, status = iso_patch.patch_stream_http_session_text(text)
        self.assertIn('.locals 3', out)
        self.assertIn('NetworkReadAheadInputStream;->wrap', out)
        self.assertIn('shouldUseNetworkReadAhead()Z', out)
        self.assertIn('const-wide/32 v2, 0x800000', out)
        self.assertIn('const-wide/16 v4, 0x1', out)
        self.assertIn('requestedStart:J', out)
        self.assertIn('requestedEnd:J', out)
        self.assertIn('length:J', out)
        self.assertIn('getSourceUri()Landroid/net/Uri;', out)
        self.assertEqual(status, 'applied')

    def test_webdav_readahead_uses_background_pipe(self):
        self.assertIn('PipedInputStream;-><init>(I)V', iso_patch.READ_AHEAD_SMALI)
        self.assertIn('const v1, 0x2000000', iso_patch.READ_AHEAD_SMALI)
        self.assertIn('Nova WebDAV read-ahead', iso_patch.READ_AHEAD_SMALI)
        self.assertIn('READ_AHEAD_ON webdav cap=32MiB low=2MiB start=8MiB rebuffer=16/24/28MiB', iso_patch.READ_AHEAD_SMALI)
        self.assertIn('BUFFER_LOW stage=1 target=16MiB', iso_patch.READ_AHEAD_SMALI)
        self.assertIn('BUFFER_LOW stage=2 target=24MiB', iso_patch.READ_AHEAD_SMALI)
        self.assertIn('BUFFER_LOW stage=3 target=28MiB', iso_patch.READ_AHEAD_SMALI)
        self.assertIn('BUFFER_READY', iso_patch.READ_AHEAD_SMALI)
        self.assertIn('LockSupport;->parkNanos(J)V', iso_patch.READ_AHEAD_SMALI)
        self.assertIn('implements Ljava/lang/Runnable;', iso_patch.READ_AHEAD_SMALI)

    def test_iso_playback_uses_persistent_range_stream(self):
        source = (Path(__file__).resolve().parents[1] / 'iso' / 'nova_iso.c').read_text()
        self.assertIn('fetch_range_playback', source)
        self.assertIn('STREAM_OPEN_READY', source)
        self.assertIn('Range: bytes=%" PRId64 "-\\r\\nConnection: close', source)
        self.assertIn('s->input.playback_mode = 1;', source)
        self.assertIn('close_playback_stream(&s->input);', source)

    def test_iso_player_factory_forces_avos_then_restores_any_decoder(self):
        self.assertIn('const/4 v0, 0x1', iso_patch.ISO_FACTORY_SMALI)
        self.assertIn('AvosMediaPlayer;', iso_patch.ISO_FACTORY_SMALI)
        self.assertIn('LibAvos;->setDecoder(I)V', iso_patch.ISO_FACTORY_SMALI)
        self.assertIn('PLAYER_FACTORY avos=1 forced=1', iso_patch.ISO_FACTORY_SMALI)

    def test_native_source_uses_real_crlf_escapes(self):
        source = (Path(__file__).resolve().parents[1] / 'iso' / 'nova_iso.c').read_text()
        self.assertIn("header[i] == '\\r'", source)
        self.assertIn('"\\r\\n"', source)
        self.assertNotIn("header[i] == '\\\\\\\\r'", source)

    def test_native_url_marks_iso_proxy(self):
        source = (Path(__file__).resolve().parents[1] / 'iso' / 'nova_iso.c').read_text()
        self.assertIn('main.m2ts?mpegts&nova_iso=1', source)

    def test_stock_avos_is_preserved(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts' / 'iso_patch.py').read_text()
        self.assertNotIn("shutil.copyfile(avos_src", source)
        self.assertNotIn("avos_dir / abi / 'libavos.so'", source)

    def test_proxy_smali_has_native_bridge(self):
        self.assertIn('System;->loadLibrary', iso_patch.PROXY_SMALI)
        self.assertIn('StreamOverHttp;-><init>', iso_patch.PROXY_SMALI)
        self.assertIn('nativeOpen', iso_patch.PROXY_SMALI)

    def test_native_preempt_does_not_reuse_stale_client_fd(self):
        source = (Path(__file__).resolve().parents[1] / 'iso' / 'nova_iso.c').read_text()
        self.assertIn('pthread_mutex_t client_lock;', source)
        self.assertIn('if (s->client_fd == fd) s->client_fd = -1;', source)
        self.assertIn('pthread_mutex_lock(&s->client_lock);', source)

if __name__ == '__main__':
    unittest.main()
