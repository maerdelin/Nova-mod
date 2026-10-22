#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


def sub_once(text: str, pattern: str, repl: str, label: str) -> str:
    # repl is generated C source; callable replacement preserves C escapes verbatim.
    out, count = re.subn(
        pattern, lambda _match: repl, text, count=1, flags=re.M | re.S
    )
    if count != 1:
        raise RuntimeError(f"{label}: expected one regex anchor, got {count}")
    return out


RAW_SCHED = r'''
static long nova_cpu_max_freq_khz(int cpu)
{
    char path[160];
    snprintf(path, sizeof(path),
             "/sys/devices/system/cpu/cpu%d/cpufreq/cpuinfo_max_freq", cpu);
    FILE *f = fopen(path, "r");
    if( !f ) return 0;
    long khz = 0;
    if( fscanf(f, "%ld", &khz) != 1 ) khz = 0;
    fclose(f);
    return khz;
}

static void nova_pick_fast_cpus(const cpu_set_t *allowed, cpu_set_t *fast,
                                int *fast0, int *fast1)
{
    CPU_ZERO(fast);
    *fast0 = *fast1 = -1;
    long score0 = -1, score1 = -1;
    for( int cpu = 0; cpu < CPU_SETSIZE; cpu++ ) {
        if( !CPU_ISSET(cpu, allowed) ) continue;
        long score = nova_cpu_max_freq_khz(cpu);
        if( score <= 0 ) score = cpu + 1;  // deterministic fallback
        if( score > score0 || (score == score0 && cpu > *fast0) ) {
            score1 = score0; *fast1 = *fast0;
            score0 = score;  *fast0 = cpu;
        } else if( score > score1 || (score == score1 && cpu > *fast1) ) {
            score1 = score; *fast1 = cpu;
        }
    }
    if( *fast0 >= 0 ) CPU_SET(*fast0, fast);
    if( *fast1 >= 0 ) CPU_SET(*fast1, fast);
}

static void nova_raw_boost_thread(void)
{
    cpu_set_t allowed, fast, actual_mask;
    CPU_ZERO(&allowed);
    CPU_ZERO(&fast);
    CPU_ZERO(&actual_mask);
    int fast0 = -1, fast1 = -1;
    int get_aff_rc = sched_getaffinity(0, sizeof(allowed), &allowed);
    if( get_aff_rc == 0 )
        nova_pick_fast_cpus(&allowed, &fast, &fast0, &fast1);

    int affinity_rc = -1;
    int affinity_errno = 0;
    if( get_aff_rc == 0 && fast0 >= 0 ) {
        errno = 0;
        affinity_rc = sched_setaffinity(0, sizeof(fast), &fast);
        affinity_errno = affinity_rc ? errno : 0;
    }

    errno = 0;
    const int requested_nice = -8;
    int nice_rc = setpriority(PRIO_PROCESS, 0, requested_nice);
    int nice_errno = nice_rc ? errno : 0;
    errno = 0;
    int actual_nice = getpriority(PRIO_PROCESS, 0);
    int get_nice_errno = errno;
    int actual_aff_rc = sched_getaffinity(0, sizeof(actual_mask), &actual_mask);

    serprintf(
        "NOVA_RAW_SCHED: requestedNice=%d niceRc=%d niceErr=%d actualNice=%d getNiceErr=%d fastCpu0=%d fastCpu1=%d affinityRc=%d affinityErr=%d actualAffinityRc=%d\n",
        requested_nice, nice_rc, nice_errno, actual_nice, get_nice_errno,
        fast0, fast1, affinity_rc, affinity_errno, actual_aff_rc );
}
'''


RAW_PRODUCER = r'''static void *nova_raw_thread(void *opaque)
{
    NOVA_RAW_PREFETCH *raw = (NOVA_RAW_PREFETCH *)opaque;
    nova_raw_boost_thread();

    while( __atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) ) {
        int want = 0;
        int64_t write_off = 0;
        unsigned generation = 0;

        pthread_mutex_lock(&raw->mutex);
        while( __atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) &&
               (raw->eof || raw->used_bytes >= raw->capacity_bytes) ) {
            nova_raw_log_locked(raw);
            pthread_cond_wait(&raw->can_write, &raw->mutex);
        }
        if( !__atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) ) {
            pthread_mutex_unlock(&raw->mutex);
            break;
        }

        int64_t room = raw->capacity_bytes - raw->used_bytes;
        int64_t contiguous = raw->capacity_bytes - raw->write_off;
        int64_t ask = room < contiguous ? room : contiguous;
        if( ask > NOVA_RAW_IO_BYTES ) ask = NOVA_RAW_IO_BYTES;
        want = ask > 0 ? (int)ask : 0;
        write_off = raw->write_off;
        pthread_mutex_unlock(&raw->mutex);

        if( want <= 0 )
            continue;

        /*
         * Source ownership remains serialized with seek. Generation is sampled
         * after owning source_mutex so a runtime seek can never leave source
         * byte position and the 128 MiB ring generation out of sync.
         */
        pthread_mutex_lock(&raw->source_mutex);
        pthread_mutex_lock(&raw->mutex);
        generation = raw->generation;
        pthread_mutex_unlock(&raw->mutex);
        int got = avio_read(raw->source, raw->ring + write_off, want);
        pthread_mutex_unlock(&raw->source_mutex);

        pthread_mutex_lock(&raw->mutex);
        if( generation != raw->generation ) {
            pthread_mutex_unlock(&raw->mutex);
            continue;
        }

        if( got > 0 ) {
            raw->write_off += got;
            if( raw->write_off >= raw->capacity_bytes )
                raw->write_off = 0;
            raw->used_bytes += got;
            raw->produced_bytes += got;
            raw->eof = 0;
            raw->error = 0;
            __atomic_store_n(
                &raw->s->raw_prefetch_eof, 0, __ATOMIC_RELEASE );
            nova_raw_log_locked(raw);
            pthread_cond_broadcast(&raw->can_read);
            pthread_mutex_unlock(&raw->mutex);
            continue;
        }

        if( got == 0 || got == AVERROR_EOF ) {
            raw->eof = 1;
            raw->error = 0;
            __atomic_store_n(
                &raw->s->raw_prefetch_eof, 1, __ATOMIC_RELEASE );
            nova_raw_log_locked(raw);
            pthread_cond_broadcast(&raw->can_read);
            pthread_mutex_unlock(&raw->mutex);
            continue;
        }

        /*
         * A transient network read error is not a flow-control state. Below
         * 128 MiB the producer keeps trying until data resumes, a seek changes
         * generation, EOF is proven or the stream is closed.
         */
        raw->error = 0;
        serprintf(
            "NOVA_RAW_RETRY: error=%d generation=%u used=%lld capacity=%lld\n",
            got, raw->generation, (long long)raw->used_bytes,
            (long long)raw->capacity_bytes );
        pthread_mutex_unlock(&raw->mutex);
        av_usleep(50000);
    }
    return NULL;
}'''


RAW_CONSUMER = r'''static int nova_raw_read(void *opaque, uint8_t *dst, int size)
{
    NOVA_RAW_PREFETCH *raw = (NOVA_RAW_PREFETCH *)opaque;
    if( size <= 0 )
        return AVERROR(EINVAL);

    pthread_mutex_lock(&raw->mutex);
    while( __atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) &&
           raw->used_bytes == 0 && !raw->eof ) {
        pthread_cond_wait(&raw->can_read, &raw->mutex);
    }

    if( raw->used_bytes == 0 ) {
        int ret = raw->eof ? AVERROR_EOF : AVERROR_EXIT;
        pthread_mutex_unlock(&raw->mutex);
        return ret;
    }

    int copied = 0;
    while( copied < size && raw->used_bytes > 0 ) {
        int64_t contiguous = raw->capacity_bytes - raw->read_off;
        int64_t available = raw->used_bytes < contiguous ?
            raw->used_bytes : contiguous;
        int take = (int)(available < (size - copied) ?
            available : (size - copied));
        if( take <= 0 ) break;
        memcpy(dst + copied, raw->ring + raw->read_off, take);
        raw->read_off += take;
        if( raw->read_off >= raw->capacity_bytes )
            raw->read_off = 0;
        raw->used_bytes -= take;
        raw->consumed_bytes += take;
        raw->consumer_pos += take;
        copied += take;
    }

    nova_raw_log_locked(raw);
    pthread_cond_broadcast(&raw->can_write);
    pthread_mutex_unlock(&raw->mutex);
    return copied;
}'''


PLAYBACK_SCHED = r'''
static long nova_playback_cpu_max_freq_khz(int cpu)
{
    char path[160];
    snprintf(path, sizeof(path),
             "/sys/devices/system/cpu/cpu%d/cpufreq/cpuinfo_max_freq", cpu);
    FILE *f = fopen(path, "r");
    if( !f ) return 0;
    long khz = 0;
    if( fscanf(f, "%ld", &khz) != 1 ) khz = 0;
    fclose(f);
    return khz;
}

static void nova_playback_yield_sched(const char *role, int requested_nice)
{
    cpu_set_t allowed, playback;
    CPU_ZERO(&allowed);
    CPU_ZERO(&playback);
    int get_aff_rc = sched_getaffinity(0, sizeof(allowed), &allowed);

    int fast0 = -1, fast1 = -1;
    long score0 = -1, score1 = -1;
    if( get_aff_rc == 0 ) {
        for( int cpu = 0; cpu < CPU_SETSIZE; cpu++ ) {
            if( !CPU_ISSET(cpu, &allowed) ) continue;
            long score = nova_playback_cpu_max_freq_khz(cpu);
            if( score <= 0 ) score = cpu + 1;
            if( score > score0 || (score == score0 && cpu > fast0) ) {
                score1 = score0; fast1 = fast0;
                score0 = score; fast0 = cpu;
            } else if( score > score1 || (score == score1 && cpu > fast1) ) {
                score1 = score; fast1 = cpu;
            }
        }

        int count = 0;
        for( int cpu = 0; cpu < CPU_SETSIZE; cpu++ ) {
            if( !CPU_ISSET(cpu, &allowed) ) continue;
            if( cpu == fast0 || cpu == fast1 ) continue;
            CPU_SET(cpu, &playback);
            count++;
        }
        if( count > 0 )
            sched_setaffinity(0, sizeof(playback), &playback);
    }

    errno = 0;
    int nice_rc = setpriority(PRIO_PROCESS, 0, requested_nice);
    int nice_errno = nice_rc ? errno : 0;
    errno = 0;
    int actual_nice = getpriority(PRIO_PROCESS, 0);
    int get_nice_errno = errno;
    serprintf(
        "NOVA_PLAYBACK_SCHED: role=%s requestedNice=%d niceRc=%d niceErr=%d actualNice=%d getNiceErr=%d reservedFast0=%d reservedFast1=%d\n",
        role, requested_nice, nice_rc, nice_errno,
        actual_nice, get_nice_errno, fast0, fast1 );
}
'''


def patch_native(root: Path) -> dict:
    parser = root / "Source" / "stream_parser_ffmpeg.c"
    video = root / "Source" / "stream_video.c"
    p = parser.read_text()
    v = video.read_text()

    if "NOVA_AGGRESSIVE_RAW_RING" in p:
        raise RuntimeError("aggressive native patch already applied")

    p = once(
        p,
        '#include "types.h"',
        '#ifndef _GNU_SOURCE\n#define _GNU_SOURCE 1\n#endif\n#include "types.h"',
        "parser GNU feature define",
    )
    p = once(
        p,
        "#include <signal.h>\n",
        "#include <signal.h>\n#include <sched.h>\n#include <sys/resource.h>\n#include <unistd.h>\n",
        "parser scheduling includes",
    )
    p = once(
        p,
        "#define NOVA_RAW_CHUNK_BYTES          (128 * 1024)\n",
        "#define NOVA_RAW_IO_BYTES             (256 * 1024)\n#define NOVA_AGGRESSIVE_RAW_RING       1\n",
        "raw IO constant",
    )
    p = sub_once(
        p,
        r"typedef struct NOVA_RAW_CHUNK \{.*?\} NOVA_RAW_CHUNK;\n\n",
        "",
        "remove per-chunk allocation type",
    )
    p = once(
        p,
        "    NOVA_RAW_CHUNK *head;\n    NOVA_RAW_CHUNK *tail;\n",
        "    uint8_t *ring;\n    int64_t read_off;\n    int64_t write_off;\n",
        "install preallocated ring fields",
    )
    p = sub_once(
        p,
        r"static void nova_raw_free_chunks_locked\(NOVA_RAW_PREFETCH \*raw\)\n\{.*?\n\}",
        """static void nova_raw_free_chunks_locked(NOVA_RAW_PREFETCH *raw)
{
    raw->read_off = 0;
    raw->write_off = 0;
    raw->used_bytes = 0;
}""",
        "ring reset",
    )
    p = once(
        p,
        "static int nova_raw_interrupt(void *opaque)\n",
        RAW_SCHED + "\nstatic int nova_raw_interrupt(void *opaque)\n",
        "raw scheduling helpers",
    )
    p = sub_once(
        p,
        r"static void \*nova_raw_thread\(void \*opaque\)\n\{.*?\n\}\n\nstatic int nova_raw_read",
        RAW_PRODUCER + "\n\nstatic int nova_raw_read",
        "replace producer with preallocated ring producer",
    )
    p = sub_once(
        p,
        r"static int nova_raw_read\(void \*opaque, uint8_t \*dst, int size\)\n\{.*?\n\}\n\nstatic int64_t nova_raw_seek",
        RAW_CONSUMER + "\n\nstatic int64_t nova_raw_seek",
        "replace consumer with ring consumer",
    )
    p = once(
        p,
        "    can_write_ready = 1;\n\n    AVDictionary *io_options = NULL;",
        """    can_write_ready = 1;

    raw->ring = av_malloc(NOVA_RAW_FALLBACK_CAP_BYTES);
    if( !raw->ring ) {
        ret = AVERROR(ENOMEM);
        goto fail;
    }
    raw->read_off = 0;
    raw->write_off = 0;

    AVDictionary *io_options = NULL;""",
        "preallocate 128MiB raw ring",
    )
    p = p.replace("av_malloc(NOVA_RAW_CHUNK_BYTES)", "av_malloc(NOVA_RAW_IO_BYTES)")
    p = p.replace("buffer, NOVA_RAW_CHUNK_BYTES, 0, raw,", "buffer, NOVA_RAW_IO_BYTES, 0, raw,")
    p = once(
        p,
        "    if( raw->source )\n        avio_closep(&raw->source);\n    raw->enabled = 0;",
        "    if( raw->source )\n        avio_closep(&raw->source);\n    av_freep(&raw->ring);\n    raw->enabled = 0;",
        "ring fail cleanup",
    )
    p = once(
        p,
        "    if( raw->source )\n        avio_closep(&raw->source);\n\n    __atomic_store_n(&raw->s->raw_prefetch_enabled",
        "    if( raw->source )\n        avio_closep(&raw->source);\n    av_freep(&raw->ring);\n\n    __atomic_store_n(&raw->s->raw_prefetch_enabled",
        "ring close cleanup",
    )
    p = once(
        p,
        '"NOVA_RAW10X: produced=%llu consumed=%llu raw_used=%lld capacity=%lld producerBps=%llu consumerBps=%llu eof=%d\\n",',
        '"NOVA_RAW10X: produced=%llu consumed=%llu raw_used=%lld capacity=%lld producerBps=%llu consumerBps=%llu eof=%d paused=%d rebuffer=%d\\n",',
        "raw state telemetry format",
    )
    p = once(
        p,
        "        (unsigned long long)consumer_bps,\n        raw->eof );",
        "        (unsigned long long)consumer_bps,\n        raw->eof, raw->s ? raw->s->paused : -1,\n        raw->s ? __atomic_load_n(&raw->s->rebuffering, __ATOMIC_ACQUIRE) : -1 );",
        "raw state telemetry args",
    )

    v = once(
        v,
        '#include "global.h"',
        '#ifndef _GNU_SOURCE\n#define _GNU_SOURCE 1\n#endif\n#include "global.h"',
        "video GNU feature define",
    )
    v = once(
        v,
        "#include <signal.h>\n",
        "#include <signal.h>\n#include <sched.h>\n#include <sys/resource.h>\n#include <unistd.h>\n",
        "video scheduling includes",
    )
    v = once(
        v,
        "static void *_decode_thread( void *data )\n",
        PLAYBACK_SCHED + "\nstatic void *_decode_thread( void *data )\n",
        "playback scheduling helper",
    )
    v = once(
        v,
        "\tSTREAM *s = (STREAM *)data;\n\ttimeline_set_local_identity(!!(s->flags & STREAM_THUMB));\nDBGS serprintf(\"PID[%5d] decode_thread::Starting\\r\\n\", getpid() );\t\n\t\n\twhile( s->codec_run ) {",
        "\tSTREAM *s = (STREAM *)data;\n\ttimeline_set_local_identity(!!(s->flags & STREAM_THUMB));\n\tint nova_sched_done = 0;\nDBGS serprintf(\"PID[%5d] decode_thread::Starting\\r\\n\", getpid() );\t\n\t\n\twhile( s->codec_run ) {\n\t\tif( !nova_sched_done && __atomic_load_n(&s->raw_prefetch_enabled, __ATOMIC_ACQUIRE) ) {\n\t\t\tnova_playback_yield_sched(\"decode\", 8);\n\t\t\tnova_sched_done = 1;\n\t\t}",
        "decode yields to downloader",
    )
    v = once(
        v,
        "\tSTREAM *s = (STREAM *)data;\n\ttimeline_set_local_identity(!!(s->flags & STREAM_THUMB));\n\tint yield = 1;",
        "\tSTREAM *s = (STREAM *)data;\n\ttimeline_set_local_identity(!!(s->flags & STREAM_THUMB));\n\tint nova_sched_done = 0;\n\tint yield = 1;",
        "parser scheduling flag",
    )
    v = once(
        v,
        "\twhile( thread_state_get( &s->parser_tstate ) != THREAD_EXIT ) {\n\t\tthread_state_ack( &s->parser_tstate );",
        "\twhile( thread_state_get( &s->parser_tstate ) != THREAD_EXIT ) {\n\t\tif( !nova_sched_done && __atomic_load_n(&s->raw_prefetch_enabled, __ATOMIC_ACQUIRE) ) {\n\t\t\tnova_playback_yield_sched(\"parser\", 5);\n\t\t\tnova_sched_done = 1;\n\t\t}\n\t\tthread_state_ack( &s->parser_tstate );",
        "parser yields to downloader",
    )

    required = (
        "NOVA_AGGRESSIVE_RAW_RING",
        "NOVA_RAW_SCHED:",
        "nova_raw_boost_thread();",
        "raw->ring = av_malloc(NOVA_RAW_FALLBACK_CAP_BYTES)",
        "NOVA_PLAYBACK_SCHED:",
        'nova_playback_yield_sched("decode", 8)',
        'nova_playback_yield_sched("parser", 5)',
        "generation = raw->generation",
        "NOVA_RAW10X_SEEK:",
    )
    whole = p + v
    missing = [x for x in required if x not in whole]
    if missing:
        raise RuntimeError("aggressive native postcondition missing: " + repr(missing))
    if "NOVA_RAW_CHUNK *" in p or "amalloc(sizeof(NOVA_RAW_CHUNK))" in p:
        raise RuntimeError("per-read RAW allocation survived")

    parser.write_text(p)
    video.write_text(v)
    return {
        "status": "PASS",
        "raw_warehouse_bytes": 128 * 1024 * 1024,
        "raw_storage": "single preallocated ring",
        "raw_io_bytes": 256 * 1024,
        "download_nice_requested": -8,
        "playback_parser_nice": 5,
        "playback_decode_nice": 8,
        "download_cpu_policy": "two highest-frequency allowed CPUs",
        "playback_cpu_policy": "allowed CPUs excluding download fast pair when possible",
        "seek_generation_preserved": True,
    }


ISO_HELPERS = r'''
static long nova_iso_cpu_max_freq_khz(int cpu) {
    char path[160];
    snprintf(path, sizeof(path),
             "/sys/devices/system/cpu/cpu%d/cpufreq/cpuinfo_max_freq", cpu);
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    long khz = 0;
    if (fscanf(f, "%ld", &khz) != 1) khz = 0;
    fclose(f);
    return khz;
}

static void nova_iso_boost_thread(const char *role, int requested_nice) {
    cpu_set_t allowed, fast;
    CPU_ZERO(&allowed);
    CPU_ZERO(&fast);
    int fast0 = -1, fast1 = -1;
    long score0 = -1, score1 = -1;
    int get_aff_rc = sched_getaffinity(0, sizeof(allowed), &allowed);
    if (get_aff_rc == 0) {
        for (int cpu = 0; cpu < CPU_SETSIZE; cpu++) {
            if (!CPU_ISSET(cpu, &allowed)) continue;
            long score = nova_iso_cpu_max_freq_khz(cpu);
            if (score <= 0) score = cpu + 1;
            if (score > score0 || (score == score0 && cpu > fast0)) {
                score1 = score0; fast1 = fast0;
                score0 = score; fast0 = cpu;
            } else if (score > score1 || (score == score1 && cpu > fast1)) {
                score1 = score; fast1 = cpu;
            }
        }
        if (fast0 >= 0) CPU_SET(fast0, &fast);
        if (fast1 >= 0) CPU_SET(fast1, &fast);
    }

    int affinity_rc = -1, affinity_errno = 0;
    if (get_aff_rc == 0 && fast0 >= 0) {
        errno = 0;
        affinity_rc = sched_setaffinity(0, sizeof(fast), &fast);
        affinity_errno = affinity_rc ? errno : 0;
    }

    errno = 0;
    int nice_rc = setpriority(PRIO_PROCESS, 0, requested_nice);
    int nice_errno = nice_rc ? errno : 0;
    errno = 0;
    int actual_nice = getpriority(PRIO_PROCESS, 0);
    int get_nice_errno = errno;
    LOGI("IO_SCHED role=%s requestedNice=%d niceRc=%d niceErr=%d actualNice=%d getNiceErr=%d fastCpu0=%d fastCpu1=%d affinityRc=%d affinityErr=%d",
         role, requested_nice, nice_rc, nice_errno, actual_nice,
         get_nice_errno, fast0, fast1, affinity_rc, affinity_errno);
}
'''


ISO_PREFETCH = r'''
typedef struct {
    iso_input *in;
    int worker;
} iso_prefetch_task;

static iso_cache_slot *cache_find_any_locked(iso_input *in, int64_t aligned) {
    for (int i = 0; i < CACHE_SLOTS; i++) {
        iso_cache_slot *slot = &in->cache[i];
        if (slot->state != ISO_CACHE_EMPTY && slot->start == aligned)
            return slot;
    }
    return NULL;
}

static iso_cache_slot *cache_reserve_locked(iso_input *in, int64_t aligned) {
    iso_cache_slot *existing = cache_find_any_locked(in, aligned);
    if (existing) return existing;

    iso_cache_slot *victim = NULL;
    for (int i = 0; i < CACHE_SLOTS; i++) {
        iso_cache_slot *slot = &in->cache[i];
        if (slot->state == ISO_CACHE_EMPTY) {
            victim = slot;
            break;
        }
        if (slot->state == ISO_CACHE_READY &&
            (!victim || slot->last_use < victim->last_use))
            victim = slot;
    }
    if (!victim) return NULL;

    victim->start = aligned;
    victim->len = 0;
    victim->generation = in->prefetch_generation;
    victim->state = ISO_CACHE_QUEUED;
    victim->last_use = ++in->cache_clock;
    return victim;
}

static void cache_schedule_window_locked(iso_input *in, int64_t byte_pos) {
    int64_t aligned = (byte_pos / CACHE_BYTES) * CACHE_BYTES;
    if (in->prefetch_focus < 0 ||
        llabs(aligned - in->prefetch_focus) >
            (int64_t)CACHE_BYTES * CACHE_SLOTS * 2) {
        in->prefetch_generation++;
        for (int i = 0; i < CACHE_SLOTS; i++) {
            if (in->cache[i].state == ISO_CACHE_QUEUED)
                in->cache[i].state = ISO_CACHE_EMPTY;
        }
        LOGI("PREFETCH_RECENTER generation=%" PRIu64 " aligned=%" PRId64,
             in->prefetch_generation, aligned);
    }
    in->prefetch_focus = aligned;

    for (int i = 0; i < CACHE_SLOTS; i++) {
        int64_t pos = aligned + (int64_t)i * CACHE_BYTES;
        cache_reserve_locked(in, pos);
    }
    pthread_cond_broadcast(&in->prefetch_cond);
}

static void *iso_prefetch_worker(void *opaque) {
    iso_prefetch_task *task = (iso_prefetch_task *)opaque;
    iso_input *in = task->in;
    int worker = task->worker;
    free(task);
    nova_iso_boost_thread("iso-range", -8);

    while (1) {
        pthread_mutex_lock(&in->lock);
        iso_cache_slot *slot = NULL;
        while (in->prefetch_run && !slot) {
            for (int i = 0; i < CACHE_SLOTS; i++) {
                if (in->cache[i].state == ISO_CACHE_QUEUED) {
                    slot = &in->cache[i];
                    slot->state = ISO_CACHE_ACTIVE;
                    break;
                }
            }
            if (!slot)
                pthread_cond_wait(&in->prefetch_cond, &in->lock);
        }
        if (!in->prefetch_run) {
            pthread_mutex_unlock(&in->lock);
            break;
        }

        int64_t start = slot->start;
        uint64_t generation = slot->generation;
        pthread_mutex_unlock(&in->lock);

        int64_t t0 = mono_ms();
        LOGI("PREFETCH_BEGIN worker=%d generation=%" PRIu64 " start=%" PRId64,
             worker, generation, start);
        ssize_t got = fetch_range(in, start, CACHE_BYTES, slot->data);

        pthread_mutex_lock(&in->lock);
        if (slot->state == ISO_CACHE_ACTIVE &&
            slot->start == start &&
            slot->generation == generation &&
            generation == in->prefetch_generation &&
            got >= UDF_BLOCK) {
            slot->len = (size_t)got;
            slot->state = ISO_CACHE_READY;
            slot->last_use = ++in->cache_clock;
            LOGI("PREFETCH_READY worker=%d generation=%" PRIu64
                 " start=%" PRId64 " got=%zd ms=%" PRId64,
                 worker, generation, start, got, mono_ms() - t0);
        } else if (slot->state == ISO_CACHE_ACTIVE &&
                   slot->start == start &&
                   slot->generation == generation) {
            slot->len = 0;
            slot->state = ISO_CACHE_EMPTY;
            LOGI("PREFETCH_DISCARD worker=%d generation=%" PRIu64
                 " currentGeneration=%" PRIu64 " start=%" PRId64 " got=%zd",
                 worker, generation, in->prefetch_generation, start, got);
        }
        pthread_cond_broadcast(&in->prefetch_cond);
        pthread_mutex_unlock(&in->lock);

        if (got < UDF_BLOCK)
            usleep(50000);
    }

    LOGI("PREFETCH_WORKER_EXIT worker=%d", worker);
    return NULL;
}

static void reset_iso_prefetch_for_seek(iso_input *in) {
    pthread_mutex_lock(&in->lock);
    in->prefetch_generation++;
    in->prefetch_focus = -1;
    for (int i = 0; i < CACHE_SLOTS; i++) {
        iso_cache_slot *slot = &in->cache[i];
        if (slot->state != ISO_CACHE_ACTIVE) {
            slot->state = ISO_CACHE_EMPTY;
            slot->len = 0;
        }
    }
    LOGI("PREFETCH_SEEK_RESET generation=%" PRIu64, in->prefetch_generation);
    pthread_cond_broadcast(&in->prefetch_cond);
    pthread_mutex_unlock(&in->lock);
}

static int start_iso_prefetch(iso_input *in) {
    if (pthread_cond_init(&in->prefetch_cond, NULL) != 0)
        return -1;
    in->prefetch_cond_ready = 1;
    in->prefetch_run = 1;
    in->prefetch_generation = 1;
    in->prefetch_focus = -1;

    for (int i = 0; i < CACHE_SLOTS; i++) {
        if (!in->cache[i].data) {
            in->cache[i].data = malloc(CACHE_BYTES);
            if (!in->cache[i].data) return -1;
        }
        in->cache[i].state =
            in->cache[i].len >= UDF_BLOCK ? ISO_CACHE_READY : ISO_CACHE_EMPTY;
    }

    for (int i = 0; i < PREFETCH_WORKERS; i++) {
        iso_prefetch_task *task = calloc(1, sizeof(*task));
        if (!task) return -1;
        task->in = in;
        task->worker = i;
        if (pthread_create(&in->prefetch_threads[i], NULL,
                           iso_prefetch_worker, task) != 0) {
            free(task);
            return -1;
        }
        in->prefetch_started[i] = 1;
    }
    LOGI("PREFETCH_START workers=%d cacheBytes=%d slots=%d inFlightMax=%d",
         PREFETCH_WORKERS, CACHE_BYTES, CACHE_SLOTS,
         PREFETCH_WORKERS * CACHE_BYTES);
    return 0;
}

static void stop_iso_prefetch(iso_input *in) {
    if (!in->prefetch_cond_ready) return;
    pthread_mutex_lock(&in->lock);
    in->prefetch_run = 0;
    pthread_cond_broadcast(&in->prefetch_cond);
    pthread_mutex_unlock(&in->lock);
    for (int i = 0; i < PREFETCH_WORKERS; i++) {
        if (in->prefetch_started[i]) {
            pthread_join(in->prefetch_threads[i], NULL);
            in->prefetch_started[i] = 0;
        }
    }
    pthread_cond_destroy(&in->prefetch_cond);
    in->prefetch_cond_ready = 0;
}
'''


def patch_iso(path: Path) -> dict:
    text = path.read_text()
    if "PREFETCH_WORKERS" in text:
        raise RuntimeError("aggressive ISO patch already applied")

    text = once(
        text,
        "#define _GNU_SOURCE\n",
        "#define _GNU_SOURCE\n",
        "ISO GNU feature define",
    )
    text = once(
        text,
        "#include <sys/types.h>\n",
        "#include <sys/types.h>\n#include <sched.h>\n#include <sys/resource.h>\n",
        "ISO scheduling includes",
    )
    text = once(
        text,
        "    if (fd < 0) return -1;\n    struct sockaddr_in sa;",
        "    if (fd < 0) return -1;\n"
        "    int nova_sockbuf = 4 * 1024 * 1024;\n"
        "    setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &nova_sockbuf, sizeof(nova_sockbuf));\n"
        "    setsockopt(fd, SOL_SOCKET, SO_SNDBUF, &nova_sockbuf, sizeof(nova_sockbuf));\n"
        "    struct sockaddr_in sa;",
        "ISO loopback socket buffers",
    )
    text = once(
        text,
        "#define HEADER_MAX 32768\n",
        "#define HEADER_MAX 32768\n#define PREFETCH_WORKERS 4\n"
        "#define ISO_CACHE_EMPTY 0\n#define ISO_CACHE_QUEUED 1\n"
        "#define ISO_CACHE_ACTIVE 2\n#define ISO_CACHE_READY 3\n",
        "ISO prefetch constants",
    )
    text = once(
        text,
        "    uint64_t last_use;\n} iso_cache_slot;",
        "    uint64_t last_use;\n    uint64_t generation;\n    int state;\n} iso_cache_slot;",
        "ISO cache slot state",
    )
    text = once(
        text,
        "    pthread_mutex_t lock;\n} iso_input;",
        "    pthread_mutex_t lock;\n"
        "    pthread_cond_t prefetch_cond;\n"
        "    int prefetch_cond_ready;\n"
        "    volatile int prefetch_run;\n"
        "    pthread_t prefetch_threads[PREFETCH_WORKERS];\n"
        "    int prefetch_started[PREFETCH_WORKERS];\n"
        "    uint64_t prefetch_generation;\n"
        "    int64_t prefetch_focus;\n"
        "} iso_input;",
        "ISO prefetch state",
    )
    text = once(
        text,
        "static int64_t mono_ms(void) {",
        ISO_HELPERS + "\nstatic int64_t mono_ms(void) {",
        "ISO scheduling helper",
    )
    text = once(
        text,
        "    uint64_t req_id = ++in->range_requests;",
        "    uint64_t req_id = __atomic_add_fetch(&in->range_requests, 1, __ATOMIC_RELAXED);",
        "atomic range request counter",
    )
    text = once(
        text,
        "    in->fetched_bytes += copied;\n    LOGI(\"RANGE_END id=%\" PRIu64 \" start=%\" PRId64 \" got=%zu ms=%\" PRId64 \" totalFetched=%\" PRIu64,\n         req_id, start, copied, mono_ms() - t0, in->fetched_bytes);",
        "    uint64_t total_fetched = __atomic_add_fetch(\n"
        "        &in->fetched_bytes, copied, __ATOMIC_RELAXED);\n"
        "    LOGI(\"RANGE_END id=%\" PRIu64 \" start=%\" PRId64 \" got=%zu ms=%\" PRId64 \" totalFetched=%\" PRIu64,\n"
        "         req_id, start, copied, mono_ms() - t0, total_fetched);",
        "atomic fetched byte counter",
    )
    text = once(
        text,
        "        if (slot->data && slot->len > 0 &&\n",
        "        if (slot->state == ISO_CACHE_READY && slot->data && slot->len > 0 &&\n",
        "cache reads only ready slots",
    )
    text = sub_once(
        text,
        r"static iso_cache_slot \*cache_victim\(iso_input \*in\) \{.*?\n\}",
        """static iso_cache_slot *cache_victim(iso_input *in) {
    iso_cache_slot *victim = NULL;
    for (int i = 0; i < CACHE_SLOTS; i++) {
        iso_cache_slot *slot = &in->cache[i];
        if (slot->state == ISO_CACHE_EMPTY) return slot;
        if (slot->state == ISO_CACHE_READY &&
            (!victim || slot->last_use < victim->last_use))
            victim = slot;
    }
    return victim;
}""",
        "cache victim ignores in-flight slots",
    )
    text = once(
        text,
        "    iso_cache_slot *slot = cache_victim(in);\n    if (!slot->data) {",
        "    iso_cache_slot *slot = cache_victim(in);\n    if (!slot) return -1;\n    if (!slot->data) {",
        "sync cache victim nullable",
    )
    text = once(
        text,
        "    slot->start = aligned;\n    slot->len = (size_t)got;\n    slot->last_use = ++in->cache_clock;",
        "    slot->start = aligned;\n    slot->len = (size_t)got;\n"
        "    slot->generation = in->prefetch_generation;\n"
        "    slot->state = ISO_CACHE_READY;\n"
        "    slot->last_use = ++in->cache_clock;",
        "sync cache fill state",
    )
    text = once(
        text,
        "static int iso_read_blocks(void *handle, void *buf, int lba, int num_blocks) {",
        ISO_PREFETCH + "\nstatic int iso_read_blocks(void *handle, void *buf, int lba, int num_blocks) {",
        "ISO async prefetch implementation",
    )
    text = sub_once(
        text,
        r"static int iso_read_blocks\(void \*handle, void \*buf, int lba, int num_blocks\) \{.*?\n\}\n\nstatic int read_request",
        r'''static int iso_read_blocks(void *handle, void *buf, int lba, int num_blocks) {
    iso_input *in = (iso_input *)handle;
    if (!in || !buf || lba < 0 || num_blocks <= 0) return -1;

    pthread_mutex_lock(&in->lock);
    uint8_t *dst = (uint8_t *)buf;
    int done = 0;

    while (done < num_blocks) {
        int64_t byte_pos = (int64_t)(lba + done) * UDF_BLOCK;
        iso_cache_slot *slot = cache_find(in, byte_pos);

        if (!slot && !in->playback_mode) {
            if (cache_fill(in, byte_pos, &slot) < 0) break;
        } else if (!slot) {
            while (in->prefetch_run && !(slot = cache_find(in, byte_pos))) {
                cache_schedule_window_locked(in, byte_pos);
                pthread_cond_wait(&in->prefetch_cond, &in->lock);
            }
            if (!slot) break;
        }

        size_t off = (size_t)(byte_pos - slot->start);
        size_t avail = slot->len - off;
        int blocks = (int)(avail / UDF_BLOCK);
        int need = num_blocks - done;
        if (blocks > need) blocks = need;
        if (blocks <= 0) break;

        memcpy(dst + (size_t)done * UDF_BLOCK,
               slot->data + off,
               (size_t)blocks * UDF_BLOCK);
        done += blocks;

        if (in->playback_mode)
            cache_schedule_window_locked(in, byte_pos + (int64_t)blocks * UDF_BLOCK);
    }

    pthread_mutex_unlock(&in->lock);
    return done > 0 ? done : -1;
}

static int read_request''',
        "async ISO read path",
    )
    text = once(
        text,
        "static void *client_main(void *opaque) {\n    client_task *task = (client_task *)opaque;",
        "static void *client_main(void *opaque) {\n"
        "    nova_iso_boost_thread(\"iso-title\", -4);\n"
        "    client_task *task = (client_task *)opaque;",
        "title server scheduling",
    )
    text = once(
        text,
        "    LOGI(\"PLAYER_SEEK_BEGIN start=%\" PRIu64, start);\n"
        "    if (seek_exact(s->bd, start) < 0) {",
        "    LOGI(\"PLAYER_SEEK_BEGIN start=%\" PRIu64, start);\n"
        "    reset_iso_prefetch_for_seek(&s->input);\n"
        "    if (seek_exact(s->bd, start) < 0) {",
        "ISO prefetch seek generation reset",
    )
    text = once(
        text,
        "    s->input.playback_mode = 1;\n    LOGI(\"CACHE_MODE playback persistent_range=1 window=%d slots=%d\", CACHE_BYTES, CACHE_SLOTS);",
        "    s->input.playback_mode = 1;\n"
        "    if (start_iso_prefetch(&s->input) < 0) {\n"
        "        LOGE(\"PREFETCH_START_FAIL\");\n"
        "        session_destroy(s);\n"
        "        return NULL;\n"
        "    }\n"
        "    LOGI(\"CACHE_MODE playback parallel_range=1 window=%d slots=%d workers=%d\", CACHE_BYTES, CACHE_SLOTS, PREFETCH_WORKERS);",
        "start aggressive ISO prefetch",
    )
    text = once(
        text,
        "    if (s->thread_started) pthread_join(s->thread, NULL);\n    close_playback_stream(&s->input);",
        "    if (s->thread_started) pthread_join(s->thread, NULL);\n"
        "    stop_iso_prefetch(&s->input);\n"
        "    close_playback_stream(&s->input);",
        "stop aggressive ISO prefetch",
    )

    required = (
        "#define PREFETCH_WORKERS 4",
        "PREFETCH_START workers=%d",
        'nova_iso_boost_thread("iso-range", -8)',
        'nova_iso_boost_thread("iso-title", -4)',
        "cache_schedule_window_locked",
        "ISO_CACHE_ACTIVE",
        "prefetch_generation",
    )
    missing = [x for x in required if x not in text]
    if missing:
        raise RuntimeError("aggressive ISO postcondition missing: " + repr(missing))

    path.write_text(text)
    return {
        "status": "PASS",
        "range_workers": 4,
        "range_bytes_each": 4 * 1024 * 1024,
        "max_simultaneous_range_bytes": 16 * 1024 * 1024,
        "cache_bytes_existing_ceiling": 8 * 4 * 1024 * 1024,
        "cache_preallocated_before_playback": True,
        "range_worker_nice_requested": -8,
        "title_thread_nice_requested": -4,
        "cpu_policy": "two highest-frequency allowed CPUs",
        "generation_discard_on_recenter": True,
        "generation_reset_on_title_seek": True,
        "loopback_socket_buffer_bytes_requested": 4 * 1024 * 1024,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--native", type=Path)
    g.add_argument("--iso", type=Path)
    p.add_argument("--report", type=Path)
    a = p.parse_args()

    if a.native:
        result = patch_native(a.native)
    else:
        result = patch_iso(a.iso)

    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
