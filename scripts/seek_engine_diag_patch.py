#!/usr/bin/env python3
"""Observe why a completed backward Seek has data but no new rendered frames.

Collect 1Hz samples from existing independent rebuffer diagnostic heartbeat.
No change to pause, clock, decoder, AVIO, buffering or subtitles.
"""
import argparse
from pathlib import Path

def one(s, a, b, tag):
    count = s.count(a)
    if count != 1:
        raise RuntimeError(f'{tag}: expected one anchor, got {count}')
    return s.replace(a,b,1)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--native", type=Path, required=True)
    a=ap.parse_args()
    root=a.native

    include=root/"Include/stream.h"
    text=include.read_text()
    text=one(text,
       "    int nova_final_parser_reason;\n",
       "    int nova_final_parser_reason;\n    int nova_seek_engine_loops;\n",
       "add engine-loop counter")
    include.write_text(text)

    path=root/"Source/stream_video.c"
    text=path.read_text()
    text=one(text,
       "            s->player( s );\n",
       "            __atomic_fetch_add(&s->nova_seek_engine_loops, 1, __ATOMIC_RELAXED);\n"
       "            s->player( s );\n",
       "count engine dispatches")
    # Install beside the 1Hz heartbeat, not inside any player/codec loop.
    needle="        __atomic_load_n(&s->nova_diag_drop_late, __ATOMIC_RELAXED));\n"
    sample=r'''        /* NOVA_SEEK_ENGINE_DIAG_V1: observe decode and audio scheduling.
         * Poll from the existing independent heartbeat thread. */
        serprintf("NOVA_SEEK_ENGINE_DIAG_V1: wall=%d epoch=%d engineT=%d audioT=%d videoState=%d engineLoops=%d videoDec=%s flush=%d cNow=%d cNext=%d decodeFrame=%d playN=%d videoEnd=%d audioEnd=%d videoError=%d audioStartPending=%d audioPreload=%d audioBuffer=%d syncA=%d syncV=%d aDrop=%d vDrop=%d videoTargetPending=%d aPts=%d vPts=%d decQ=%d dispQ=%d codecQ=%d\n",
          now, s->seek_epoch, thread_state_get(&s->engine_tstate),
          thread_state_get(&s->audio_tstate), s->video_state,
          __atomic_load_n(&s->nova_seek_engine_loops, __ATOMIC_RELAXED),
          (s->video_dec && s->video_dec->name) ? s->video_dec->name : "none",
          s->video_flush, s->cdata_now.valid, s->cdata_next.valid,
          !!s->decode_frame, s->play_n_video_frames,
          s->video_end, s->audio_end, s->video_error,
          s->audio_start_pending, s->audio_preload, s->audio_buffer_size,
          s->sync_audio, s->sync_video, s->seek_audio_drop,
          s->seek_video_drop, s->seek_video_target_pending,
          s->audio_time, s->video_time,
          frame_q_count(&s->decode_q), frame_q_count(&s->disp_q),
          frame_q_count(&s->codec_q));
'''
    text=one(text,needle,needle+sample,"heartbeat addition")
    assert text.count("NOVA_SEEK_ENGINE_DIAG_V1:") == 1
    path.write_text(text)
    print("NOVA_SEEK_ENGINE_DIAG_V1=INSTRUMENTED")

if __name__=="__main__":
    main()
