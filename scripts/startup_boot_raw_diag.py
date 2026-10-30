#!/usr/bin/env python3
"""NOVA_BOOT_DIAG_V2: observational RAW producer/consumer/seek stall timings.
Apply AFTER shared42 and all other AVOS patches, before native build.
Abort when pinned source anchor changes rather than modifying scheduling.
"""
import argparse
from pathlib import Path

def once(src,old,new,label):
    count=src.count(old)
    if count!=1: raise RuntimeError(f"BOOT diag {label}: expected 1 anchor got {count}")
    return src.replace(old,new,1)

def apply(p):
    s=p.read_text()
    s=once(s,
        "    int64_t last_log_us;\n",
        "    int64_t last_log_us;\n"
        "    unsigned nova_boot_producer_calls;\n"
        "    unsigned nova_boot_consumer_calls;\n",
        "RAW diagnostic counters")
    s=once(s,
        "        int incoming_page=-1;\n        int got=raw->shared_pages ?\n",
        "        int incoming_page=-1;\n"
        "        int64_t nova_boot_io_begin=av_gettime_relative();\n"
        "        int got=raw->shared_pages ?\n",
        "RAW producer read begin")
    s=once(s,
        "        pthread_mutex_unlock(&raw->source_mutex);\n        if(got>0 && raw->shared_pages && raw->source && raw->source->direct){",
        "        int64_t nova_boot_io_ms=(av_gettime_relative()-nova_boot_io_begin)/1000;\n"
        "        if(nova_boot_io_ms>=100 || raw->nova_boot_producer_calls++<12)\n"
        "            serprintf(\"NOVA_BOOT_RAW_SOURCE tMs=%lld thread=%lu gen=%u want=%d got=%d ioMs=%lld shared=%d\\n\",\n"
        "                  (long long)(av_gettime_relative()/1000),\n"
        "                  (unsigned long)pthread_self(),generation,want,got,\n"
        "                  (long long)nova_boot_io_ms,raw->shared_pages);\n"
        "        pthread_mutex_unlock(&raw->source_mutex);\n"
        "        if(got>0 && raw->shared_pages && raw->source && raw->source->direct){",
        "RAW producer shared page")
    s=once(s,
        "    pthread_mutex_lock(&raw->mutex);\n    if( nova_mkv_seek_guard_failed(raw) ) {",
        "    int64_t nova_boot_read_begin=av_gettime_relative();\n"
        "    pthread_mutex_lock(&raw->mutex);\n"
        "    if( nova_mkv_seek_guard_failed(raw) ) {",
        "RAW read timing start")
    s=once(s,
        "    if( raw->used_bytes == 0 ) {\n        int ret = raw->eof ? AVERROR_EOF : AVERROR_EXIT;",
        "    int64_t nova_boot_consumer_wait_ms=(av_gettime_relative()-nova_boot_read_begin)/1000;\n"
        "    if(nova_boot_consumer_wait_ms>=100 || raw->nova_boot_consumer_calls++<12)\n"
        "        serprintf(\"NOVA_BOOT_RAW_CONSUMER tMs=%lld thread=%lu gen=%u want=%d used=%lld waitMs=%lld\\n\",\n"
        "                  (long long)(av_gettime_relative()/1000),\n"
        "                  (unsigned long)pthread_self(),raw->generation,size,\n"
        "                  (long long)raw->used_bytes,\n"
        "                  (long long)nova_boot_consumer_wait_ms);\n"
        "    if( raw->used_bytes == 0 ) {\n"
        "        int ret = raw->eof ? AVERROR_EOF : AVERROR_EXIT;",
        "RAW consumer wait")
    s=once(s,
        "    pthread_mutex_lock(&raw->source_mutex);\n    int64_t result = avio_seek(raw->source, target, SEEK_SET);",
        "    int64_t nova_boot_seek_lock_begin=av_gettime_relative();\n"
        "    pthread_mutex_lock(&raw->source_mutex);\n"
        "    int64_t nova_boot_seek_lock_ms=(av_gettime_relative()-nova_boot_seek_lock_begin)/1000;\n"
        "    int64_t nova_boot_seek_io_begin=av_gettime_relative();\n"
        "    int64_t result = avio_seek(raw->source, target, SEEK_SET);\n"
        "    int64_t nova_boot_seek_io_ms=(av_gettime_relative()-nova_boot_seek_io_begin)/1000;\n"
        "    serprintf(\"NOVA_BOOT_RAW_SEEK tMs=%lld thread=%lu current=%lld target=%lld result=%lld lockMs=%lld ioMs=%lld\\n\",\n"
        "              (long long)(av_gettime_relative()/1000),\n"
        "              (unsigned long)pthread_self(),\n"
        "              (long long)current,(long long)target,(long long)result,\n"
        "              (long long)nova_boot_seek_lock_ms,(long long)nova_boot_seek_io_ms);",
        "RAW seek lock and IO")
    p.write_text(s)
    print("NOVA_BOOT_DIAG_V2_RAW=PASS")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--native",required=True,type=Path)
    args=parser.parse_args()
    apply(args.native/"Source"/"stream_parser_ffmpeg.c")
