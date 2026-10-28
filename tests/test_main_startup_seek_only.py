"""Minimal regression: source-side startup zero seek, no playback-path changes."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import direct_transport_apply as app
import startup_bbc_seek_fix_patch as native

SVC=""".class public Lcom/archos/mediacenter/video/player/PlayerService;
.super Ljava/lang/Object;
.method private postPreparedAndVideoDb()V
    .locals 3
    invoke-virtual {v0, v1}, Lcom/archos/mediacenter/video/player/Player;->seekTo(I)V
    return-void
.end method
.method public manualSeek()V
    .locals 2
    invoke-virtual {v0, v1}, Lcom/archos/mediacenter/video/player/Player;->seekTo(I)V
    return-void
.end method
"""
RESUME=""".class public Lcom/archos/mediacenter/video/player/Player$ResumeCtx;
.super Ljava/lang/Object;
.method public onPrepared()V
    .locals 2
    invoke-virtual {v0, v1}, Lcom/archos/mediacenter/video/player/Player;->seekTo(I)V
    return-void
.end method
.method public manualSeek(I)V
    .locals 0
    return-void
.end method
"""
FF="""static int _set_audio_stream( STREAM *s, int audio_stream )
{
\treturn stream_parser_set_audio_stream( s, audio_stream);
}"""

class StartupOnlyRegression(unittest.TestCase):
    def test_service_no_zero_request_but_preserve_manual(self):
        s=app.patch_service(SVC)
        self.assertIn("NOVA_STARTUP_ZERO_NO_REQUEST_V1",s)
        self.assertIn("if-eqz v1, :nova_startup_zero_no_request_done",s)
        self.assertIn("DirectPlayerFactory;->seekTo",s)
        self.assertEqual(s.count("invoke-virtual {v0, v1}, Lcom/archos/mediacenter/video/player/Player;->seekTo(I)V"),1)
        self.assertNotIn("NOVA_RELATIVE_UNKNOWN_INIT_V1",s)

    def test_prepared_resume_zero_only(self):
        s=app.patch_resume_ctx_initial_zero(RESUME)
        self.assertIn("NOVA_RESUME_ZERO_NO_REQUEST_V1",s)
        self.assertIn("if-eqz v1, :nova_resume_zero_no_request_done",s)
        self.assertEqual(s.count("->seekTo(I)V"),1)

    def test_audio_pre_first_frame_only(self):
        s=native.patch_initial_ffmpeg_audio_selection(FF)
        for v in ("s->video_time < 0 && s->audio_time < 0",
                  "s->seek_epoch == 0",
                  "s->start_time == 0 && s->start_pos == 0",
                  '_flush_packets( &ff_p->aq, "START_AUDIO_ONLY" )',
                  "stream_parser_clear_audio_chunks( s )"):
            self.assertIn(v,s)
        self.assertEqual(s.count("return stream_parser_set_audio_stream( s, audio_stream);"),1)
        self.assertNotIn("_flush_packets( &ff_p->vq",s)
        self.assertNotIn("stream_seek_time(",s)

    def test_fail_closed_on_changed_sources(self):
        for fn,src in [(app.patch_service,SVC),(app.patch_resume_ctx_initial_zero,RESUME),
                       (native.patch_initial_ffmpeg_audio_selection,FF)]:
            patched=fn(src)
            with self.assertRaises(RuntimeError): fn(patched)
        with self.assertRaises(RuntimeError): app.patch_service(SVC.replace("seekTo(I)V","setAudioTrack(I)V"))
        with self.assertRaises(RuntimeError): native.patch_initial_ffmpeg_audio_selection(FF.replace("stream_parser_set_audio_stream","unsupported"))

if __name__=="__main__":
    unittest.main()
