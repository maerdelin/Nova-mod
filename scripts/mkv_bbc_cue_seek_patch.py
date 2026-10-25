#!/usr/bin/env python3
"""NOVA_MKV_BBC_CUE_SEEK_V1: MKV-only indexed backward seek and bounded reads.

Patch AFTER iso_index_seek_patch.py, preserving its byte-identical ISO path.
MP4/TS/AVI retain Run687's unmodified time seek and fallback.
"""
import argparse
from pathlib import Path

def once(src, before, after, label):
    found = src.count(before)
    if found != 1:
        raise RuntimeError(f"{label}: expected 1 anchor, got {found}")
    return src.replace(before, after, 1)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--native",type=Path,required=True)
    args=parser.parse_args()
    file=args.native/"Source/stream_parser_ffmpeg.c"
    src=file.read_text()
    anchor='    /* NOVA_ISO_INDEX_SEEK_V3: only verified single-clip ISO, never MP4/MKV. */\n    int ret=-1;'
    replacement='''    /* NOVA_MKV_BBC_CUE_SEEK_V1: indexed video keyframe, MKV one-GET only. */
    int nova_mkv_seek = ff_p->raw.enabled && ff_p->raw.mkv_single_get &&
                        !ff_p->nova_iso_time_mode && time >= 0 &&
                        s->video->valid && stream >= 0 &&
                        stream < (int)fmt->nb_streams;
    if(nova_mkv_seek) {
        ff_p->raw.mkv_seek_bytes=0;
        ff_p->raw.mkv_seek_started_us=av_gettime_relative();
        __atomic_store_n(&ff_p->raw.mkv_seek_failed,0,__ATOMIC_RELEASE);
        __atomic_store_n(&ff_p->raw.mkv_seek_active,1,__ATOMIC_RELEASE);
    }
    /* NOVA_ISO_INDEX_SEEK_V3: only verified single-clip ISO, never MP4/MKV. */
    int ret=-1;'''
    src=once(src,anchor,replacement,"start indexed seek")
    src=once(src,
        '        ret=avformat_seek_file(fmt,-1,seek_min,new_pos,seek_max,av_flags);',
        '''        if(nova_mkv_seek) {
            int64_t video_ts=av_rescale_q(new_pos,AV_TIME_BASE_Q,
                                          fmt->streams[stream]->time_base);
            ret=av_seek_frame(fmt,stream,video_ts,AVSEEK_FLAG_BACKWARD);
            serprintf("NOVA_MKV_BBC_CUE_SEEK_V1: timeUs=%lld streamTs=%lld ret=%d\\n",
                      (long long)new_pos,(long long)video_ts,ret);
        } else {
            ret=avformat_seek_file(fmt,-1,seek_min,new_pos,seek_max,av_flags);
        }''',
        "indexed MKV seek instead of generic scan")
    src=once(src,
        '\tif( ret < 0 ) {\n\t\t// The timestamp seek can fail',
        '\tif( ret < 0 && !nova_mkv_seek ) {\n\t\t// The timestamp seek can fail',
        "no potentially unbounded fallback for MKV")
    src=once(src,
        '\tif( ret < 0 ) {\nserprintf("FFMPEG: seek error\\r\\n");',
        '''\tif( ret < 0 && nova_mkv_seek ) {
        __atomic_store_n(&ff_p->raw.mkv_seek_active,0,__ATOMIC_RELEASE);
        __atomic_store_n(&ff_p->raw.mkv_seek_failed,0,__ATOMIC_RELEASE);
    }
\tif( ret < 0 ) {
serprintf("FFMPEG: seek error\\r\\n");''',
        "clear MKV state on indexed seek failure")
    orig='while ((unsigned)(atime() - deadline) < 15000) { /* NOVA_MP4_SEEK_SLOW_READ_GRACE_V1 */'
    repl=orig+'''
        /* Abort only the MKV seek scan after failed Range or bounded work.
         * Non-MKV still has Run687's 15s refill path. */
        if(nova_mkv_seek &&
           (__atomic_load_n(&ff_p->raw.mkv_seek_failed,__ATOMIC_ACQUIRE) ||
            av_gettime_relative()-ff_p->raw.mkv_seek_started_us>12000000 ||
            ff_p->raw.mkv_seek_bytes>(64ULL*1024*1024))) {
            serprintf("NOVA_MKV_BBC_SEEK_STOP_V1: bytes=%llu\\n",
                      (unsigned long long)ff_p->raw.mkv_seek_bytes);
            break;
        }'''
    src=once(src,orig,repl,"bounded MKV refill")
    src=once(src,
        '\tff_p->seeking = 0;\n\tif (!found) {',
        '''\tff_p->seeking = 0;
    if(nova_mkv_seek) {
        __atomic_store_n(&ff_p->raw.mkv_seek_active,0,__ATOMIC_RELEASE);
        __atomic_store_n(&ff_p->raw.mkv_seek_failed,0,__ATOMIC_RELEASE);
    }
\tif (!found) {''',"clear guarded state after packet search")
    file.write_text(src)
    print("NOVA_MKV_BBC_CUE_SEEK_V1=PATCHED")

if __name__=="__main__":
    main()
