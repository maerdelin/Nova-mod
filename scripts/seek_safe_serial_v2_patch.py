#!/usr/bin/env python3
"""RUN653 seek correctness: prevent AVERROR_EXIT poisoning on user seek.

RUN652 field evidence: ISO seek at 22:02:01 caused >1,000 immediate-exit
retries and no rendered frame for >60s. The RUN649 'seek preempt' patch
interrupted the same libbluray/FFmpeg AVIOContext that it later reused.
This repair runs AFTER RUN649 seek/cache patches. It uses a producer gate:
the currently running read completes, then the producer yields source_mutex
to the seek. A seek never calls the transport preempt export and no longer
cancels an in-flight network operation. No change to 2X/5X buffering.
"""
import argparse
from pathlib import Path


def one(source: str, old: str, new: str, name: str) -> str:
    n = source.count(old)
    if n != 1:
        raise RuntimeError(f"{name}: expected unique anchor, got {n}")
    return source.replace(old, new, 1)


def fix_transport(path: Path) -> None:
    s = path.read_text()
    s = one(s,
        "    return !s || s->stopping ||\n"
        "           __atomic_load_n(&s->seek_preempt, __ATOMIC_ACQUIRE);\n",
        "    /* NOVA_SEEK_SAFE_SERIAL_V2: never abort an active libbluray/AVIO\n"
        "     * read just because a user requested a different position. The\n"
        "     * prior design poisoned the upstream context with AVERROR_EXIT. */\n"
        "    return !s || s->stopping;\n",
        "transport upstream AVIO cancel")
    s = one(s,
        "    if (s->stopping || __atomic_load_n(&s->seek_preempt, __ATOMIC_ACQUIRE)) {\n"
        "        ret = AVERROR_EXIT;\n"
        "    } else if (s->mode == NOVA_MODE_BLURAY_ISO) {",
        "    if (s->stopping) {\n"
        "        ret = AVERROR_EXIT;\n"
        "    } else if (s->mode == NOVA_MODE_BLURAY_ISO) {",
        "transport direct read cancel")
    # These historical exports/fields exist only for binary compatibility.
    # Nothing calls them from the new RAW producer or seek path. Prevent any
    # unrelated code from resurrecting the old cancellation behavior.
    s = one(s,
        "    __atomic_store_n(&s->seek_preempt, 1, __ATOMIC_RELEASE);\n"
        "    session_release(s);\n    return 0;\n",
        "    /* Deprecated: an AVIO reader must not be canceled by Seek. */\n"
        "    session_release(s);\n    return 0;\n",
        "disable old exported preempt")
    assert "NOVA_SEEK_SAFE_SERIAL_V2" in s
    assert "return !s || s->stopping;" in s
    path.write_text(s)


def fix_parser(path: Path) -> None:
    s = path.read_text()
    s = one(s,
        "    volatile int seek_preempt;\n",
        "    volatile int seek_preempt; /* deprecated, always zero */\n"
        "    volatile int seek_pending; /* cooperative priority gate */\n",
        "RAW gate field")
    s = one(s,
        "    return __atomic_load_n(&raw->seek_preempt, __ATOMIC_ACQUIRE) ||\n"
        "           (raw->s && stream_abort(raw->s)) ? 1 : 0;\n",
        "    /* Safe cancellation only on a genuine player shutdown. */\n"
        "    return raw->s && stream_abort(raw->s) ? 1 : 0;\n",
        "do not poison producer AVIO")
    s = one(s,
        "           !__atomic_load_n(&raw->seek_preempt, __ATOMIC_ACQUIRE) &&\n"
        "           !(raw->s && raw->s->parser_interrupt) ) {",
        "           !(raw->s && raw->s->parser_interrupt) ) {",
        "parser wait (only parser interrupt)")
    s = one(s,
        "    if( __atomic_load_n(&raw->seek_preempt, __ATOMIC_ACQUIRE) ||\n"
        "        (raw->s && raw->s->parser_interrupt) ) {\n",
        "    if( raw->s && raw->s->parser_interrupt ) {\n",
        "parser wake (only parser interrupt)")
    s = one(s,
        "        if(__atomic_load_n(&raw->seek_preempt, __ATOMIC_ACQUIRE)) {\n"
        "            pthread_mutex_unlock(&raw->source_mutex);\n"
        "            av_usleep(1000);\n"
        "            continue;\n"
        "        }\n",
        "        if(__atomic_load_n(&raw->seek_pending, __ATOMIC_ACQUIRE)) {\n"
        "            /* Yield to the pending Seek without interrupting a read.\n"
        "             * Wait WITHOUT source_mutex, so the Seeker can acquire it. */\n"
        "            pthread_mutex_unlock(&raw->source_mutex);\n"
        "            pthread_mutex_lock(&raw->mutex);\n"
        "            while (__atomic_load_n(&raw->run, __ATOMIC_ACQUIRE) &&\n"
        "                   __atomic_load_n(&raw->seek_pending, __ATOMIC_ACQUIRE))\n"
        "                pthread_cond_wait(&raw->can_write, &raw->mutex);\n"
        "            pthread_mutex_unlock(&raw->mutex);\n"
        "            continue;\n"
        "        }\n",
        "cooperative producer gate")
    s = one(s,
        "        if(__atomic_load_n(&raw->seek_preempt, __ATOMIC_ACQUIRE))\n"
        "            got=AVERROR_EXIT; /* stale old-position network read */\n",
        "",
        "never discard valid old read with AVERROR_EXIT")
    s = one(s,
        "    /* Request preemption BEFORE source_mutex, not after it. */\n"
        "    __atomic_store_n(&raw->seek_preempt, 1, __ATOMIC_RELEASE);\n"
        "    if(raw->direct_transport && raw->direct_preempt_read)\n"
        "        raw->direct_preempt_read(raw->transport_generation);\n",
        "    /* NOVA_SEEK_SAFE_SERIAL_V2: prioritize the next seek by pausing\n"
        "     * future producer reads. Do not cancel the currently running\n"
        "     * libbluray/HTTP read: AVERROR_EXIT persists in AVIOContext. */\n"
        "    __atomic_store_n(&raw->seek_pending, 1, __ATOMIC_RELEASE);\n",
        "disable damaging seek preempt")
    s = one(s,
        "    /* Old I/O is quiesced. Reenable interrupts before NEW HTTP Seek. */\n"
        "    if(raw->direct_transport && raw->direct_clear_preempt)\n"
        "        raw->direct_clear_preempt(raw->transport_generation);\n"
        "    __atomic_store_n(&raw->seek_preempt, 0, __ATOMIC_RELEASE);\n",
        "    /* Existing AVIO stays valid, no interrupt state needs clearing. */\n",
        "do not send clear to transport")
    s = one(s,
        "    if(raw->direct_transport && raw->direct_clear_preempt)\n"
        "        raw->direct_clear_preempt(raw->transport_generation);\n"
        "    __atomic_store_n(&raw->seek_preempt, 0, __ATOMIC_RELEASE);\n"
        "    pthread_mutex_lock(&raw->mutex);\n"
        "    pthread_cond_broadcast(&raw->can_read);\n"
        "    pthread_cond_broadcast(&raw->can_write);\n"
        "    pthread_mutex_unlock(&raw->mutex);\n"
        "    pthread_mutex_unlock(&raw->source_mutex);\n",
        "    /* Release producer gate for BOTH successful and failed seeks.\n"
        "     * This must happen after source reposition / ring generation reset. */\n"
        "    pthread_mutex_lock(&raw->mutex);\n"
        "    __atomic_store_n(&raw->seek_pending, 0, __ATOMIC_RELEASE);\n"
        "    pthread_cond_broadcast(&raw->can_read);\n"
        "    pthread_cond_broadcast(&raw->can_write);\n"
        "    pthread_mutex_unlock(&raw->mutex);\n"
        "    serprintf(\"NOVA_SEEK_SAFE_SERIAL_V2: seek_finish target=%lld result=%lld\\n\",\n"
        "              (long long)target, (long long)result);\n"
        "    pthread_mutex_unlock(&raw->source_mutex);\n",
        "always release gate after raw seek")
    s = one(s,
        "    /* Wake parser for seek, but preempt network only on cache miss. */\n"
        "    pthread_mutex_lock(&raw->mutex);\n",
        "    /* Stop FUTURE producer reads; current AVIO must finish naturally. */\n"
        "    __atomic_store_n(&raw->seek_pending, 1, __ATOMIC_RELEASE);\n"
        "    pthread_mutex_lock(&raw->mutex);\n",
        "seek request marks pending")
    s = one(s,
        "    if (raw->direct_transport && raw->direct_clear_preempt)\n"
        "        raw->direct_clear_preempt(raw->transport_generation);\n"
        "    __atomic_store_n(&raw->seek_preempt, 0, __ATOMIC_RELEASE);\n"
        "    pthread_mutex_lock(&raw->mutex);\n",
        "    __atomic_store_n(&raw->seek_pending, 0, __ATOMIC_RELEASE);\n"
        "    pthread_mutex_lock(&raw->mutex);\n",
        "seek unpause clears pending")
    # RAW128 retained byte-window seeks do not touch source AVIO. The same
    # gate must be cleared on a cache hit; otherwise producer waits forever.
    s = one(s,
        "        raw->consumer_pos=target;\n"
        "        pthread_cond_broadcast(&raw->can_read);\n",
        "        raw->consumer_pos=target;\n"
        "        __atomic_store_n(&raw->seek_pending, 0, __ATOMIC_RELEASE);\n"
        "        pthread_cond_broadcast(&raw->can_read);\n",
        "cache-hit releases pending gate")

    # Concrete code-level safety proof: there is no call to the transport
    # interrupt export, and the upstream IO callback cannot see seek_pending.
    forbidden = (
        "raw->direct_preempt_read(raw->transport_generation)",
        "raw->direct_clear_preempt(raw->transport_generation)",
        "got=AVERROR_EXIT; /* stale old-position network read */",
        "__atomic_store_n(&raw->seek_preempt, 1,",
    )
    for item in forbidden:
        assert item not in s, "Unsafe seek preemption path remains: " + item
    assert s.count("NOVA_SEEK_SAFE_SERIAL_V2") >= 2
    assert "NOVA_RAW_CACHE_SEEK_V1" in s
    path.write_text(s)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--native",type=Path,required=True)
    ap.add_argument("--transport",type=Path,required=True)
    a=ap.parse_args()
    fix_transport(a.transport)
    fix_parser(a.native/"Source/stream_parser_ffmpeg.c")
    print("NOVA_SEEK_SAFE_SERIAL_V2=PATCHED source_avio_interrupt=STOP_ONLY")

if __name__=="__main__":
    main()
