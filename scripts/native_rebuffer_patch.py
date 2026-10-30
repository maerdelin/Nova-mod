#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

EXPECTED_AVOS_COMMIT = "b313441df14414632781617742efb66778689b91"
LOW_BYTES = 24 * 1024 * 1024
RESUME_BYTES = 64 * 1024 * 1024
CAPACITY_BYTES = 128 * 1024 * 1024
POLL_MS = 50


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


def sub_once(text: str, pattern: str, repl, label: str) -> str:
    out, count = re.subn(pattern, repl, text, count=1, flags=re.M | re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected one regex anchor, got {count}")
    return out


def check_head(root: Path, allow_unpinned_head: bool = False) -> str:
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != EXPECTED_AVOS_COMMIT and not allow_unpinned_head:
        raise RuntimeError(
            f"aos-avos commit mismatch: expected {EXPECTED_AVOS_COMMIT}, got {head}"
        )
    if head != EXPECTED_AVOS_COMMIT:
        required = (
            root / "Include" / "stream.h",
            root / "Source" / "stream_video.c",
            root / "Source" / "stream.c",
            root / "Source" / "avos_mp_video.c",
            root / "Source" / "stream_parser_ffmpeg.c",
        )
        missing = [str(p.relative_to(root)) for p in required if not p.is_file()]
        if missing:
            raise RuntimeError(
                "unpinned aos-avos source is missing required files: " + ", ".join(missing)
            )
    return head


REBUFFER_THREAD = r'''
// *****************************************************************************
//
//  Raw-source buffering controller
//
//  The pre-demux raw producer has one fixed 128 MiB warehouse wall. 1.5X/3X
//  are playback pause/resume thresholds only. They never throttle, pause or
//  accelerate network production. As long as RAW used bytes are below 128 MiB,
//  the producer keeps pulling regardless of play/pause/rebuffer/decoder state.
//
// *****************************************************************************
static int _nova_rebuffer_eof( STREAM *s )
{
    int audio_done = !s->audio->valid || s->audio_parse_end;
    int video_done = !s->video->valid || s->video_parse_end;
    return audio_done && video_done;
}

static void *_rebuffer_thread( void *data )
{
    STREAM *s = (STREAM *)data;
    int last_wait_log = 0;

    DBGS serprintf("PID[%5d] raw_rebuffer_thread::Starting\r\n", getpid());

    while( thread_state_get( &s->rebuffer_tstate ) != THREAD_EXIT ) {
        thread_state_ack( &s->rebuffer_tstate );

        if( thread_state_get( &s->rebuffer_tstate ) == THREAD_RUNNING ) {
            if( __atomic_load_n( &s->raw_prefetch_enabled, __ATOMIC_ACQUIRE ) &&
                !s->seek && !s->seek_paused && !s->paused_internal &&
                s->parser && s->parser->get_stats ) {
                STREAM_PARSER_STATS stats;
                STREAM_PARSER_STATS *pst = s->parser->get_stats( s, &stats );

                if( pst && pst->buffer2_size == s->rebuffer_capacity_bytes &&
                    s->rebuffer_low_bytes > 0 && s->rebuffer_resume_bytes > 0 ) {
                    int64_t resident64 = (int64_t)pst->buffer_used +
                                         (int64_t)pst->buffer2_used;
                    int resident = resident64 > INT_MAX ? INT_MAX : (int)resident64;
                    int raw_used = pst->buffer2_used;
                    int packet_used = pst->buffer_used;
                    int parsed_eof = _nova_rebuffer_eof( s );
                    int source_eof = __atomic_load_n(
                        &s->raw_prefetch_eof, __ATOMIC_ACQUIRE );
                    int active = __atomic_load_n(
                        &s->rebuffering, __ATOMIC_ACQUIRE );

                    if( !active ) {
                        int play_requested = __atomic_load_n(
                            &s->rebuffer_play_requested, __ATOMIC_ACQUIRE );
                        int frame_seen = __atomic_load_n(
                            &s->rebuffer_frame_seen, __ATOMIC_ACQUIRE );

                        if( play_requested && frame_seen &&
                            !s->paused && !s->stream_end &&
                            s->video_error == VE_NO_ERROR &&
                            !parsed_eof && !source_eof &&
                            resident < s->rebuffer_low_bytes ) {
                            __atomic_store_n(
                                &s->rebuffering, 1, __ATOMIC_RELEASE );
                            __atomic_store_n(
                                &s->rebuffer_user_paused, 0, __ATOMIC_RELEASE );

                            int was_paused = stream_pause( s );
                            if( was_paused ) {
                                __atomic_store_n(
                                    &s->rebuffering, 0, __ATOMIC_RELEASE );
                            } else {
                                last_wait_log = atime();
                                serprintf(
                                    "NOVA_REBUFFER_ENTER: resident=%d raw=%d packet=%d low=%d resume=%d raw_cap=%d\n",
                                    resident, raw_used, packet_used,
                                    s->rebuffer_low_bytes,
                                    s->rebuffer_resume_bytes,
                                    s->rebuffer_capacity_bytes );
                                if( s->message_cb )
                                    s->message_cb( s, STREAM_BUFFERING_START );
                            }
                        }
                    } else {
                        int user_paused = __atomic_load_n(
                            &s->rebuffer_user_paused, __ATOMIC_ACQUIRE );
                        int now = atime();
                        if( now - last_wait_log >= 1000 ) {
                            last_wait_log = now;
                            serprintf(
                                "NOVA_REBUFFER_WAIT: resident=%d raw=%d packet=%d resume=%d raw_cap=%d source_eof=%d user_paused=%d\n",
                                resident, raw_used, packet_used,
                                s->rebuffer_resume_bytes,
                                s->rebuffer_capacity_bytes,
                                source_eof, user_paused );
                        }

                        if( source_eof || parsed_eof || s->stream_end ||
                            s->video_error != VE_NO_ERROR ||
                            resident >= s->rebuffer_resume_bytes ) {
                            const char *reason =
                                s->video_error != VE_NO_ERROR ? "error" :
                                (source_eof || parsed_eof || s->stream_end) ?
                                    "eof" : "threshold";

                            serprintf(
                                "NOVA_REBUFFER_EXIT: resident=%d raw=%d packet=%d reason=%s user_paused=%d\n",
                                resident, raw_used, packet_used,
                                reason, user_paused );
                            if( s->message_cb )
                                s->message_cb( s, STREAM_BUFFERING_END );

                            if( !user_paused )
                                stream_un_pause( s, 0 );

                            __atomic_store_n(
                                &s->rebuffer_user_paused, 0, __ATOMIC_RELEASE );
                            __atomic_store_n(
                                &s->rebuffering, 0, __ATOMIC_RELEASE );
                        }
                    }
                }
            }
        }

        msec_sleep( NOVA_REBUFFER_POLL_MS );
    }

    DBGS serprintf("PID[%5d] raw_rebuffer_thread::Exiting\r\n", getpid());
    return NULL;
}
'''


RAW_TYPES = r'''
#define NOVA_RAW_IO_BYTES             (128 * 1024)
#define NOVA_RAW_FALLBACK_LOW_BYTES   (24 * 1024 * 1024)
#define NOVA_RAW_FALLBACK_RESUME_BYTES (64 * 1024 * 1024)
#define NOVA_RAW_FALLBACK_CAP_BYTES   (128 * 1024 * 1024)

typedef struct NOVA_RAW_PREFETCH {
    STREAM *s;
    AVIOContext *source;
    AVIOContext *consumer;
    AVIOInterruptCB upstream_interrupt;
    pthread_t thread;
    pthread_mutex_t mutex;
    pthread_mutex_t source_mutex;
    pthread_cond_t can_read;
    pthread_cond_t can_write;
    uint8_t *ring;
    int64_t read_off;
    int64_t write_off;
    volatile int run;
    int enabled;
    int thread_started;
    int eof;
    int error;
    unsigned generation;
    int64_t used_bytes;
    int64_t capacity_bytes;
    int64_t low_bytes;
    int64_t resume_bytes;
    int64_t consumer_pos;
    int64_t source_size;
    uint64_t produced_bytes;
    uint64_t consumed_bytes;
    uint64_t last_log_produced;
    uint64_t last_log_consumed;
    int64_t last_log_us;
    unsigned nova_boot_producer_calls;
    unsigned nova_boot_consumer_calls;
    /* NOVA_MKV_BBC_SEEK_GUARD_V1: only MKV one-GET source. */
    int mkv_single_get;
    volatile int mkv_seek_active;
    volatile int mkv_seek_failed;
    int64_t mkv_seek_started_us;
    uint64_t mkv_seek_bytes;
} NOVA_RAW_PREFETCH;
'''


RAW_CODE = r'''

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
    /* Run584 policy: inherit ordinary OS priority and CPU affinity.
     * No explicit setpriority/sched_setaffinity of transport producer. */
}
static int nova_raw_interrupt(void *opaque)
{
    NOVA_RAW_PREFETCH *raw = (NOVA_RAW_PREFETCH *)opaque;
    if( !raw || !__atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) )
        return 1;

    /*
     * The demux parser deliberately raises s->parser_interrupt while parking
     * its own av_read_frame() thread for a runtime seek. The RAW producer is a
     * separate network owner and must NOT inherit that parser-only interrupt:
     * doing so turns a normal seek into AVERROR_EXIT ("Immediate exit
     * requested"), poisons raw->error and makes the seek fail before the RAW
     * source can reposition. Only a real player/user abort may interrupt this
     * upstream AVIO.
     */
    return raw->s && stream_abort(raw->s) ? 1 : 0;
}

static void nova_raw_reset_locked(NOVA_RAW_PREFETCH *raw)
{
    raw->read_off = 0;
    raw->write_off = 0;
    raw->used_bytes = 0;
}

static void nova_raw_log_locked(NOVA_RAW_PREFETCH *raw)
{
    int64_t now = av_gettime_relative();
    if( raw->last_log_us && now - raw->last_log_us < 1000000 )
        return;
    if( !raw->last_log_us ) {
        raw->last_log_us = now;
        raw->last_log_produced = raw->produced_bytes;
        raw->last_log_consumed = raw->consumed_bytes;
        return;
    }
    int64_t elapsed = now - raw->last_log_us;
    uint64_t produced_delta = raw->produced_bytes - raw->last_log_produced;
    uint64_t consumed_delta = raw->consumed_bytes - raw->last_log_consumed;
    uint64_t producer_bps = elapsed > 0 ?
        produced_delta * 1000000ULL / (uint64_t)elapsed : 0;
    uint64_t consumer_bps = elapsed > 0 ?
        consumed_delta * 1000000ULL / (uint64_t)elapsed : 0;
    serprintf(
        "NOVA_RAW128: produced=%llu consumed=%llu raw_used=%lld capacity=%lld producerBps=%llu consumerBps=%llu eof=%d\n",
        (unsigned long long)raw->produced_bytes,
        (unsigned long long)raw->consumed_bytes,
        (long long)raw->used_bytes,
        (long long)raw->capacity_bytes,
        (unsigned long long)producer_bps,
        (unsigned long long)consumer_bps,
        raw->eof );
    raw->last_log_us = now;
    raw->last_log_produced = raw->produced_bytes;
    raw->last_log_consumed = raw->consumed_bytes;
}

static void nova_raw_set_policy(NOVA_RAW_PREFETCH *raw,
                                int low_bytes, int resume_bytes)
{
    if( !raw->enabled )
        return;
    pthread_mutex_lock(&raw->mutex);
    raw->low_bytes = low_bytes;
    raw->resume_bytes = resume_bytes;
    raw->capacity_bytes = NOVA_RAW_FALLBACK_CAP_BYTES;
    pthread_cond_broadcast(&raw->can_write);
    pthread_mutex_unlock(&raw->mutex);
    raw->s->rebuffer_low_bytes = low_bytes;
    raw->s->rebuffer_resume_bytes = resume_bytes;
    raw->s->rebuffer_capacity_bytes = NOVA_RAW_FALLBACK_CAP_BYTES;
}

static void *nova_raw_thread(void *opaque)
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

        pthread_mutex_unlock(&raw->mutex);

        /*
         * The ring write offset MUST be sampled after source_mutex is owned.
         * A seek resets generation/read_off/write_off while also owning
         * source_mutex. Sampling write_off before this lock lets a producer
         * carry a pre-seek offset into the post-seek generation and place valid
         * new bytes at the wrong ring address.
         */
        pthread_mutex_lock(&raw->source_mutex);
        pthread_mutex_lock(&raw->mutex);
        if( !__atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) ||
            raw->eof || raw->used_bytes >= raw->capacity_bytes ) {
            pthread_mutex_unlock(&raw->mutex);
            pthread_mutex_unlock(&raw->source_mutex);
            continue;
        }

        generation = raw->generation;
        int64_t room = raw->capacity_bytes - raw->used_bytes;
        int64_t contiguous = raw->capacity_bytes - raw->write_off;
        int64_t ask = room < contiguous ? room : contiguous;
        if( ask > NOVA_RAW_IO_BYTES ) ask = NOVA_RAW_IO_BYTES;
        want = ask > 0 ? (int)ask : 0;
        write_off = raw->write_off;
        pthread_mutex_unlock(&raw->mutex);

        if( want <= 0 ) {
            pthread_mutex_unlock(&raw->source_mutex);
            continue;
        }

        int64_t nova_boot_io_begin = av_gettime_relative();
        int got = avio_read(raw->source, raw->ring + write_off, want);
        int64_t nova_boot_io_ms = (av_gettime_relative()-nova_boot_io_begin)/1000;
        if( nova_boot_io_ms >= 100 || raw->nova_boot_producer_calls++ < 12 )
            serprintf("NOVA_BOOT_RAW_SOURCE tMs=%lld thread=%lu generation=%u want=%d got=%d waitMs=%lld\n",
                      (long long)(av_gettime_relative()/1000),
                      (unsigned long)pthread_self(),generation,want,got,
                      (long long)nova_boot_io_ms);
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
         * Player/stream shutdown is terminal. stream_stop() marks aborted and
         * requests RAW stop before parser join. Never spin AVERROR_EXIT in the
         * transient 50 ms retry loop.
         */
        if( got == AVERROR_EXIT ||
            !__atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) ||
            (raw->s && stream_abort(raw->s)) ) {
            __atomic_store_n( &raw->run, 0, __ATOMIC_RELEASE );
            raw->error = AVERROR_EXIT;
            unsigned stop_generation = raw->generation;
            int64_t stop_used = raw->used_bytes;
            pthread_cond_broadcast(&raw->can_read);
            pthread_cond_broadcast(&raw->can_write);
            pthread_mutex_unlock(&raw->mutex);
            serprintf(
                "NOVA_RAW_ABORT: reason=source_abort error=%d generation=%u used=%lld\n",
                got, stop_generation, (long long)stop_used );
            break;
        }

        /* A failed MKV target GET must wake the demuxer, not be hidden by
         * an unbounded RAW producer retry while seekPause holds video. */
        if( raw->mkv_single_get &&
            __atomic_load_n(&raw->mkv_seek_active, __ATOMIC_ACQUIRE) ) {
            __atomic_store_n(&raw->mkv_seek_failed, 1, __ATOMIC_RELEASE);
            raw->error = got;
            pthread_cond_broadcast(&raw->can_read);
            pthread_mutex_unlock(&raw->mutex);
            av_usleep(50000);
            continue;
        }
        /*
         * A real transient network read error remains retryable while the
         * stream is alive and the fixed 128 MiB warehouse has room.
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
}

static int nova_mkv_seek_guard_failed(NOVA_RAW_PREFETCH *raw)
{
    if( !raw->mkv_single_get ||
        !__atomic_load_n(&raw->mkv_seek_active, __ATOMIC_ACQUIRE) )
        return 0;
    if( __atomic_load_n(&raw->mkv_seek_failed, __ATOMIC_ACQUIRE) )
        return 1;
    if( av_gettime_relative() - raw->mkv_seek_started_us > 12000000 )
        return 1;
    return raw->mkv_seek_bytes > (64ULL * 1024 * 1024);
}

static int nova_raw_read(void *opaque, uint8_t *dst, int size)
{
    NOVA_RAW_PREFETCH *raw = (NOVA_RAW_PREFETCH *)opaque;
    if( size <= 0 )
        return AVERROR(EINVAL);

    int64_t nova_boot_read_begin = av_gettime_relative();
    pthread_mutex_lock(&raw->mutex);
    if( nova_mkv_seek_guard_failed(raw) ) {
        pthread_mutex_unlock(&raw->mutex);
        return AVERROR(EIO);
    }
    while( __atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) &&
           raw->used_bytes == 0 && !raw->eof ) {
        if( raw->mkv_single_get &&
            __atomic_load_n(&raw->mkv_seek_active, __ATOMIC_ACQUIRE) ) {
            struct timespec timeout;
            clock_gettime(CLOCK_REALTIME, &timeout);
            timeout.tv_nsec += 100000000L;
            if( timeout.tv_nsec >= 1000000000L ) {
                timeout.tv_sec++;
                timeout.tv_nsec -= 1000000000L;
            }
            pthread_cond_timedwait(&raw->can_read, &raw->mutex, &timeout);
            if( nova_mkv_seek_guard_failed(raw) ) {
                pthread_mutex_unlock(&raw->mutex);
                return AVERROR(EIO);
            }
        } else {
            pthread_cond_wait(&raw->can_read, &raw->mutex);
        }
    }

    int64_t nova_boot_read_wait_ms = (av_gettime_relative()-nova_boot_read_begin)/1000;
    if( nova_boot_read_wait_ms >= 100 || raw->nova_boot_consumer_calls++ < 12 )
        serprintf("NOVA_BOOT_RAW_CONSUMER tMs=%lld thread=%lu want=%d used=%lld waitMs=%lld generation=%u\n",
                  (long long)(av_gettime_relative()/1000),
                  (unsigned long)pthread_self(),size,
                  (long long)raw->used_bytes,
                  (long long)nova_boot_read_wait_ms,raw->generation);
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

    if( raw->mkv_single_get &&
        __atomic_load_n(&raw->mkv_seek_active, __ATOMIC_ACQUIRE) ) {
        raw->mkv_seek_bytes += (uint64_t)copied;
        if( nova_mkv_seek_guard_failed(raw) )
            __atomic_store_n(&raw->mkv_seek_failed, 1, __ATOMIC_RELEASE);
    }
    nova_raw_log_locked(raw);
    pthread_cond_broadcast(&raw->can_write);
    pthread_mutex_unlock(&raw->mutex);
    return copied;
}

static int64_t nova_raw_seek(void *opaque, int64_t offset, int whence)
{
    NOVA_RAW_PREFETCH *raw = (NOVA_RAW_PREFETCH *)opaque;
    if( whence == AVSEEK_SIZE )
        return raw->source_size >= 0 ? raw->source_size : AVERROR(ENOSYS);

    whence &= ~AVSEEK_FORCE;
    int64_t target;
    pthread_mutex_lock(&raw->mutex);
    int64_t current = raw->consumer_pos;
    int64_t size = raw->source_size;
    pthread_mutex_unlock(&raw->mutex);

    if( whence == SEEK_SET )
        target = offset;
    else if( whence == SEEK_CUR )
        target = current + offset;
    else if( whence == SEEK_END && size >= 0 )
        target = size + offset;
    else
        return AVERROR(EINVAL);

    if( target < 0 || (size >= 0 && target > size) )
        return AVERROR(EINVAL);

    // Serialize the actual source protocol. The producer never holds the raw
    // queue mutex while blocked in network I/O, so seek cannot deadlock it.
    int64_t nova_boot_seek_wait_begin=av_gettime_relative();
    pthread_mutex_lock(&raw->source_mutex);
    int64_t nova_boot_mutex_wait_ms=(av_gettime_relative()-nova_boot_seek_wait_begin)/1000;
    int64_t nova_boot_seek_io_begin=av_gettime_relative();
    int64_t result = avio_seek(raw->source, target, SEEK_SET);
    int64_t nova_boot_seek_io_ms=(av_gettime_relative()-nova_boot_seek_io_begin)/1000;
    serprintf("NOVA_BOOT_RAW_SEEK tMs=%lld thread=%lu current=%lld target=%lld result=%lld mutexWaitMs=%lld ioMs=%lld\n",
              (long long)(av_gettime_relative()/1000),
              (unsigned long)pthread_self(),
              (long long)current,(long long)target,(long long)result,
              (long long)nova_boot_mutex_wait_ms,(long long)nova_boot_seek_io_ms);
    if( result < 0 && raw->mkv_single_get &&
        __atomic_load_n(&raw->mkv_seek_active, __ATOMIC_ACQUIRE) ) {
        __atomic_store_n(&raw->mkv_seek_failed, 1, __ATOMIC_RELEASE);
        serprintf("NOVA_MKV_RANGE_SEEK_FAIL_V1: target=%lld rc=%lld\n",
                  (long long)target, (long long)result);
    }
    if( result >= 0 ) {
        if( raw->mkv_single_get )
            __atomic_store_n(&raw->mkv_seek_failed, 0, __ATOMIC_RELEASE);
        pthread_mutex_lock(&raw->mutex);
        raw->generation++;
        unsigned generation = raw->generation;
        nova_raw_reset_locked(raw);
        raw->consumer_pos = result;
        raw->eof = 0;
        raw->error = 0;
        __atomic_store_n(
            &raw->s->raw_prefetch_eof, 0, __ATOMIC_RELEASE );
        pthread_cond_broadcast(&raw->can_read);
        pthread_cond_broadcast(&raw->can_write);
        serprintf(
            "NOVA_RAW128_SEEK: target=%lld result=%lld generation=%u\n",
            (long long)target, (long long)result, generation );
        pthread_mutex_unlock(&raw->mutex);
    }
    pthread_mutex_unlock(&raw->source_mutex);
    return result;
}

static void nova_raw_stats(NOVA_RAW_PREFETCH *raw,
                           int *used, int *capacity)
{
    *used = 0;
    *capacity = 0;
    if( !raw->enabled )
        return;
    pthread_mutex_lock(&raw->mutex);
    *used = raw->used_bytes > INT_MAX ? INT_MAX : (int)raw->used_bytes;
    *capacity = raw->capacity_bytes > INT_MAX ?
        INT_MAX : (int)raw->capacity_bytes;
    pthread_mutex_unlock(&raw->mutex);
}

static int nova_raw_open(NOVA_RAW_PREFETCH *raw, STREAM *s,
                         AVFormatContext *fmt, const char *url,
                         AVDictionary **options)
{
    if( strncmp(url, "http://", 7) && strncmp(url, "https://", 8) )
        return 0;

    /*
     * Install the RAW consumer BEFORE avformat_open_input(). FFmpeg/MOV then
     * sees one stable AVIOContext for probe, tail-moov discovery and runtime.
     * The producer owns exactly one URL AVIO source. Random access is
     * serialized by source_mutex; no post-probe AVIO replacement is allowed.
     */
    memset(raw, 0, sizeof(*raw));
    raw->s = s;
    raw->mkv_single_get = strstr(url, "nova_mkv=1") != NULL;
    raw->source_size = -1;
    raw->capacity_bytes = NOVA_RAW_FALLBACK_CAP_BYTES;
    raw->low_bytes = NOVA_RAW_FALLBACK_LOW_BYTES;
    raw->resume_bytes = NOVA_RAW_FALLBACK_RESUME_BYTES;
    raw->upstream_interrupt = fmt->interrupt_callback;
    __atomic_store_n(&raw->run, 1, __ATOMIC_RELEASE);

    int ret = AVERROR(ENOMEM);
    int mutex_ready = 0, source_mutex_ready = 0;
    int can_read_ready = 0, can_write_ready = 0;
    if( pthread_mutex_init(&raw->mutex, NULL) )
        return AVERROR(ENOMEM);
    mutex_ready = 1;
    if( pthread_mutex_init(&raw->source_mutex, NULL) )
        goto init_fail;
    source_mutex_ready = 1;
    if( pthread_cond_init(&raw->can_read, NULL) )
        goto init_fail;
    can_read_ready = 1;
    if( pthread_cond_init(&raw->can_write, NULL) )
        goto init_fail;
    can_write_ready = 1;

    raw->ring = av_malloc(NOVA_RAW_FALLBACK_CAP_BYTES);
    if( !raw->ring ) {
        ret = AVERROR(ENOMEM);
        goto fail;
    }
    raw->read_off = 0;
    raw->write_off = 0;

    AVDictionary *io_options = NULL;
    av_dict_copy(&io_options, *options, 0);
    AVIOInterruptCB interrupt = {
        .callback = nova_raw_interrupt,
        .opaque = raw,
    };
    ret = avio_open2(
        &raw->source, url, AVIO_FLAG_READ, &interrupt, &io_options );
    av_dict_free(&io_options);
    if( ret < 0 || !raw->source )
        goto fail;

    raw->source_size = avio_size(raw->source);
    int64_t origin = avio_seek(raw->source, 0, SEEK_SET);
    if( origin < 0 ) {
        ret = (int)origin;
        goto fail;
    }

    unsigned char *buffer = av_malloc(NOVA_RAW_IO_BYTES);
    if( !buffer ) {
        ret = AVERROR(ENOMEM);
        goto fail;
    }
    raw->consumer = avio_alloc_context(
        buffer, NOVA_RAW_IO_BYTES, 0, raw,
        nova_raw_read, NULL, nova_raw_seek );
    if( !raw->consumer ) {
        av_free(buffer);
        ret = AVERROR(ENOMEM);
        goto fail;
    }
    raw->consumer->seekable = raw->source->seekable;
    raw->consumer->pos = 0;
    raw->consumer_pos = 0;

    fmt->pb = raw->consumer;
    fmt->flags |= AVFMT_FLAG_CUSTOM_IO;
    raw->enabled = 1;
    s->rebuffer_low_bytes = NOVA_RAW_FALLBACK_LOW_BYTES;
    s->rebuffer_resume_bytes = NOVA_RAW_FALLBACK_RESUME_BYTES;
    s->rebuffer_capacity_bytes = NOVA_RAW_FALLBACK_CAP_BYTES;
    __atomic_store_n(&s->raw_prefetch_enabled, 1, __ATOMIC_RELEASE);
    __atomic_store_n(&s->raw_prefetch_eof, 0, __ATOMIC_RELEASE);

    ret = pthread_create(&raw->thread, NULL, nova_raw_thread, raw);
    if( ret ) {
        ret = AVERROR(ret);
        goto fail;
    }
    raw->thread_started = 1;
    serprintf(
        "NOVA_RAW128_OPEN: phase=pre_probe url=%s fallback_low=%d fallback_resume=%d fallback_capacity=%d source_size=%lld seekable=%d\n",
        url, NOVA_RAW_FALLBACK_LOW_BYTES,
        NOVA_RAW_FALLBACK_RESUME_BYTES,
        NOVA_RAW_FALLBACK_CAP_BYTES,
        (long long)raw->source_size,
        !!(raw->consumer->seekable & AVIO_SEEKABLE_NORMAL) );
    return 1;

fail:
    __atomic_store_n(&raw->run, 0, __ATOMIC_RELEASE);
    if( raw->thread_started ) {
        pthread_mutex_lock(&raw->mutex);
        pthread_cond_broadcast(&raw->can_read);
        pthread_cond_broadcast(&raw->can_write);
        pthread_mutex_unlock(&raw->mutex);
        pthread_join(raw->thread, NULL);
        raw->thread_started = 0;
    }
    if( raw->consumer ) {
        if( fmt->pb == raw->consumer )
            fmt->pb = NULL;
        av_freep(&raw->consumer->buffer);
        avio_context_free(&raw->consumer);
    }
    if( raw->source )
        avio_closep(&raw->source);
    av_freep(&raw->ring);
    raw->enabled = 0;
    __atomic_store_n(&s->raw_prefetch_enabled, 0, __ATOMIC_RELEASE);
    __atomic_store_n(&s->raw_prefetch_eof, 0, __ATOMIC_RELEASE);
init_fail:
    if( can_write_ready ) pthread_cond_destroy(&raw->can_write);
    if( can_read_ready ) pthread_cond_destroy(&raw->can_read);
    if( source_mutex_ready ) pthread_mutex_destroy(&raw->source_mutex);
    if( mutex_ready ) pthread_mutex_destroy(&raw->mutex);
    return ret < 0 ? ret : AVERROR(ENOMEM);
}

static void nova_raw_close(NOVA_RAW_PREFETCH *raw)
{
    if( !raw->enabled )
        return;

    __atomic_store_n(&raw->run, 0, __ATOMIC_RELEASE);
    pthread_mutex_lock(&raw->mutex);
    pthread_cond_broadcast(&raw->can_read);
    pthread_cond_broadcast(&raw->can_write);
    pthread_mutex_unlock(&raw->mutex);

    if( raw->thread_started ) {
        pthread_join(raw->thread, NULL);
        raw->thread_started = 0;
    }

    pthread_mutex_lock(&raw->mutex);
    nova_raw_reset_locked(raw);
    pthread_mutex_unlock(&raw->mutex);

    if( raw->consumer ) {
        av_freep(&raw->consumer->buffer);
        avio_context_free(&raw->consumer);
    }
    if( raw->source )
        avio_closep(&raw->source);
    av_freep(&raw->ring);

    __atomic_store_n(&raw->s->raw_prefetch_enabled, 0, __ATOMIC_RELEASE);
    __atomic_store_n(&raw->s->raw_prefetch_eof, 0, __ATOMIC_RELEASE);
    pthread_cond_destroy(&raw->can_write);
    pthread_cond_destroy(&raw->can_read);
    pthread_mutex_destroy(&raw->source_mutex);
    pthread_mutex_destroy(&raw->mutex);
    raw->enabled = 0;
}

void nova_raw_request_stop(STREAM *s)
{
    if( !s || !s->parser_priv ||
        !__atomic_load_n( &s->raw_prefetch_enabled, __ATOMIC_ACQUIRE ) )
        return;

    FF_PRIV *ff_p = (FF_PRIV *)s->parser_priv;
    NOVA_RAW_PREFETCH *raw = &ff_p->raw;
    if( !raw->enabled )
        return;

    int was_running = __atomic_exchange_n(
        &raw->run, 0, __ATOMIC_ACQ_REL );

    pthread_mutex_lock(&raw->mutex);
    raw->error = AVERROR_EXIT;
    unsigned generation = raw->generation;
    int64_t used = raw->used_bytes;
    pthread_cond_broadcast(&raw->can_read);
    pthread_cond_broadcast(&raw->can_write);
    pthread_mutex_unlock(&raw->mutex);

    serprintf(
        "NOVA_RAW_ABORT: reason=stream_stop was_running=%d generation=%u used=%lld\n",
        was_running, generation, (long long)used );
}
'''


DYNAMIC_POLICY = r'''
	s->duration = ff_p->duration;
	s->size     = ff_p->size;

    // X = average source bytes/second. 1.5X/3X control playback only.
    // Network production has a separate fixed 128 MiB warehouse wall.
    uint64_t nova_x = 0;
    const uint64_t nova_max_x = (uint64_t)(INT_MAX / 5);
    if (ff_p->size_known && s->size > 0 && s->duration > 0) {
        uint64_t duration_ms = (uint64_t)s->duration;
        uint64_t whole = (uint64_t)s->size / duration_ms;
        uint64_t remain = (uint64_t)s->size % duration_ms;
        if (whole > nova_max_x / 1000)
            nova_x = nova_max_x;
        else
            nova_x = whole * 1000 + (remain * 1000) / duration_ms;
        if (nova_x > nova_max_x) nova_x = nova_max_x;
    }

    // MPEG-TS keeps legacy no_duration presentation semantics. Derive X only
    // for raw buffering from credible demux/title metadata; never mutate the
    // player duration or seek timebase.
    if (ff_p->raw.enabled && s->etype == ETYPE_MPEG_TS) {
        const AVFormatContext *nova_ts_fmt = ff_p->fmt;
        const char *nova_ts_source = "fallback";
        int64_t nova_ts_duration_us = nova_ts_fmt ?
            nova_ts_fmt->duration : AV_NOPTS_VALUE;
        int64_t nova_ts_demux_bps = nova_ts_fmt ? nova_ts_fmt->bit_rate : 0;
        const uint64_t nova_ts_min_x = 8192;
        const uint64_t nova_ts_max_x = 25 * 1024 * 1024;

        int nova_iso_metadata_valid = 0;
        const char *nova_iso_duration_arg = NULL;
        if (strstr(s->src_query, "&nova_iso=1&") != NULL)
            nova_iso_duration_arg = strstr(
                s->src_query, "&nova_iso_duration_us=");
        if (nova_iso_duration_arg) {
            const char *digits = nova_iso_duration_arg +
                sizeof("&nova_iso_duration_us=") - 1;
            if (*digits >= '0' && *digits <= '9') {
                char *end = NULL;
                unsigned long long us = strtoull(digits, &end, 10);
                if (end != digits && (*end == '\0' || *end == '&') &&
                    us >= 10ULL * AV_TIME_BASE &&
                    us <= 24ULL * 3600 * AV_TIME_BASE) {
                    nova_ts_duration_us = (int64_t)us;
                    nova_iso_metadata_valid = 1;
                }
            }
        }

        if (ff_p->size_known && s->size > 0 && nova_ts_fmt) {
            if (nova_ts_duration_us <= 0 ||
                nova_ts_duration_us == AV_NOPTS_VALUE) {
                for (int pass = 0; pass < 2; pass++) {
                    for (unsigned int i = 0; i < nova_ts_fmt->nb_streams; i++) {
                        const AVStream *st = nova_ts_fmt->streams[i];
                        if (!st || !st->codecpar) continue;
                        if (st->codecpar->codec_type !=
                            (pass == 0 ? AVMEDIA_TYPE_VIDEO : AVMEDIA_TYPE_AUDIO))
                            continue;
                        if (st->duration <= 0 || st->duration == AV_NOPTS_VALUE ||
                            st->time_base.num <= 0 || st->time_base.den <= 0)
                            continue;
                        int64_t candidate = av_rescale_q(
                            st->duration, st->time_base, AV_TIME_BASE_Q);
                        if (candidate >= 10LL * AV_TIME_BASE &&
                            candidate <= 24LL * 3600 * AV_TIME_BASE) {
                            nova_ts_duration_us = candidate;
                            break;
                        }
                    }
                    if (nova_ts_duration_us >= 10LL * AV_TIME_BASE &&
                        nova_ts_duration_us <= 24LL * 3600 * AV_TIME_BASE)
                        break;
                }
            }

            if (nova_ts_duration_us >= 10LL * AV_TIME_BASE &&
                nova_ts_duration_us <= 24LL * 3600 * AV_TIME_BASE) {
                const uint64_t us = (uint64_t)nova_ts_duration_us;
                const uint64_t whole = (uint64_t)s->size / us;
                const uint64_t part = (uint64_t)s->size % us;
                uint64_t x = whole > nova_max_x / AV_TIME_BASE ?
                    nova_max_x : whole * AV_TIME_BASE +
                    (part * AV_TIME_BASE) / us;
                if (x >= nova_ts_min_x && x <= nova_ts_max_x) {
                    nova_x = x;
                    nova_ts_source = nova_iso_metadata_valid ?
                        "iso-title-metadata" : "duration-derived";
                }
            }

            if (nova_x == 0 &&
                nova_ts_demux_bps >= (int64_t)nova_ts_min_x * 8 &&
                nova_ts_demux_bps <= (int64_t)nova_ts_max_x * 8) {
                nova_x = (uint64_t)nova_ts_demux_bps / 8;
                nova_ts_source = "demux-estimate";
            }
            if (nova_x > nova_max_x) nova_x = nova_max_x;
        }
        serprintf(
            "NOVA_TS_BITRATE: source=%s size=%llu duration_us=%lld demux_bps=%lld x_bytes_per_sec=%llu seekable=%d\n",
            nova_ts_source, (unsigned long long)s->size,
            (long long)nova_ts_duration_us, (long long)nova_ts_demux_bps,
            (unsigned long long)nova_x,
            nova_ts_fmt && nova_ts_fmt->pb ?
                !!(nova_ts_fmt->pb->seekable & AVIO_SEEKABLE_NORMAL) : 0);
    }

    if (ff_p->raw.enabled) {
        int low = NOVA_RAW_FALLBACK_LOW_BYTES;
        int resume = NOVA_RAW_FALLBACK_RESUME_BYTES;
        const int capacity = NOVA_RAW_FALLBACK_CAP_BYTES;
        int clamped = 0;
        uint64_t requested_low = low;
        uint64_t requested_resume = resume;

        if (nova_x > 0) {
            requested_low = nova_x + nova_x / 2; /* 1.5 X, no floating point */
            requested_resume = 3 * nova_x;
            low = requested_low > (uint64_t)INT_MAX ?
                INT_MAX : (int)requested_low;
            resume = requested_resume > (uint64_t)INT_MAX ?
                INT_MAX : (int)requested_resume;
        }

        // RAW is fixed at 128 MiB. Resident bytes also include the ordinary
        // packet handoff queue, so clamp only mathematically unreachable
        // thresholds to prevent an infinite rebuffer wait on extreme media.
        int64_t max_resident64 = (int64_t)capacity +
            (ff_p->buffer_size > 0 ? (int64_t)ff_p->buffer_size : 0);
        int max_resident = max_resident64 > INT_MAX ?
            INT_MAX : (int)max_resident64;
        if (resume > max_resident) {
            resume = max_resident;
            clamped = 1;
        }
        if (low >= resume) {
            low = resume > 2 ? resume / 2 : 1;
            clamped = 1;
        }

        nova_raw_set_policy(&ff_p->raw, low, resume);
        serprintf(
            "NOVA_RAW_FIXED128_POLICY: mode=%s size=%llu duration_ms=%d x_bytes_per_sec=%llu requested_low=%llu requested_resume=%llu low=%d resume=%d capacity=%d packet_handoff=%d max_resident=%d clamped=%d\n",
            nova_x > 0 ? "average" : "fallback",
            (unsigned long long)s->size, s->duration,
            (unsigned long long)nova_x,
            (unsigned long long)requested_low,
            (unsigned long long)requested_resume,
            low, resume, capacity, ff_p->buffer_size,
            max_resident, clamped);
    } else {
        s->rebuffer_low_bytes = 0;
        s->rebuffer_resume_bytes = 0;
        s->rebuffer_capacity_bytes = 0;
    }
'''


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
    /* Run584 default OS scheduling; no explicit priority/affinity changes. */
    (void)role;
    (void)requested_nice;
}'''


def patch_stream_h(path: Path) -> None:
    text = path.read_text()
    # v6.6 no longer exposes STREAM_SUBTITLE_CLEARED; preserve
    # the upstream enum and append the two buffering notifications.
    text = sub_once(
        text,
        r"(\tSTREAM_DECODER_CHANGED,\n)(} STREAM_MESSAGE;)",
        r"\1\tSTREAM_BUFFERING_START,\n\tSTREAM_BUFFERING_END,\n\2",
        "STREAM_MESSAGE enum v6.6",
    )
    text = sub_once(
        text,
        r"(\n\s*int\s+fps_start;\n\s*int\s+fps_count;\n\s*void\s+\*surface_handle;\n(?:\s*void\s+\*sub_engine;\n)?)(\s*\n}\s*STREAM;)",
        r"\1"
        "\n\t// Native raw-source buffering state. Appended for ABI safety.\n"
        "\tpthread_t\trebuffer_thread_handle;\n"
        "\tint\t\trebuffer_thread_started;\n"
        "\tTHREAD_STATE\trebuffer_tstate;\n"
        "\tvolatile int\trebuffering;\n"
        "\tvolatile int\trebuffer_user_paused;\n"
        "\tvolatile int\trebuffer_play_requested;\n"
        "\tvolatile int\trebuffer_frame_seen;\n"
        "\tvolatile int\traw_prefetch_enabled;\n"
        "\tvolatile int\traw_prefetch_eof;\n"
        "\tvolatile int\tstartup_first_sink_logged;\n"
        "\tint\t\trebuffer_low_bytes;\n"
        "\tint\t\trebuffer_resume_bytes;\n"
        "\tint\t\trebuffer_capacity_bytes;\n"
        r"\2",
        "STREAM tail raw buffering fields",
    )
    path.write_text(text)


def patch_stream_video(path: Path) -> None:
    text = path.read_text()
    text = replace_once(text, '#include "global.h"',
        '#ifndef _GNU_SOURCE\n#define _GNU_SOURCE 1\n#endif\n#include "global.h"',
        "video GNU feature define")
    text = replace_once(text, "#include <signal.h>\n",
        "#include <signal.h>\n#include <sched.h>\n#include <sys/resource.h>\n#include <unistd.h>\n",
        "video scheduling includes")
    text = replace_once(text, "static void *_decode_thread( void *data )\n",
        PLAYBACK_SCHED + "\nstatic void *_decode_thread( void *data )\n",
        "playback scheduling helper")
    text = replace_once(
        text,
        "\tSTREAM *s = (STREAM *)data;\n\ttimeline_set_local_identity(!!(s->flags & STREAM_THUMB));\nDBGS serprintf(\"PID[%5d] decode_thread::Starting\\r\\n\", getpid() );\t\n\t\n\twhile( s->codec_run ) {",
        "\tSTREAM *s = (STREAM *)data;\n\ttimeline_set_local_identity(!!(s->flags & STREAM_THUMB));\n\tint nova_sched_done = 0;\nDBGS serprintf(\"PID[%5d] decode_thread::Starting\\r\\n\", getpid() );\t\n\t\n\twhile( s->codec_run ) {\n\t\tif( !nova_sched_done && __atomic_load_n(&s->raw_prefetch_enabled, __ATOMIC_ACQUIRE) ) {\n\t\t\tnova_playback_yield_sched(\"decode\", 8);\n\t\t\tnova_sched_done = 1;\n\t\t}",
        "decode yields to downloader")
    text = replace_once(
        text,
        "\tSTREAM *s = (STREAM *)data;\n\ttimeline_set_local_identity(!!(s->flags & STREAM_THUMB));\n\tint yield = 1;",
        "\tSTREAM *s = (STREAM *)data;\n\ttimeline_set_local_identity(!!(s->flags & STREAM_THUMB));\n\tint nova_sched_done = 0;\n\tint yield = 1;",
        "parser scheduling flag")
    text = replace_once(
        text,
        "\twhile( thread_state_get( &s->parser_tstate ) != THREAD_EXIT ) {\n\t\tthread_state_ack( &s->parser_tstate );",
        "\twhile( thread_state_get( &s->parser_tstate ) != THREAD_EXIT ) {\n\t\tif( !nova_sched_done && __atomic_load_n(&s->raw_prefetch_enabled, __ATOMIC_ACQUIRE) ) {\n\t\t\tnova_playback_yield_sched(\"parser\", 5);\n\t\t\tnova_sched_done = 1;\n\t\t}\n\t\tthread_state_ack( &s->parser_tstate );",
        "parser yields to downloader")
    text = replace_once(
        text,
        "int stream_stop( STREAM *s )\n{",
        "extern void nova_raw_request_stop(STREAM *s);\n\n"
        "int stream_stop( STREAM *s )\n{",
        "declare RAW early-stop hook",
    )
    text = replace_once(
        text,
        "\t// abort everything\n\ts->aborted = 1;\n",
        "\t// abort everything\n\ts->aborted = 1;\n"
        "\t// Stop source I/O before stream_close() waits for parser threads.\n"
        "\tnova_raw_request_stop( s );\n",
        "stop RAW before parser join",
    )

    text = replace_once(
        text,
        "#define THREAD_PRIO_SUBTITLE\t0\n",
        "#define THREAD_PRIO_SUBTITLE\t0\n\n"
        "#define NOVA_REBUFFER_POLL_MS      50\n",
        "raw rebuffer constants",
    )
    text = sub_once(
        text,
        r"(static\s+void\s+\*_parser_thread\s*\(\s*void\s+\*data\s*\);\n)",
        r"\1static void\t*_rebuffer_thread( void *data );\n",
        "rebuffer forward declaration",
    )

    # During an INTERNAL rebuffer only, keep demux running until its ordinary
    # packet handoff queue backpressures. Manual pause remains a real parser
    # pause; the raw network producer is independent and keeps filling itself.
    text = sub_once(
        text,
        r"if\s*\(\s*!s->paused\s*\|\|\s*s->play_n_video_frames\s*\|\|\s*"
        r"s->play_n_audio_frames\s*\|\|\s*s->parser_parse_once\s*\)\s*\{",
        "if( !s->paused || "
        "__atomic_load_n( &s->rebuffering, __ATOMIC_ACQUIRE ) || "
        "s->play_n_video_frames || s->play_n_audio_frames || "
        "s->parser_parse_once ) {",
        "parser continues only during internal rebuffer",
    )

    text = replace_once(
        text,
        "static void _seek_init( STREAM *s )\n{\n\ts->seek = 1;",
        "static void _seek_init( STREAM *s )\n{\n"
        "\t__atomic_store_n( &s->rebuffer_frame_seen, 0, __ATOMIC_RELEASE );\n"
        "\ts->seek = 1;",
        "reset first-frame proof on seek",
    )
    text = replace_once(
        text,
        "\ts->video_sink_count ++;\n\tpthread_mutex_unlock( &s->video_sink_mutex );",
        "\ts->video_sink_count ++;\n"
        "\tif( __atomic_load_n( &s->rebuffer_play_requested, __ATOMIC_ACQUIRE ) )\n"
        "\t\t__atomic_store_n( &s->rebuffer_frame_seen, 1, __ATOMIC_RELEASE );\n"
        "\tpthread_mutex_unlock( &s->video_sink_mutex );",
        "prove first frame reached video sink",
    )
    text = sub_once(
        text,
        r"(static\s+void\s+\*_player_thread\s*\(\s*void\s+\*data\s*\)\s*\n\{)",
        lambda m: REBUFFER_THREAD + "\n" + m.group(1),
        "insert raw rebuffer thread",
    )
    marker = "\t// lock and start the subtitle_thread\n"
    start = (
        "\t// Playback controller only; raw network production lives in FFmpeg source IO.\n"
        "\tif( _stream_start_thread( &s->rebuffer_tstate, &s->rebuffer_thread_handle,\n"
        "\t\t&s->rebuffer_thread_started, _rebuffer_thread, s, stream_prio_parser, \"rbuf\" ) )\n"
        "\t\tgoto ErrorExit;\n\t\n"
    )
    text = replace_once(text, marker, start + marker, "start rebuffer controller")
    text = replace_once(
        text,
        "\tthread_state_set( &s->parser_tstate, THREAD_RUNNING );\n"
        "\tthread_state_set( &s->engine_tstate, THREAD_RUNNING );",
        "\tthread_state_set( &s->parser_tstate,   THREAD_RUNNING );\n"
        "\tthread_state_set( &s->rebuffer_tstate, THREAD_RUNNING );\n"
        "\tthread_state_set( &s->engine_tstate,   THREAD_RUNNING );",
        "run rebuffer controller",
    )
    path.write_text(text)


def patch_stream_c(path: Path) -> None:
    text = path.read_text()
    marker = 'DBGS serprintf("waiting for threads to join\\r\\n");\n'
    block = r'''DBGS serprintf("waiting for threads to join\r\n");
    if( s->rebuffer_thread_started ) {
        thread_state_set( &s->rebuffer_tstate, THREAD_EXIT );
        apthread_join( s->rebuffer_thread_handle, NULL );
        s->rebuffer_thread_started = 0;
        __atomic_store_n( &s->rebuffering, 0, __ATOMIC_RELEASE );
        __atomic_store_n( &s->rebuffer_user_paused, 0, __ATOMIC_RELEASE );
        __atomic_store_n( &s->rebuffer_play_requested, 0, __ATOMIC_RELEASE );
        __atomic_store_n( &s->rebuffer_frame_seen, 0, __ATOMIC_RELEASE );
        pthread_cond_destroy( &s->rebuffer_tstate._cond );
        pthread_mutex_destroy( &s->rebuffer_tstate._mutex );
DBGS   serprintf("raw_rebuffer_thread joined\r\n");
    }
'''
    text = replace_once(text, marker, block, "join rebuffer controller")
    path.write_text(text)


def patch_avos_mp_video(path: Path) -> None:
    text = path.read_text()
    # AVOS v6.6 has folded subtitle change reporting into STREAM_SUB_PROPS_CHANGED.
    # Preserve existing metadata events; add buffering messages next to them.
    text = replace_once(
        text,
        "\tcase STREAM_DECODER_CHANGED:\n\t\tsend_metadata(mp, video, 1);\n\t\tbreak;\n\tdefault:",
        "\tcase STREAM_DECODER_CHANGED:\n\t\tsend_metadata(mp, video, 1);\n\t\tbreak;\n"
        "\tcase STREAM_BUFFERING_START:\n"
        "\t\tavos_mp_sendevent(mp, MEDIA_INFO, MEDIA_INFO_BUFFERING_START, 0);\n"
        "\t\tbreak;\n"
        "\tcase STREAM_BUFFERING_END:\n"
        "\t\tavos_mp_sendevent(mp, MEDIA_INFO, MEDIA_INFO_BUFFERING_END, 0);\n"
        "\t\tbreak;\n\tdefault:",
        "buffering media info v6.6",
    )
    # v6.6 also starts/stops the separate subtitle engine. Do not replace it:
    # insert only the network buffer lifecycle before the existing first action.
    text = replace_once(
        text,
        "int avos_mp_video_start(avos_mp_t *mp, avos_mp_video_t *video)\n{\n",
        "int avos_mp_video_start(avos_mp_t *mp, avos_mp_video_t *video)\n{\n"
        "\t__atomic_store_n(&video->s->rebuffer_play_requested, 1, __ATOMIC_RELEASE);\n"
        "\t__atomic_store_n(&video->s->rebuffer_frame_seen, 0, __ATOMIC_RELEASE);\n"
        "\tif (__atomic_load_n(&video->s->rebuffering, __ATOMIC_ACQUIRE)) {\n"
        "\t\t__atomic_store_n(&video->s->rebuffer_user_paused, 0, __ATOMIC_RELEASE);\n"
        "\t\treturn AVOS_ERR_OK;\n"
        "\t}\n",
        "real play arms raw rebuffer lifecycle v6.6",
    )
    text = replace_once(
        text,
        "int avos_mp_video_pause(avos_mp_t *mp, avos_mp_video_t *video)\n{\n",
        "int avos_mp_video_pause(avos_mp_t *mp, avos_mp_video_t *video)\n{\n"
        "\t__atomic_store_n(&video->s->rebuffer_play_requested, 0, __ATOMIC_RELEASE);\n"
        "\t__atomic_store_n(&video->s->rebuffer_frame_seen, 0, __ATOMIC_RELEASE);\n"
        "\tif (__atomic_load_n(&video->s->rebuffering, __ATOMIC_ACQUIRE)) {\n"
        "\t\t__atomic_store_n(&video->s->rebuffer_user_paused, 1, __ATOMIC_RELEASE);\n"
        "\t\treturn AVOS_ERR_OK;\n"
        "\t}\n",
        "manual pause stays independent from raw producer v6.6",
    )
    path.write_text(text)


def patch_stream_parser_ffmpeg(path: Path) -> None:
    text = path.read_text()
    text = replace_once(
        text, '#include "types.h"',
        '#ifndef _GNU_SOURCE\n#define _GNU_SOURCE 1\n#endif\n#include "types.h"',
        "parser GNU feature define",
    )
    text = replace_once(
        text, "#include <signal.h>\n",
        "#include <signal.h>\n#include <sched.h>\n#include <sys/resource.h>\n#include <unistd.h>\n",
        "parser scheduling includes",
    )

    text = replace_once(
        text, "#include <sys/resource.h>\n",
        "#include <sys/resource.h>\n#include <time.h>\n",
        "mkv timed wait clock",
    )

    fd_type = '''typedef struct FD_INPUT {
\tint fd;
\tint64_t start, length, pos;
\tAVIOInterruptCB interrupt;
} FD_INPUT;
'''
    text = replace_once(
        text, fd_type, fd_type + "\n" + RAW_TYPES + "\n",
        "insert raw prefetch types",
    )
    text = replace_once(
        text,
        "\tAVIOContext *fd_io;\n\tFD_INPUT *fd_input;\n",
        "\tAVIOContext *fd_io;\n\tFD_INPUT *fd_input;\n"
        "\tNOVA_RAW_PREFETCH raw;\n",
        "add raw prefetch to FF_PRIV",
    )

    seek_anchor = '''static int64_t fd_input_seek(void *opaque, int64_t offset, int whence)
{
\tFD_INPUT *in = opaque;
\tif (whence == AVSEEK_SIZE) return in->length;
\twhence &= ~AVSEEK_FORCE;
\tint64_t base;
\tif (whence == SEEK_SET) base = 0;
\telse if (whence == SEEK_CUR) base = in->pos;
\telse if (whence == SEEK_END) base = in->length;
\telse return AVERROR(EINVAL);
\tif (offset < -base || offset > in->length - base) return AVERROR(EINVAL);
\tin->pos = base + offset;
\treturn in->pos;
}
'''
    text = replace_once(
        text, seek_anchor, seek_anchor + "\n" + RAW_CODE + "\n",
        "insert raw prefetch implementation",
    )

    open_pattern = (
        r"static int ffmpeg_open_input\(FF_PRIV \*priv, const char \*url, "
        r"AVDictionary \*\*options\)\n\{.*?\n\}\n\nstatic int ff_force_seek"
    )
    open_replacement = r'''static int ffmpeg_open_input(FF_PRIV *priv, const char *url, AVDictionary **options)
{
	if (strncmp(url, "fd://", 5)) {
		int raw_result = 0;
		if (priv->s)
			raw_result = nova_raw_open(
				&priv->raw, priv->s, priv->fmt, url, options);
		if (raw_result < 0)
			return raw_result;
		if (raw_result > 0)
			return avformat_open_input(&priv->fmt, url, NULL, options);
		return avformat_open_input(&priv->fmt, url, NULL, options);
	}
	int fd;
	int64_t offset, length;
	if (stream_fd_parse_url(url, &fd, &offset, &length)) return AVERROR(EINVAL);
	fd = stream_fd_duplicate(fd, offset, &length);
	if (fd < 0) return AVERROR(errno);
	priv->fd_input = acalloc(1, sizeof(*priv->fd_input));
	if (!priv->fd_input) { close(fd); return AVERROR(ENOMEM); }
	*priv->fd_input = (FD_INPUT){.fd = fd, .start = offset, .length = length,
		.interrupt = priv->fmt->interrupt_callback};
	unsigned char *buffer = av_malloc(32768);
	if (!buffer) return AVERROR(ENOMEM);
	priv->fd_io = avio_alloc_context(buffer, 32768, 0, priv->fd_input,
		fd_input_read, NULL, fd_input_seek);
	if (!priv->fd_io) { av_free(buffer); return AVERROR(ENOMEM); }
	priv->fmt->pb = priv->fd_io;
	priv->fmt->flags |= AVFMT_FLAG_CUSTOM_IO;
	return avformat_open_input(&priv->fmt, NULL, NULL, options);
}

static int ff_force_seek'''
    text = sub_once(
        text, open_pattern, open_replacement,
        "replace FFmpeg source open with raw producer",
    )

    text = replace_once(
        text,
        "\ts->duration = ff_p->duration;\n\ts->size     = ff_p->size;\n",
        DYNAMIC_POLICY,
        "install source-layer dynamic 1.5X/3X with fixed 128MiB producer wall",
    )

    # Custom AVIO is owned by us because AVFMT_FLAG_CUSTOM_IO prevents lavf
    # from closing it.
    text = replace_once(
        text,
        "\tif (ff_p->fmt) avformat_close_input(&ff_p->fmt);\n"
        "\tffmpeg_close_fd_input(ff_p);",
        "\tif (ff_p->fmt) avformat_close_input(&ff_p->fmt);\n"
        "\tnova_raw_close(&ff_p->raw);\n"
        "\tffmpeg_close_fd_input(ff_p);",
        "error cleanup raw producer",
    )
    text = replace_once(
        text,
        "\t\tif( ff_p->fmt ) {\n"
        "\t\t\t// Close the video file\n"
        "\t\t\tavformat_close_input(&ff_p->fmt);\n"
        "\t\t}\n\n\n"
        "\t\tffmpeg_close_fd_input(ff_p);",
        "\t\tif( ff_p->fmt ) {\n"
        "\t\t\t// Close the video file\n"
        "\t\t\tavformat_close_input(&ff_p->fmt);\n"
        "\t\t}\n\n"
        "\t\tnova_raw_close(&ff_p->raw);\n"
        "\t\tffmpeg_close_fd_input(ff_p);",
        "normal cleanup raw producer",
    )

    stats_old = '''\tstats->buffer_size   = ff_p->buffer_size;
\tstats->buffer_used   = ff_p->aq.mem_used + ff_p->vq.mem_used;
\t
\tstats->audio_chunks  = ff_p->aq.packets;
\tstats->video_chunks  = ff_p->vq.packets;
'''
    stats_new = '''\t// buffer is the ordinary post-demux packet handoff/safety queue.
\tstats->buffer_size   = ff_p->buffer_size;
\tstats->buffer_used   = ff_p->aq.mem_used + ff_p->vq.mem_used;
\t// buffer2 is the independent PRE-DEMUX raw source queue. Its capacity is
\t// the single fixed 128 MiB network-production wall.
\tnova_raw_stats(&ff_p->raw, &stats->buffer2_used, &stats->buffer2_size);
\t
\tstats->audio_chunks  = ff_p->aq.packets;
\tstats->video_chunks  = ff_p->vq.packets;
'''
    text = replace_once(
        text, stats_old, stats_new,
        "publish raw prefetch stats",
    )

    required = (
        "NOVA_RAW128_OPEN:",
        "NOVA_RAW128:",
        "NOVA_RAW_FIXED128_POLICY:",
        "NOVA_TS_BITRATE:",
        "nova_raw_thread",
        "nova_raw_seek",
        "stats->buffer2_used",
    )
    missing = [token for token in required if token not in text]
    if missing:
        raise RuntimeError("raw prefetch postcondition missing: " + repr(missing))
    forbidden = (
        "ff_p->buffer_size" + " = s->rebuffer_capacity_bytes",
    )
    present = [token for token in forbidden if token in text]
    if present:
        raise RuntimeError("post-demux producer-wall residue remains: " + repr(present))

    path.write_text(text)


def patch_startup_trace(root: Path) -> None:
    """Observational startup milestones only; no buffering or scheduling changes."""
    avos = root / "Source" / "avos_mp_video.c"
    text = avos.read_text()
    text = replace_once(
        text,
        "\tint _flags = STREAM_PAUSED;\n",
        "\tint _flags = STREAM_PAUSED;\n"
        "\tint nova_trace_t0 = atime();\n"
        '\tserprintf("NOVA_STARTUP_TRACE open_begin t=%d starttime=%d\\n", nova_trace_t0, starttime);\n',
        "trace player open entry",
    )
    text = replace_once(
        text,
        "\tif (stream_open(video->s, src, etype, _flags)) {",
        '\tserprintf("NOVA_STARTUP_TRACE stream_open_begin t=%d elapsed=%d\\n", atime(), atime()-nova_trace_t0);\n'
        "\tif (stream_open(video->s, src, etype, _flags)) {",
        "trace stream open entry",
    )
    text = replace_once(
        text,
        "\tAV_set_state(AV_PLAYING, TYPE_VID, 0, video->s, NULL);",
        '\tserprintf("NOVA_STARTUP_TRACE stream_open_done t=%d elapsed=%d\\n", atime(), atime()-nova_trace_t0);\n'
        "\tAV_set_state(AV_PLAYING, TYPE_VID, 0, video->s, NULL);",
        "trace stream open return",
    )
    text = replace_once(
        text,
        "\tif (stream_start(video->s)) {",
        '\tserprintf("NOVA_STARTUP_TRACE stream_start_begin t=%d elapsed=%d\\n", atime(), atime()-nova_trace_t0);\n'
        "\tif (stream_start(video->s)) {",
        "trace stream start entry",
    )
    text = replace_once(
        text,
        "\tvideo->last_seekable = stream_seekable(video->s);",
        '\tserprintf("NOVA_STARTUP_TRACE stream_start_done t=%d elapsed=%d\\n", atime(), atime()-nova_trace_t0);\n'
        "\tvideo->last_seekable = stream_seekable(video->s);",
        "trace stream start return",
    )
    avos.write_text(text)

    ff = root / "Source" / "stream_parser_ffmpeg.c"
    text = ff.read_text()
    text = replace_once(
        text,
        "\tif( !(s->parser_priv = (FF_PRIV*)amalloc( sizeof( FF_PRIV ) ) ) ) {",
        '\tserprintf("NOVA_STARTUP_TRACE ff_open_begin t=%d\\n", atime());\n'
        "\tif( !(s->parser_priv = (FF_PRIV*)amalloc( sizeof( FF_PRIV ) ) ) ) {",
        "trace ffmpeg parser entry",
    )
    text = replace_once(
        text,
        "\tif( ffmpeg_open_input(ff_p, s->src.url, &ff_p->fmt_opts) != 0) {",
        '\tserprintf("NOVA_STARTUP_TRACE network_open_begin t=%d\\n", atime());\n'
        "\tif( ffmpeg_open_input(ff_p, s->src.url, &ff_p->fmt_opts) != 0) {",
        "trace network open start",
    )
    text = replace_once(
        text,
        'DBGP serprintf("info\\r\\n");',
        '\tserprintf("NOVA_STARTUP_TRACE network_open_done t=%d\\n", atime());\n'
        'DBGP serprintf("info\\r\\n");',
        "trace network open complete",
    )
    text = replace_once(
        text,
        "\t// Retrieve stream information\n",
        '\tserprintf("NOVA_STARTUP_TRACE probe_begin t=%d\\n", atime());\n'
        "\t// Retrieve stream information\n",
        "trace stream info start",
    )
    text = replace_once(
        text,
        "\tif (_parse_format(s->etype, ff_p)) goto ErrorExit4;",
        '\tserprintf("NOVA_STARTUP_TRACE probe_done t=%d streams=%d\\n", atime(), ff_p->fmt->nb_streams);\n'
        "\tif (_parse_format(s->etype, ff_p)) goto ErrorExit4;",
        "trace probe complete",
    )
    text = replace_once(
        text,
        "\tif( s->video->valid ) {\n\t\tff_p->need_key = 1;\n\t}",
        '\tserprintf("NOVA_STARTUP_TRACE parser_ready t=%d budget=%d\\n", atime(), ff_p->buffer_size);\n'
        "\tif( s->video->valid ) {\n\t\tff_p->need_key = 1;\n\t}",
        "trace parser ready",
    )
    ff.write_text(text)

    video = root / "Source" / "stream_video.c"
    text = video.read_text()
    text = replace_once(
        text,
        'serprintf("\\r\\nstream_start %s\\r\\n", s->src.url );',
        'serprintf("NOVA_STARTUP_TRACE native_stream_start t=%d\\n", atime());\n'
        'serprintf("\\r\\nstream_start %s\\r\\n", s->src.url );',
        "trace native stream start",
    )
    text = replace_once(
        text,
        "\t\t\t_check_sink_delay( s );\n\n\t\t\ts->current_frame     = frame;",
        '\t\t\tif( !__atomic_exchange_n( &s->startup_first_sink_logged, 1, __ATOMIC_ACQ_REL ) )\n'
        '\t\t\t\tserprintf("NOVA_STARTUP_TRACE first_frame_sink t=%d pts=%d\\n", atime(), frame->time);\n'
        "\t\t\t_check_sink_delay( s );\n\n\t\t\ts->current_frame     = frame;",
        "trace first sink frame",
    )
    video.write_text(text)


def apply(
    root: Path,
    report: Path | None = None,
    allow_unpinned_head: bool = False,
) -> dict:
    root = root.resolve()
    head = check_head(root, allow_unpinned_head)

    patch_stream_h(root / "Include" / "stream.h")
    patch_stream_video(root / "Source" / "stream_video.c")
    patch_stream_c(root / "Source" / "stream.c")
    patch_avos_mp_video(root / "Source" / "avos_mp_video.c")
    patch_stream_parser_ffmpeg(root / "Source" / "stream_parser_ffmpeg.c")
    patch_startup_trace(root)

    result = {
        "status": "PASS",
        "aos_avos_commit": head,
        "aos_avos_head_policy": "latest-structural" if allow_unpinned_head else "pinned",
        "architecture": "one independent native raw-source producer before FFmpeg demux; no Java FIFO and no parallel downloader",
        "network_wall": "fixed 128MiB raw warehouse only",
        "raw_io_bytes": 128 * 1024,
        "dynamic_buffer": "X=file bytes/duration seconds; playback low=2X, resume=5X; raw producer cap=fixed 128MiB",
        "fallback": {
            "low_bytes": LOW_BYTES,
            "resume_bytes": RESUME_BYTES,
            "capacity_bytes": CAPACITY_BYTES,
        },
        "packet_queue_role": "upstream FFmpeg handoff/safety queue only; never used as a producer wall",
        "packet_queue_is_producer_wall": False,
        "manual_pause_policy": "manual pause may stop parser/playback; independent raw producer continues until the fixed 128MiB warehouse is full",
        "internal_rebuffer_policy": "parser may continue only during automatic rebuffer; raw producer is independent in all states",
        "probe_policy": "one stable RAW custom AVIO is installed before avformat_open_input and remains the demuxer IO through probe, tail-moov discovery and runtime",
        "seek_policy": "single producer-owned source AVIO for probe and playback; seek serializes source, invalidates queued raw generation, no parallel downloader",
        "telemetry": ["NOVA_RAW128_OPEN", "NOVA_RAW128", "NOVA_RAW_FIXED128_POLICY", "NOVA_REBUFFER_ENTER", "NOVA_REBUFFER_WAIT", "NOVA_REBUFFER_EXIT", "NOVA_STARTUP_TRACE"],
        "mp4_tail_moov_safe": True,
        "mp4_runtime_seek_race_safe": True,
        "events": ["MEDIA_INFO_BUFFERING_START", "MEDIA_INFO_BUFFERING_END"],
        "extra_fixed_prefetch_wall_bytes": 0,
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument(
        "--allow-unpinned-head",
        action="store_true",
        help="Allow a newer aos-avos HEAD; exact patch anchors still fail closed.",
    )
    args = p.parse_args()
    print(json.dumps(apply(args.root, args.report, args.allow_unpinned_head), indent=2))


if __name__ == "__main__":
    main()
