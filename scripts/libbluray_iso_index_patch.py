#!/usr/bin/env python3
"""Add a private, non-mutating CLPI time-to-byte lookup to pinned libbluray.

Read-only NAV index traversal avoids bd_seek_time(), bd_seek() and bd_read(),
which would otherwise move the active playback reader just to discover an
offset. Fail closed if the pinned source anchor changes.
"""
from __future__ import annotations
import argparse
from pathlib import Path

MARK = "NOVA_BD_READONLY_TIME_INDEX_V3"
INSERT = r'''
/* NOVA_BD_READONLY_TIME_INDEX_V3: map time without changing the stream,
 * angle, event queue, state or read-ahead position. Single-clip validation
 * is performed by the NOVA transport caller. BLURAY's normal mutex is used
 * because the NAV_TITLE index may be replaced on title selection. */
int64_t bd_nova_map_time_to_byte(BLURAY *bd, uint64_t tick,
                                 uint64_t *indexed_tick)
{
    if (!bd || !indexed_tick || (tick >> 33))
        return -1;
    *indexed_tick=0;
    int64_t result=-1;
    uint64_t nav_tick=tick/2; /* libbluray NAV uses 45 kHz */
    bd_mutex_lock(&bd->mutex);
    if (bd->title && !bd->seamless_angle_change &&
        nav_tick < bd->title->duration) {
        uint32_t clip_pkt=0, out_pkt=0;
        const NAV_CLIP *clip=nav_time_search(bd->title,(uint32_t)nav_tick,
                                             &clip_pkt,&out_pkt);
        if (clip && out_pkt < bd->title->packets) {
            uint32_t check_clip=0, check_out=0, out_time=0;
            const NAV_CLIP *actual=nav_packet_search(
                bd->title,out_pkt,&check_clip,&check_out,&out_time);
            if (actual && check_out==out_pkt) {
                /* NAV uses title-relative 45 kHz; public API is 90 kHz. */
                *indexed_tick=((uint64_t)out_time+actual->title_time)*2ULL;
                result=(int64_t)out_pkt*192LL;
            }
        }
    }
    bd_mutex_unlock(&bd->mutex);
    return result;
}

'''
ANCHOR = "uint64_t bd_tell_time(BLURAY *bd)\n{"

def patch(text: str) -> str:
    if MARK in text:
        raise RuntimeError("Already patched")
    if text.count(ANCHOR)!=1:
        raise RuntimeError("Pinned libbluray anchor missing or ambiguous")
    return text.replace(ANCHOR,INSERT+ANCHOR,1)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("path",type=Path)
    args=p.parse_args()
    src=args.path.read_text()
    args.path.write_text(patch(src))
    print(MARK+"=PATCHED")

if __name__=="__main__":
    main()
