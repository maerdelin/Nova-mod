#!/usr/bin/env python3
"""Minimal AVOS v6.6 natural-EOF compatibility port for main/6.5.5.

Field evidence from the actual WebDAV "诗词大会" TS:
  video_end=1, parser EOF, no queued packets
  audio_time=5393922, video_time=5393526 (audio ahead 396 ms)
  PCM lead gate's threshold is 200 ms.  Unlike stream_sync_audio(),
  stream_sync_pcm_audio_lead_gate() does NOT bypass its audio-writer
  throttle when video has genuinely ended.  Video's frozen clock can
  therefore prevent the last PCM from reaching the ordinary drain path.

This patch changes ONE conditional in Source/stream_sync.c.  It only
releases a *would-block* PCM lead gate after both parsers and the video
have reached their actual terminal EOF for the current session.  It
does NOT set audio_end, seek, flush, bypass live playback pacing or
fake the native onCompletion callback.  The original main/6.5.5
playback_completion_patch.py remains byte-for-byte unchanged.
"""
import argparse
import json
from pathlib import Path

ANCHOR = """\tif( diff < -gate_ms ) {
DBG serprintf("pcm_audio_lead_gate: hold sync_v=%d heard=%d diff=%d raw_diff=%d av_delay=%d dbg_delay=%d gate=%d\\n",
"""

REPLACEMENT = """\tif( diff < -gate_ms ) {
        /*
         * NOVA_MAIN655_TS_EOF_LEAD_GATE_RELEASE_V1
         * Video has already reached true parser EOF and completed output.
         * It cannot advance sync_v_time. Holding a final AAC PCM write
         * because heard audio is >200ms ahead would deadlock the original
         * main/6.5.5 decoder/AudioTrack drain and completion callback.
         * Do not bypass this gate during ordinary play, seeks or pauses.
         */
        if( s->video_end && s->video_parse_end && s->audio_parse_end &&
            !s->audio_end && !s->paused && !s->seek_paused &&
            s->video_error == VE_NO_ERROR ) {
            static int64_t nova_last_eof_gate_log_ms = 0;
            int64_t nova_now = atime64();
            int64_t nova_before = __atomic_load_n(
                &nova_last_eof_gate_log_ms, __ATOMIC_RELAXED);
            if( nova_now - nova_before >= 1000 &&
                __atomic_compare_exchange_n(
                    &nova_last_eof_gate_log_ms, &nova_before, nova_now, 0,
                    __ATOMIC_RELAXED, __ATOMIC_RELAXED) ) {
                serprintf("NOVA_MAIN655_TS_EOF_LEAD_RELEASE_V1: epoch=%d syncV=%d heard=%d audio=%d diff=%d gate=%d\\n",
                    s->seek_epoch, s->sync_v_time, heard_ts,
                    s->audio_time, diff, gate_ms);
            }
            return 0; /* Let original audio worker drain real PCM. */
        }
DBG serprintf("pcm_audio_lead_gate: hold sync_v=%d heard=%d diff=%d raw_diff=%d av_delay=%d dbg_delay=%d gate=%d\\n",
"""

def patch_sync(text: str) -> str:
    if "NOVA_MAIN655_TS_EOF_LEAD_GATE_RELEASE_V1" in text:
        raise RuntimeError("duplicate EOF lead gate patch")
    if text.count(ANCHOR) != 1:
        raise RuntimeError("expected exactly one v6.6 PCM lead gate anchor; got "+str(text.count(ANCHOR)))
    if "if( s->video_end ) {" not in text:
        raise RuntimeError("AVOS upstream stream_sync_audio() EOF bypass missing")
    out=text.replace(ANCHOR, REPLACEMENT, 1)
    if out.count("NOVA_MAIN655_TS_EOF_LEAD_RELEASE_V1")!=1:
        raise RuntimeError("new EOF runtime marker missing")
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--native",type=Path,required=True)
    ap.add_argument("--report",type=Path)
    args=ap.parse_args()
    p=args.native/"Source/stream_sync.c"
    before=p.read_text()
    after=patch_sync(before)
    p.write_text(after)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps({
            "status":"PASS",
            "source_baseline":"main/6.5.5 original natural EOF",
            "source_file":"Source/stream_sync.c",
            "added_marker":"NOVA_MAIN655_TS_EOF_LEAD_RELEASE_V1",
            "precondition":"PCM lead gate would block (>200 ms); true video/parser terminal EOF; no seek/pause/error",
            "media_completion_fabricated":False,
            "normal_playback_changed":False,
            "files_patched":1,
        },indent=2)+"\n")
    print("NOVA_MAIN655_TS_EOF_LEAD_GATE_PORT=PASS")

if __name__=="__main__":
    main()
