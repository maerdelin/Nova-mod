#!/usr/bin/env python3
"""Test-only indexed FFmpeg video-stream seek for MKV/MP4, with safe fallback.

Use the selected video stream's index and time_base before asking FFmpeg
to perform generic format-wide timestamp search. Fallback is unchanged.
ISO/TS remains handled by the Blu-ray-indexed seek experiment.
"""
import argparse
from pathlib import Path
def rep(s, a, b):
    count=s.count(a)
    if count!=1: raise RuntimeError("indexed video seek anchor count=%d" % count)
    return s.replace(a,b,1)

PATCH=r'''
    /* NOVA_FAST_VIDEO_INDEX_SEEK_V1: use the selected video track index.
     * MKV/MP4 have seek tables, whereas generic -1 avformat_seek_file
     * may perform repeated network probes. Preserve original fallback.
     */
    int ret = -1;
    if ((s->etype == ETYPE_MKV || s->etype == ETYPE_MP4) &&
        s->video->valid && s->video->stream >= 0 &&
        s->video->stream < fmt->nb_streams && time > 0) {
        AVStream *vs = fmt->streams[s->video->stream];
        if (vs && vs->time_base.num > 0 && vs->time_base.den > 0) {
            int64_t video_ts = av_rescale_q(new_pos, AV_TIME_BASE_Q, vs->time_base);
            int seek_t0=atime();
            ret = av_seek_frame(fmt,s->video->stream,video_ts,AVSEEK_FLAG_BACKWARD);
            serprintf("NOVA_FAST_VIDEO_INDEX_SEEK_V1: type=%d targetMs=%d stream=%d streamTs=%lld elapsedMs=%d ret=%d\n",
                      s->etype,time,s->video->stream,(long long)video_ts,
                      atime()-seek_t0,ret);
        }
    }
    if(ret < 0) {
        int fallback_t0=atime();
        ret=avformat_seek_file(fmt,-1,seek_min,new_pos,seek_max,av_flags);
        serprintf("NOVA_FAST_VIDEO_INDEX_FALLBACK: type=%d timeMs=%d elapsedMs=%d ret=%d\n",
                  s->etype,time,atime()-fallback_t0,ret);
    }
'''
def main():
    p=argparse.ArgumentParser();p.add_argument('--native',type=Path,required=True);a=p.parse_args()
    path=a.native/'Source/stream_parser_ffmpeg.c';s=path.read_text()
    assert "NOVA_PGS_HISTORY_BYPASS_AB_V1" in s
    s=rep(s,"\tint ret = avformat_seek_file( fmt, -1, seek_min, new_pos, seek_max, av_flags);\n",PATCH)
    path.write_text(s)
    print("NOVA_FAST_VIDEO_INDEX_SEEK_V1=PATCHED")
if __name__=='__main__':main()
