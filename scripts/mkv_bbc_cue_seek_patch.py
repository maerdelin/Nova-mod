#!/usr/bin/env python3
"""NOVA_MKV_BBC_CUE_SEEK_V1 + NOVA_MKV_SEEK_SCAN_BUDGET_V2: MKV-only indexed backward seek, fresh post-index deadline and bounded reads.

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
                        s->video->valid && s->video->stream >= 0 &&
                        s->video->stream < (int)fmt->nb_streams;
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
                                          fmt->streams[s->video->stream]->time_base);
            ret=av_seek_frame(fmt,s->video->stream,video_ts,AVSEEK_FLAG_BACKWARD);
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
    repl='''/* NOVA_MKV_SEEK_SCAN_BUDGET_V2: a slow indexed HTTP Range
     * must not consume the separate post-index first-packet scan budget.
     * Non-MKV retains the original Run687 15-second deadline. */
    if(nova_mkv_seek && ret >= 0) {
        int64_t nova_position_us =
            av_gettime_relative() - ff_p->raw.mkv_seek_started_us;
        ff_p->raw.mkv_seek_started_us = av_gettime_relative();
        ff_p->raw.mkv_seek_bytes = 0;
        /* Success of the indexed relocation starts a fresh packet-search
         * phase; any later real I/O failure is surfaced again by the reader. */
        __atomic_store_n(&ff_p->raw.mkv_seek_failed,0,__ATOMIC_RELEASE);
        serprintf("NOVA_MKV_SEEK_SCAN_BEGIN_V2: positionMs=%lld scanBudgetMs=12000 maxScanBytes=67108864 generation=%u rebuffer=%d seekPaused=%d\\n",
                  (long long)(nova_position_us / 1000),
                  ff_p->raw.generation,
                  (int)__atomic_load_n(&s->rebuffering,__ATOMIC_ACQUIRE),
                  s->seek_paused);
    }
    unsigned nova_mkv_scan_atime = nova_mkv_seek ? atime() : 0;
    while ((unsigned)(atime() - (nova_mkv_seek ? nova_mkv_scan_atime : deadline)) < 15000) { /* NOVA_MP4_SEEK_SLOW_READ_GRACE_V1 */
        /* Still bound the MKV packet scan to 12s/64MiB after relocation.
         * An I/O error remains an immediate stop, never an infinite retry. */
        if(nova_mkv_seek) {
            int64_t nova_scan_us =
                av_gettime_relative() - ff_p->raw.mkv_seek_started_us;
            int nova_failed = __atomic_load_n(
                &ff_p->raw.mkv_seek_failed,__ATOMIC_ACQUIRE);
            int nova_timed_out = nova_scan_us > 12000000;
            int nova_byte_limit =
                ff_p->raw.mkv_seek_bytes > (64ULL*1024*1024);
            if(nova_failed || nova_timed_out || nova_byte_limit) {
                const char *nova_reason = nova_timed_out ? "scan_timeout" :
                    (nova_byte_limit ? "scan_byte_limit" : "source_error");
                serprintf("NOVA_MKV_BBC_SEEK_STOP_V1: reason=%s scanMs=%lld bytes=%llu generation=%u rawUsed=%lld rawError=%d rebuffer=%d seekPaused=%d\\n",
                          nova_reason,(long long)(nova_scan_us / 1000),
                          (unsigned long long)ff_p->raw.mkv_seek_bytes,
                          ff_p->raw.generation,
                          (long long)ff_p->raw.used_bytes,
                          ff_p->raw.error,
                          (int)__atomic_load_n(&s->rebuffering,__ATOMIC_ACQUIRE),
                          s->seek_paused);
                break;
            }
        }'''
    src=once(src,orig,repl,"bounded MKV refill")
    src=once(src,
        '\tff_p->seeking = 0;\n\tif (!found) {',
        '''\tff_p->seeking = 0;
    if(nova_mkv_seek) {
        serprintf("NOVA_MKV_SEEK_DONE_V2: found=%d scanMs=%lld bytes=%llu rebuffer=%d seekPaused=%d\\n",
                  found,
                  (long long)((av_gettime_relative() - ff_p->raw.mkv_seek_started_us)/1000),
                  (unsigned long long)ff_p->raw.mkv_seek_bytes,
                  (int)__atomic_load_n(&s->rebuffering,__ATOMIC_ACQUIRE),
                  s->seek_paused);
        __atomic_store_n(&ff_p->raw.mkv_seek_active,0,__ATOMIC_RELEASE);
        __atomic_store_n(&ff_p->raw.mkv_seek_failed,0,__ATOMIC_RELEASE);
    }
\tif (!found) {''',"clear guarded state after packet search")
    file.write_text(src)
    print("NOVA_MKV_BBC_CUE_SEEK_V1=PATCHED")

if __name__=="__main__":
    main()
