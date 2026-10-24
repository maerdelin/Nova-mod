#!/usr/bin/env python3
"""NOVA Test: bounded seekable byte window inside existing RAW128 ring.

Keeps up to 16 MiB of already consumed bytes, using the same fixed 128 MiB
buffer; no new allocation and no change to the low/resume/capacity policy.
A seek inside [consumer-history, consumer+unread] does not touch HTTP/AVIO,
does not cancel the producer, and preserves the producer's source position.
"""
import argparse
from pathlib import Path

def rep(s,old,new,tag):
    n=s.count(old)
    if n!=1: raise RuntimeError(f"{tag}: expected once, got {n}")
    return s.replace(old,new,1)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--native',type=Path,required=True)
    a=p.parse_args()
    path=a.native/'Source/stream_parser_ffmpeg.c'
    s=path.read_text()
    assert 'NOVA_SEEK_PREEMPT_V1' in s
    s=rep(s,
          "#define NOVA_RAW_IO_BYTES             (128 * 1024)\n",
          "#define NOVA_RAW_IO_BYTES             (128 * 1024)\n"
          "#define NOVA_RAW_SEEK_HISTORY_BYTES   (16 * 1024 * 1024)\n",
          "history limit")
    s=rep(s,
          "    int64_t used_bytes;\n    int64_t capacity_bytes;\n",
          "    int64_t used_bytes;\n    int64_t history_bytes;\n    int64_t capacity_bytes;\n",
          "history bytes")
    s=rep(s,
          "    raw->used_bytes = 0;\n}\n\nstatic void nova_raw_log_locked",
          "    raw->used_bytes = 0;\n    raw->history_bytes = 0;\n}\n\nstatic void nova_raw_log_locked",
          "reset history")
    # Producer must reserve written bytes without destroying preserved history.
    anchor="        generation = raw->generation;\n        int64_t room = raw->capacity_bytes - raw->used_bytes;\n"
    changed="""        /* NOVA_RAW_CACHE_SEEK_V1: reserve a short history window only while
         * room exists; evict oldest history before overwriting it. */
        int64_t room = raw->capacity_bytes - raw->used_bytes -
                       raw->history_bytes;
        if(room < NOVA_RAW_IO_BYTES && raw->history_bytes > 0) {
            int64_t evict = NOVA_RAW_IO_BYTES - room;
            if(evict > raw->history_bytes) evict = raw->history_bytes;
            raw->history_bytes -= evict;
        }
        generation = raw->generation;
        room = raw->capacity_bytes - raw->used_bytes - raw->history_bytes;
"""
    s=rep(s,anchor,changed,"producer memory window")
    anchor="        raw->used_bytes -= take;\n        raw->consumed_bytes += take;\n"
    changed=anchor+"""        raw->history_bytes += take;
        if(raw->history_bytes > NOVA_RAW_SEEK_HISTORY_BYTES)
            raw->history_bytes = NOVA_RAW_SEEK_HISTORY_BYTES;
"""
    s=rep(s,anchor,changed,"history on consume")
    anchor="""    if( target < 0 || (size >= 0 && target > size) )
        return AVERROR(EINVAL);

    /* Request preemption BEFORE source_mutex, not after it. */
"""
    changed="""    if( target < 0 || (size >= 0 && target > size) )
        return AVERROR(EINVAL);

    /* NOVA_RAW_CACHE_SEEK_V1: only move logical read cursor when target
     * bytes are still in the ring. The producer owns the network position;
     * it continues normally, with no socket reset or source_mutex wait. */
    pthread_mutex_lock(&raw->mutex);
    int64_t move = target - raw->consumer_pos;
    if(raw->enabled && __atomic_load_n(&raw->run,__ATOMIC_ACQUIRE) &&
       !__atomic_load_n(&raw->seek_preempt,__ATOMIC_ACQUIRE) &&
       ((move >= 0 && move <= raw->used_bytes) ||
        (move < 0 && -move <= raw->history_bytes))) {
        int64_t cap = raw->capacity_bytes;
        int64_t oldpos=raw->consumer_pos;
        if(move >= 0) {
            raw->read_off = (raw->read_off + move) % cap;
            raw->used_bytes -= move;
            raw->history_bytes += move;
            if(raw->history_bytes > NOVA_RAW_SEEK_HISTORY_BYTES)
                raw->history_bytes = NOVA_RAW_SEEK_HISTORY_BYTES;
            raw->consumed_bytes += move;
        } else {
            int64_t back = -move;
            raw->read_off = (raw->read_off + cap - back % cap) % cap;
            raw->history_bytes -= back;
            raw->used_bytes += back;
        }
        raw->consumer_pos=target;
        pthread_cond_broadcast(&raw->can_read);
        pthread_cond_broadcast(&raw->can_write);
        serprintf("NOVA_RAW_CACHE_SEEK_V1: from=%lld to=%lld move=%lld history=%lld unread=%lld\\n",
                  (long long)oldpos,(long long)target,(long long)move,
                  (long long)raw->history_bytes,(long long)raw->used_bytes);
        pthread_mutex_unlock(&raw->mutex);
        return target;
    }
    pthread_mutex_unlock(&raw->mutex);

    /* Request preemption BEFORE source_mutex, not after it. */
"""
    s=rep(s,anchor,changed,"cached hit before network seek")
    # Guard against a copied ring producer reservation writing past previous
    # cached history: all modifications of valid range happen under raw mutex.
    assert s.count('NOVA_RAW_CACHE_SEEK_V1')==3
    path.write_text(s)
    print('NOVA_RAW_CACHE_SEEK_V1=PATCHED')

if __name__ == '__main__':main()
