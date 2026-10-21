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
//  10X belongs only to the pre-demux raw producer. 2X/5X are playback
//  decisions based on bytes already resident in the two bounded handoff
//  stages: the raw source queue plus the ordinary FFmpeg packet handoff queue.
//  Neither threshold controls the network producer; only raw 10X does.
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
                                    "NOVA_REBUFFER_ENTER: resident=%d raw=%d packet=%d low=%d resume=%d raw10x=%d\n",
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
                                "NOVA_REBUFFER_WAIT: resident=%d raw=%d packet=%d resume=%d raw10x=%d source_eof=%d user_paused=%d\n",
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
#define NOVA_RAW_CHUNK_BYTES          (128 * 1024)
#define NOVA_RAW_FALLBACK_LOW_BYTES   (24 * 1024 * 1024)
#define NOVA_RAW_FALLBACK_RESUME_BYTES (64 * 1024 * 1024)
#define NOVA_RAW_FALLBACK_CAP_BYTES   (128 * 1024 * 1024)

typedef struct NOVA_RAW_CHUNK {
    struct NOVA_RAW_CHUNK *next;
    int offset;
    int size;
    uint8_t data[NOVA_RAW_CHUNK_BYTES];
} NOVA_RAW_CHUNK;

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
    NOVA_RAW_CHUNK *head;
    NOVA_RAW_CHUNK *tail;
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
} NOVA_RAW_PREFETCH;
'''


RAW_CODE = r'''
static int nova_raw_interrupt(void *opaque)
{
    NOVA_RAW_PREFETCH *raw = (NOVA_RAW_PREFETCH *)opaque;
    if( !raw || !__atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) )
        return 1;
    return raw->upstream_interrupt.callback &&
           raw->upstream_interrupt.callback(raw->upstream_interrupt.opaque);
}

static void nova_raw_free_chunks_locked(NOVA_RAW_PREFETCH *raw)
{
    NOVA_RAW_CHUNK *chunk = raw->head;
    while( chunk ) {
        NOVA_RAW_CHUNK *next = chunk->next;
        afree(chunk);
        chunk = next;
    }
    raw->head = NULL;
    raw->tail = NULL;
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
        "NOVA_RAW10X: produced=%llu consumed=%llu raw_used=%lld capacity=%lld producerBps=%llu consumerBps=%llu eof=%d\n",
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
                                int low_bytes, int resume_bytes,
                                int capacity_bytes)
{
    if( !raw->enabled )
        return;
    pthread_mutex_lock(&raw->mutex);
    raw->low_bytes = low_bytes;
    raw->resume_bytes = resume_bytes;
    raw->capacity_bytes = capacity_bytes;
    pthread_cond_broadcast(&raw->can_write);
    pthread_mutex_unlock(&raw->mutex);
    raw->s->rebuffer_low_bytes = low_bytes;
    raw->s->rebuffer_resume_bytes = resume_bytes;
    raw->s->rebuffer_capacity_bytes = capacity_bytes;
}

static void *nova_raw_thread(void *opaque)
{
    NOVA_RAW_PREFETCH *raw = (NOVA_RAW_PREFETCH *)opaque;

    while( __atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) ) {
        int want = 0;
        unsigned generation = 0;

        pthread_mutex_lock(&raw->mutex);
        while( __atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) &&
               (raw->eof || raw->error ||
                raw->used_bytes >= raw->capacity_bytes) ) {
            nova_raw_log_locked(raw);
            pthread_cond_wait(&raw->can_write, &raw->mutex);
        }
        if( !__atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) ) {
            pthread_mutex_unlock(&raw->mutex);
            break;
        }
        int64_t room = raw->capacity_bytes - raw->used_bytes;
        want = room > NOVA_RAW_CHUNK_BYTES ?
            NOVA_RAW_CHUNK_BYTES : (int)room;
        generation = raw->generation;
        pthread_mutex_unlock(&raw->mutex);

        if( want <= 0 )
            continue;

        NOVA_RAW_CHUNK *chunk =
            (NOVA_RAW_CHUNK *)amalloc(sizeof(NOVA_RAW_CHUNK));
        if( !chunk ) {
            pthread_mutex_lock(&raw->mutex);
            raw->error = AVERROR(ENOMEM);
            pthread_cond_broadcast(&raw->can_read);
            pthread_mutex_unlock(&raw->mutex);
            continue;
        }
        chunk->next = NULL;
        chunk->offset = 0;
        chunk->size = 0;

        pthread_mutex_lock(&raw->source_mutex);
        int got = avio_read(raw->source, chunk->data, want);
        pthread_mutex_unlock(&raw->source_mutex);

        pthread_mutex_lock(&raw->mutex);
        if( generation != raw->generation ) {
            pthread_mutex_unlock(&raw->mutex);
            afree(chunk);
            continue;
        }

        if( got > 0 ) {
            chunk->size = got;
            if( raw->tail )
                raw->tail->next = chunk;
            else
                raw->head = chunk;
            raw->tail = chunk;
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

        afree(chunk);
        if( got == 0 || got == AVERROR_EOF ) {
            raw->eof = 1;
            raw->error = 0;
            __atomic_store_n(
                &raw->s->raw_prefetch_eof, 1, __ATOMIC_RELEASE );
        } else {
            raw->error = got;
        }
        nova_raw_log_locked(raw);
        pthread_cond_broadcast(&raw->can_read);
        pthread_mutex_unlock(&raw->mutex);
    }
    return NULL;
}

static int nova_raw_read(void *opaque, uint8_t *dst, int size)
{
    NOVA_RAW_PREFETCH *raw = (NOVA_RAW_PREFETCH *)opaque;
    if( size <= 0 )
        return AVERROR(EINVAL);

    pthread_mutex_lock(&raw->mutex);
    while( __atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) &&
           !raw->head && !raw->eof && !raw->error ) {
        pthread_cond_wait(&raw->can_read, &raw->mutex);
    }

    if( !raw->head ) {
        int ret = raw->error ? raw->error :
                  raw->eof ? AVERROR_EOF : AVERROR_EXIT;
        pthread_mutex_unlock(&raw->mutex);
        return ret;
    }

    int copied = 0;
    while( copied < size && raw->head ) {
        NOVA_RAW_CHUNK *chunk = raw->head;
        int available = chunk->size - chunk->offset;
        int take = MIN(size - copied, available);
        memcpy(dst + copied, chunk->data + chunk->offset, take);
        chunk->offset += take;
        copied += take;
        raw->used_bytes -= take;
        raw->consumed_bytes += take;
        raw->consumer_pos += take;

        if( chunk->offset == chunk->size ) {
            raw->head = chunk->next;
            if( !raw->head )
                raw->tail = NULL;
            afree(chunk);
        }
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
    pthread_mutex_lock(&raw->source_mutex);
    int64_t result = avio_seek(raw->source, target, SEEK_SET);
    if( result >= 0 ) {
        pthread_mutex_lock(&raw->mutex);
        raw->generation++;
        nova_raw_free_chunks_locked(raw);
        raw->consumer_pos = result;
        raw->eof = 0;
        raw->error = 0;
        __atomic_store_n(
            &raw->s->raw_prefetch_eof, 0, __ATOMIC_RELEASE );
        pthread_cond_broadcast(&raw->can_read);
        pthread_cond_broadcast(&raw->can_write);
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

    memset(raw, 0, sizeof(*raw));
    raw->s = s;
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

    AVDictionary *io_options = NULL;
    av_dict_copy(&io_options, *options, 0);
    AVIOInterruptCB interrupt = { nova_raw_interrupt, raw };
    ret = avio_open2(
        &raw->source, url, AVIO_FLAG_READ, &interrupt, &io_options );
    av_dict_free(&io_options);
    if( ret < 0 )
        goto fail;

    raw->source_size = avio_size(raw->source);

    unsigned char *buffer = av_malloc(NOVA_RAW_CHUNK_BYTES);
    if( !buffer ) {
        ret = AVERROR(ENOMEM);
        goto fail;
    }
    raw->consumer = avio_alloc_context(
        buffer, NOVA_RAW_CHUNK_BYTES, 0, raw,
        nova_raw_read, NULL, nova_raw_seek );
    if( !raw->consumer ) {
        av_free(buffer);
        ret = AVERROR(ENOMEM);
        goto fail;
    }
    raw->consumer->seekable = raw->source->seekable;

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
        "NOVA_RAW10X_OPEN: url=%s fallback_low=%d fallback_resume=%d fallback_capacity=%d source_size=%lld\n",
        url, NOVA_RAW_FALLBACK_LOW_BYTES,
        NOVA_RAW_FALLBACK_RESUME_BYTES,
        NOVA_RAW_FALLBACK_CAP_BYTES,
        (long long)raw->source_size );
    return 1;

fail:
    __atomic_store_n(&raw->run, 0, __ATOMIC_RELEASE);
    if( raw->consumer ) {
        av_freep(&raw->consumer->buffer);
        avio_context_free(&raw->consumer);
    }
    if( raw->source )
        avio_closep(&raw->source);
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
    nova_raw_free_chunks_locked(raw);
    pthread_mutex_unlock(&raw->mutex);

    if( raw->consumer ) {
        av_freep(&raw->consumer->buffer);
        avio_context_free(&raw->consumer);
    }
    if( raw->source )
        avio_closep(&raw->source);

    __atomic_store_n(&raw->s->raw_prefetch_enabled, 0, __ATOMIC_RELEASE);
    __atomic_store_n(&raw->s->raw_prefetch_eof, 0, __ATOMIC_RELEASE);
    pthread_cond_destroy(&raw->can_write);
    pthread_cond_destroy(&raw->can_read);
    pthread_mutex_destroy(&raw->source_mutex);
    pthread_mutex_destroy(&raw->mutex);
    raw->enabled = 0;
}
'''


DYNAMIC_POLICY = r'''
	s->duration = ff_p->duration;
	s->size     = ff_p->size;

    // One buffering policy, at the raw source:
    // X = average source bytes/second, low=2X, resume=5X, producer wall=10X.
    // The ordinary FFmpeg packet queue keeps its upstream handoff/safety bound
    // and is NOT resized to 10X.
    uint64_t nova_x = 0;
    const uint64_t nova_max_x = (uint64_t)(INT_MAX / 2) / 10;
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
        int capacity = NOVA_RAW_FALLBACK_CAP_BYTES;
        if (nova_x > 0) {
            low = (int)(2 * nova_x);
            resume = (int)(5 * nova_x);
            capacity = (int)(10 * nova_x);
        }
        nova_raw_set_policy(&ff_p->raw, low, resume, capacity);
        serprintf(
            "NOVA_RAW_10X_POLICY: mode=%s size=%llu duration_ms=%d x_bytes_per_sec=%llu low=%d resume=%d capacity=%d packet_handoff=%d\n",
            nova_x > 0 ? "average" : "fallback",
            (unsigned long long)s->size, s->duration,
            (unsigned long long)nova_x, low, resume, capacity,
            ff_p->buffer_size);
    } else {
        s->rebuffer_low_bytes = 0;
        s->rebuffer_resume_bytes = 0;
        s->rebuffer_capacity_bytes = 0;
    }
'''


def patch_stream_h(path: Path) -> None:
    text = path.read_text()
    text = replace_once(
        text,
        "\tSTREAM_DECODER_CHANGED,\n\tSTREAM_SUBTITLE_CLEARED,\n} STREAM_MESSAGE;",
        "\tSTREAM_DECODER_CHANGED,\n\tSTREAM_SUBTITLE_CLEARED,\n"
        "\tSTREAM_BUFFERING_START,\n\tSTREAM_BUFFERING_END,\n} STREAM_MESSAGE;",
        "STREAM_MESSAGE enum",
    )
    text = sub_once(
        text,
        r"(\n\s*int\s+fps_start;\n\s*int\s+fps_count;\n\s*void\s+\*surface_handle;\n)(\s*\n}\s*STREAM;)",
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
        "\tint\t\trebuffer_low_bytes;\n"
        "\tint\t\trebuffer_resume_bytes;\n"
        "\tint\t\trebuffer_capacity_bytes;\n"
        r"\2",
        "STREAM tail raw buffering fields",
    )
    path.write_text(text)


def patch_stream_video(path: Path) -> None:
    text = path.read_text()
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
    text = replace_once(
        text,
        "\tcase STREAM_SUBTITLE_CHANGED:\n"
        "\t\tsend_subtitle(mp, video);\n"
        "\t\tbreak;\n"
        "\tdefault:",
        "\tcase STREAM_SUBTITLE_CHANGED:\n"
        "\t\tsend_subtitle(mp, video);\n"
        "\t\tbreak;\n"
        "\tcase STREAM_BUFFERING_START:\n"
        "\t\tavos_mp_sendevent(mp, MEDIA_INFO, MEDIA_INFO_BUFFERING_START, 0);\n"
        "\t\tbreak;\n"
        "\tcase STREAM_BUFFERING_END:\n"
        "\t\tavos_mp_sendevent(mp, MEDIA_INFO, MEDIA_INFO_BUFFERING_END, 0);\n"
        "\t\tbreak;\n"
        "\tdefault:",
        "buffering media info",
    )
    text = replace_once(
        text,
        "int avos_mp_video_start(avos_mp_t *mp, avos_mp_video_t *video)\n"
        "{\n"
        "\tif (stream_is_paused(video->s))\n"
        "\t\tstream_un_pause_from_jni(video->s, 0);",
        "int avos_mp_video_start(avos_mp_t *mp, avos_mp_video_t *video)\n"
        "{\n"
        "\t__atomic_store_n(&video->s->rebuffer_play_requested, 1, __ATOMIC_RELEASE);\n"
        "\t__atomic_store_n(&video->s->rebuffer_frame_seen, 0, __ATOMIC_RELEASE);\n"
        "\tif (__atomic_load_n(&video->s->rebuffering, __ATOMIC_ACQUIRE)) {\n"
        "\t\t__atomic_store_n(&video->s->rebuffer_user_paused, 0, __ATOMIC_RELEASE);\n"
        "\t\treturn AVOS_ERR_OK;\n"
        "\t}\n"
        "\tif (stream_is_paused(video->s))\n"
        "\t\tstream_un_pause_from_jni(video->s, 0);",
        "real play arms raw rebuffer lifecycle",
    )
    text = replace_once(
        text,
        "int avos_mp_video_pause(avos_mp_t *mp, avos_mp_video_t *video)\n"
        "{\n"
        "\tif (is_stream_pauseable(mp, video))",
        "int avos_mp_video_pause(avos_mp_t *mp, avos_mp_video_t *video)\n"
        "{\n"
        "\t__atomic_store_n(&video->s->rebuffer_play_requested, 0, __ATOMIC_RELEASE);\n"
        "\t__atomic_store_n(&video->s->rebuffer_frame_seen, 0, __ATOMIC_RELEASE);\n"
        "\tif (__atomic_load_n(&video->s->rebuffering, __ATOMIC_ACQUIRE)) {\n"
        "\t\t__atomic_store_n(&video->s->rebuffer_user_paused, 1, __ATOMIC_RELEASE);\n"
        "\t\treturn AVOS_ERR_OK;\n"
        "\t}\n"
        "\tif (is_stream_pauseable(mp, video))",
        "manual pause stays independent from raw producer",
    )
    path.write_text(text)


def patch_stream_parser_ffmpeg(path: Path) -> None:
    text = path.read_text()

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
		int raw = 0;
		if (priv->s)
			raw = nova_raw_open(
				&priv->raw, priv->s, priv->fmt, url, options);
		if (raw < 0)
			return raw;
		if (raw > 0)
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
        "install source-layer dynamic 2X/5X/10X policy",
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
\t// the only normal 10X network-production wall.
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
        "NOVA_RAW10X_OPEN:",
        "NOVA_RAW10X:",
        "NOVA_RAW_10X_POLICY:",
        "NOVA_TS_BITRATE:",
        "nova_raw_thread",
        "nova_raw_seek",
        "stats->buffer2_used",
    )
    missing = [token for token in required if token not in text]
    if missing:
        raise RuntimeError("raw prefetch postcondition missing: " + repr(missing))
    forbidden = (
        "NOVA_10X_PACKET_CAP_BYPASS",
        "ff_p->buffer_size" + " = s->rebuffer_capacity_bytes",
    )
    present = [token for token in forbidden if token in text]
    if present:
        raise RuntimeError("post-demux 10X residue remains: " + repr(present))

    path.write_text(text)


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

    result = {
        "status": "PASS",
        "aos_avos_commit": head,
        "aos_avos_head_policy": "latest-structural" if allow_unpinned_head else "pinned",
        "architecture": "one independent native raw-source producer before FFmpeg demux; no Java FIFO and no parallel downloader",
        "network_wall": "dynamic raw 10X only",
        "raw_chunk_bytes": 128 * 1024,
        "dynamic_buffer": "X=file bytes/duration seconds; playback low=2X, resume=5X; raw producer cap=10X",
        "fallback": {
            "low_bytes": LOW_BYTES,
            "resume_bytes": RESUME_BYTES,
            "capacity_bytes": CAPACITY_BYTES,
        },
        "packet_queue_role": "upstream FFmpeg handoff/safety queue only; never resized to 10X",
        "packet_queue_10x": False,
        "manual_pause_policy": "manual pause may stop parser/playback; independent raw producer continues until raw 10X",
        "internal_rebuffer_policy": "parser may continue only during automatic rebuffer; raw producer is independent in all states",
        "seek_policy": "single source AVIO; seek serializes source, invalidates queued raw generation, no parallel Range",
        "telemetry": ["NOVA_RAW10X_OPEN", "NOVA_RAW10X", "NOVA_RAW_10X_POLICY", "NOVA_REBUFFER_ENTER", "NOVA_REBUFFER_WAIT", "NOVA_REBUFFER_EXIT"],
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
