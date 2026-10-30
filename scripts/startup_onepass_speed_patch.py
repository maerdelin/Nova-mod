#!/usr/bin/env python3
"""NOVA_STARTUP_ONEPASS_V1: FILE-only probe relocation scheduling.
Applied after the pinned AVOS/Shared42/boot tracing patches, before native build.
No buffering, post-probe policy, logical seek, or ISO path changes.
"""
import argparse
from pathlib import Path

def once(s, old, new, label):
    n = s.count(old)
    if n != 1:
        raise RuntimeError(f"STARTUP_ONEPASS {label}: expected 1 anchor, got {n}")
    return s.replace(old, new, 1)

def apply(root):
    p = root / "Source" / "stream_parser_ffmpeg.c"
    s = p.read_text()
    if "NOVA_STARTUP_ONEPASS_V1" in s:
        raise RuntimeError("STARTUP_ONEPASS already installed")
    s = once(s,
        "    unsigned nova_boot_consumer_calls;\n",
        "    unsigned nova_boot_consumer_calls;\n"
        "    /* NOVA_STARTUP_ONEPASS_V1: FILE probe relocation, never ISO. */\n"
        "    volatile int startup_probe_active;\n"
        "    unsigned startup_reloc_pending; /* under raw->mutex */\n"
        "    int (*startup_probe_hint)(uint64_t,int);\n",
        "RAW startup fields")
    s = once(s,
        '    if (!raw->direct_read || !raw->direct_seek ||\n'
        '        !raw->direct_size || !raw->direct_abort || !raw->direct_set_target_bps)\n'
        '        return AVERROR(ENOSYS);\n',
        '    if (!raw->direct_read || !raw->direct_seek ||\n'
        '        !raw->direct_size || !raw->direct_abort || !raw->direct_set_target_bps)\n'
        '        return AVERROR(ENOSYS);\n'
        '    raw->startup_probe_hint=(int (*)(uint64_t,int))dlsym(\n'
        '        raw->transport_handle,"nova_transport_startup_probe_hint");\n'
        '    if(!raw->startup_probe_hint)return AVERROR(ENOSYS);\n',
        "direct transport hint ABI")
    s = once(s,
        "    ret = pthread_create(&raw->thread, NULL, nova_raw_thread, raw);\n",
        "    /* Only non-ISO direct FILE sources use the startup relocation gate. */\n"
        "    __atomic_store_n(&raw->startup_probe_active,\n"
        "        raw->direct_transport && raw->source && raw->source->direct,\n"
        "        __ATOMIC_RELEASE);\n"
        "    ret = pthread_create(&raw->thread, NULL, nova_raw_thread, raw);\n",
        "mark pre-probe RAW startup")
    s = once(s,
        "        pthread_mutex_lock(&raw->source_mutex);\n"
        "        pthread_mutex_lock(&raw->mutex);\n"
        "        if( !__atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) ||\n"
        "            raw->eof || raw->used_bytes >= raw->capacity_bytes ) {\n",
        "        /* Relocation gets first access to the shared AVIO source.\n"
        "         * Never race a network read with a seek or move RAW pages\n"
        "         * across generations. The cond wait releases raw->mutex. */\n"
        "        pthread_mutex_lock(&raw->mutex);\n"
        "        while(raw->startup_reloc_pending &&\n"
        "              __atomic_load_n(&raw->run,__ATOMIC_ACQUIRE))\n"
        "            pthread_cond_wait(&raw->can_write,&raw->mutex);\n"
        "        pthread_mutex_unlock(&raw->mutex);\n"
        "        pthread_mutex_lock(&raw->source_mutex);\n"
        "        pthread_mutex_lock(&raw->mutex);\n"
        "        if( raw->startup_reloc_pending ||\n"
        "            !__atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) ||\n"
        "            raw->eof || raw->used_bytes >= raw->capacity_bytes ) {\n",
        "producer gives relocation priority")
    s = once(s,
        "        pthread_mutex_lock(&raw->mutex);\n"
        "        if( generation != raw->generation ) {\n",
        "        pthread_mutex_lock(&raw->mutex);\n"
        "        /* The transport returned a deliberate probe read cancellation.\n"
        "         * A pending relocation will establish a fresh source epoch;\n"
        "         * do not latch EIO/EOF or commit a stale shared page. */\n"
        "        if(got==AVERROR(EINTR) && raw->startup_reloc_pending){\n"
        "            pthread_mutex_unlock(&raw->mutex);\n"
        "            continue;\n"
        "        }\n"
        "        if( generation != raw->generation ) {\n",
        "nonfatal preempt result")
    s = once(s,
        "    int64_t nova_boot_seek_lock_begin=av_gettime_relative();\n"
        "    pthread_mutex_lock(&raw->source_mutex);\n"
        "    int64_t nova_boot_seek_lock_ms=(av_gettime_relative()-nova_boot_seek_lock_begin)/1000;\n",
        "    int64_t nova_boot_seek_lock_begin=av_gettime_relative();\n"
        "    pthread_mutex_lock(&raw->source_mutex);\n"
        "    int64_t nova_boot_seek_lock_ms=(av_gettime_relative()-nova_boot_seek_lock_begin)/1000;\n"
        "    if(startup_relocating)\n"
        "        raw->startup_probe_hint(raw->transport_generation,0);\n",
        "seek priority and in-flight read cancellation")
    s = once(s,
        "    pthread_mutex_unlock(&raw->source_mutex);\n"
        "    return result;\n}\n\nstatic void nova_raw_stats",
        "    pthread_mutex_unlock(&raw->source_mutex);\n"
        "    if(startup_relocating){\n"
        "        pthread_mutex_lock(&raw->mutex);\n"
        "        raw->startup_reloc_pending--;\n"
        "        pthread_cond_broadcast(&raw->can_write);\n"
        "        pthread_mutex_unlock(&raw->mutex);\n"
        "    }\n"
        "    return result;\n}\n\nstatic void nova_raw_stats",
        "release seek priority")
    # The parser is the owner of startup-probe completion, unlike the media
    # Prepared callback. Do not leave a guard active during normal playback.
    trace = [ln for ln in s.splitlines(keepends=True)
             if 'serprintf("NOVA_STARTUP_TRACE probe_done ' in ln]
    if len(trace)!=1:
        raise RuntimeError(f"STARTUP_ONEPASS probe_done marker count={len(trace)}")
    s = once(s, trace[0],
        "    __atomic_store_n(&ff_p->raw.startup_probe_active,0,__ATOMIC_RELEASE);\n"
        + trace[0], "end RAW startup scope")
    p.write_text(s)
    print("NOVA_STARTUP_ONEPASS_RAW=PASS")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--native",required=True,type=Path)
    args=ap.parse_args()
    apply(args.native)

if __name__=="__main__":
    main()
