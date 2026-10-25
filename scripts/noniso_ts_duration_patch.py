#!/usr/bin/env python3
"""Enable finite file MPEG-TS time seeks without changing live TS or ISO.

Upstream deliberately disables duration for ETYPE_MPEG_TS regardless of
libavformat duration. For a finite and seekable *non-ISO* NOVA direct FILE,
that makes the UI occasionally send millisecond positions to an AVOS
permille-only seek method, yielding e.g. seek pos=7581 (invalid 0..1000).
Only a known-size /stream? file with credible FFmpeg duration is promoted
to time-domain seeking. ISO /main.m2ts and broadcasts retain upstream.
"""
from __future__ import annotations
import argparse
from pathlib import Path

MARK="NOVA_NONISO_TS_DURATION_V1"
ANCHOR="if( fmt->duration != AV_NOPTS_VALUE && etype != ETYPE_MPEG_TS ) {"
PATCH=r'''/* NOVA_NONISO_TS_DURATION_V1: /stream? only, never ISO /main.m2ts.
     * Matroska/MP4 retain their existing keyframe-index timestamp seek.
     * Live/no-size TS continues to use 0..1000 positional seeking.
     * Promote only a finite source for which FFmpeg knows the duration,
     * fixing the mismatch with PlayerController's millisecond seek mode. */
    const int nova_finite_file_ts =
        etype == ETYPE_MPEG_TS && priv->s && priv->size_known &&
        priv->size > 0 && fmt->duration != AV_NOPTS_VALUE &&
        fmt->duration >= 5LL * AV_TIME_BASE &&
        fmt->duration <= 24LL * 3600 * AV_TIME_BASE &&
        priv->s->src.url &&
        strstr(priv->s->src.url,"/stream?") != NULL;
    if( fmt->duration != AV_NOPTS_VALUE &&
        (etype != ETYPE_MPEG_TS || nova_finite_file_ts) ) {
        if(nova_finite_file_ts){
            priv->s->no_duration=0;
            serprintf("NOVA_NONISO_TS_DURATION_V1: duration_us=%lld size=%llu time_domain=ms\n",
                (long long)fmt->duration,(unsigned long long)priv->size);
        }'''
def patch(s:str)->str:
    if MARK in s:raise RuntimeError("Already patched")
    if s.count(ANCHOR)!=1:raise RuntimeError("Pinned FFmpeg _parse_format duration anchor missing/changed")
    return s.replace(ANCHOR,PATCH,1)
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--native",type=Path,required=True)
    a=p.parse_args()
    f=a.native/"Source"/"stream_parser_ffmpeg.c"
    text=f.read_text()
    f.write_text(patch(text))
    print(MARK+"=PATCHED")
if __name__=="__main__":
    main()
