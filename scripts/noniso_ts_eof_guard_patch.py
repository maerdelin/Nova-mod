#!/usr/bin/env python3
"""Run694: clamp finite file TS remote-control Seek before incomplete tail GOP.

The Run693 Android-11 trace has a 48021ms file and a remote DPAD jump
43421 -> 48421ms. FFmpeg attempts to parse a non-existent tail GOP and
returns 'seek did not find a usable starting packet'. Clamp the absolute
seek target for known-duration non-ISO MPEG-TS to a conservative 2-second
pre-EOF window, preserving normal playback/audio drain. ISO /main.m2ts,
live/no_duration TS, MKV, and MP4 are byte-for-byte untouched.
"""
from pathlib import Path
import argparse

MARK = "NOVA_NONISO_TS_EOF_TARGET_CLAMP_V1"
ANCHOR = """\t\twind_start = stream_get_current_pos(video->s, &stream_total);
\t\tdir = pos >= wind_start ? STREAM_SEEK_FORWARD : STREAM_SEEK_BACKWARD;"""
REPLACE = """\t\twind_start = stream_get_current_pos(video->s, &stream_total);
\t\t/* NOVA_NONISO_TS_EOF_TARGET_CLAMP_V1: finite seekable TS only.
\t\t * 48.021s media + DPAD from 43.421s yields 48.421s, past EOF.
\t\t * The final incomplete GOP causes FFmpeg parser seek to abort.
\t\t * Retain two seconds for a decodable TS GOP and natural A/V drain.
\t\t * Never alter libbluray /main.m2ts or other container seek paths. */
\t\tif (video->s && video->s->etype == ETYPE_MPEG_TS &&
\t\t    !video->s->no_duration && video->s->duration > 5000 &&
\t\t    video->s->src.url &&
\t\t    strstr(video->s->src.url, "/main.m2ts") == NULL) {
\t\t\tuint32_t last_safe = (uint32_t)(video->s->duration - 2000);
\t\t\tif (pos > last_safe) {
\t\t\t\tserprintf("NOVA_NONISO_TS_EOF_TARGET_CLAMP_V1: requested=%u duration=%d safe=%u\\n",
\t\t\t\t          (unsigned)pos, video->s->duration, (unsigned)last_safe);
\t\t\t\tpos = last_safe;
\t\t\t}
\t\t}
\t\tdir = pos >= wind_start ? STREAM_SEEK_FORWARD : STREAM_SEEK_BACKWARD;"""

def patch(s: str) -> str:
    if MARK in s: raise RuntimeError("Already patched")
    if s.count(ANCHOR) != 1:
        raise RuntimeError("Pinned avos_mp_video_seek anchor changed or ambiguous")
    return s.replace(ANCHOR, REPLACE, 1)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--native",type=Path,required=True)
    args=p.parse_args()
    f=args.native/"Source"/"avos_mp_video.c"
    content=f.read_text()
    f.write_text(patch(content))
    print(MARK+"=PATCHED")

if __name__=="__main__": main()
