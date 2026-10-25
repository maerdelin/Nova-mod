
#define _GNU_SOURCE
#include <jni.h>
#include <android/log.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <libavformat/avio.h>
#include <libavutil/dict.h>
#include <libavutil/error.h>
#include "libbluray/bluray.h"

#define TAG "NovaTransport"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)
#define UDF_BLOCK 2048
/* Proven Run506 UDF metadata locality: 4 MiB per slot, eight LRU slots.
 * This is used ONLY before playback. The working RAW128 pipeline is untouched. */
#define NOVA_ISO_META_PAGE_BYTES (4 * 1024 * 1024)
#define NOVA_ISO_META_PAGE_COUNT 8
#define NOVA_ISO_WEAK_PAGE_BYTES (256 * 1024)
#define NOVA_WEAK_RETRY_MAX_DELAY_MS 3000

typedef struct nova_iso_meta_page {
    int64_t start;
    int length;
    uint64_t touched;
    uint8_t *data;
} nova_iso_meta_page;

static int64_t nova_iso_uptime_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

typedef enum {
    NOVA_MODE_FILE = 0,
    NOVA_MODE_BLURAY_ISO = 1,
} nova_mode;

typedef struct nova_session {
    uint64_t generation;
    volatile int stopping;
    int active_calls;
    pthread_cond_t idle;
    pthread_mutex_t io_lock;
    nova_mode mode;
    AVIOContext *upstream;
    int64_t upstream_pos;
    /* NOVA_NONISO_SEEK_HEAL_V1: committed media cursor survives transient
     * HTTP Range errors; only a successful seek/read may update it. */
    int64_t file_cursor;
    int file_range_probe_done; /* One non-ISO diagnostic per file playback. */
    int64_t upstream_size;
    BLURAY *bd;
    uint64_t output_size;
    uint64_t duration_us;
    uint32_t clip_count;
    int iso_meta_active;
    int iso_meta_degraded;
    char *upstream_url;
    char *upstream_headers;
    nova_iso_meta_page iso_meta_pages[NOVA_ISO_META_PAGE_COUNT];
    uint64_t iso_meta_tick;
    uint64_t iso_meta_reads;
    uint64_t iso_meta_hits;
    uint64_t iso_meta_misses;
    uint64_t iso_meta_fetched;
} nova_session;

static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static nova_session *g_session = NULL;
static nova_session *g_opening_session = NULL;
static uint64_t g_generation = 0;

static int transport_interrupt(void *opaque)
{
    nova_session *s = (nova_session *)opaque;
    return !s || s->stopping;
}

static int read_exact(AVIOContext *io, uint8_t *dst, int bytes)
{
    int done = 0;
    while (done < bytes) {
        int got = avio_read(io, dst + done, bytes - done);
        if (got <= 0)
            return done > 0 ? done : got;
        done += got;
    }
    return done;
}


/* The direct transport is seekable. A failed HTTP range is not a missing UDF
 * block: reopen and retry that exact byte offset, keeping prior cache pages.
 * Only explicit close/abort and permanent HTTP/format errors end this wait. */
static int nova_weak_terminal_error(int rc)
{
    return rc == AVERROR_HTTP_BAD_REQUEST ||
           rc == AVERROR_HTTP_UNAUTHORIZED ||
           rc == AVERROR_HTTP_FORBIDDEN ||
           rc == AVERROR_HTTP_NOT_FOUND ||
           rc == AVERROR(EACCES) || rc == AVERROR(ENOENT) ||
           rc == AVERROR(EINVAL) || rc == AVERROR(ENOSYS);
}

static void nova_weak_backoff(nova_session *s, unsigned failures)
{
    int ms = 250;
    for (unsigned i = 1; i < failures && ms < NOVA_WEAK_RETRY_MAX_DELAY_MS; ++i)
        ms = ms > NOVA_WEAK_RETRY_MAX_DELAY_MS / 2
            ? NOVA_WEAK_RETRY_MAX_DELAY_MS : ms * 2;
    while (ms > 0 && !s->stopping) {
        int step = ms > 100 ? 100 : ms;
        struct timespec ts = { .tv_sec = 0, .tv_nsec = step * 1000000L };
        nanosleep(&ts, NULL);
        ms -= step;
    }
}

static int nova_upstream_connect(nova_session *s)
{
    if (s->stopping)
        return AVERROR_EXIT;
    AVIOContext *fresh = NULL;
    AVDictionary *opts = NULL;
    if (s->upstream_headers && *s->upstream_headers)
        av_dict_set(&opts, "headers", s->upstream_headers, 0);
    av_dict_set(&opts, "reconnect", "1", 0);
    av_dict_set(&opts, "reconnect_streamed", "1", 0);
    av_dict_set(&opts, "reconnect_at_eof", "0", 0);
    av_dict_set(&opts, "reconnect_delay_max", "3", 0);
    /* Reduce lock-holding time on a failed non-ISO range read only. */
    av_dict_set(&opts, "rw_timeout",
                s->mode == NOVA_MODE_FILE ? "5000000" : "15000000", 0);
    AVIOInterruptCB cb = { .callback = transport_interrupt, .opaque = s };
    int rc = avio_open2(&fresh, s->upstream_url, AVIO_FLAG_READ, &cb, &opts);
    av_dict_free(&opts);
    if (rc < 0 || !fresh) {
        if (fresh)
            avio_closep(&fresh);
        return rc < 0 ? rc : AVERROR(EIO);
    }
    if (s->upstream)
        avio_closep(&s->upstream);
    s->upstream = fresh;
    s->upstream_pos = 0;
    return 0;
}

static void nova_upstream_drop(nova_session *s)
{
    if (s->upstream)
        avio_closep(&s->upstream);
    s->upstream_pos = -1;
}

static int nova_upstream_open_until_ready(nova_session *s)
{
    unsigned failures = 0;
    while (!s->stopping) {
        int rc = nova_upstream_connect(s);
        if (rc >= 0) {
            int64_t size = avio_size(s->upstream);
            int64_t origin = size > 0 ? avio_seek(s->upstream, 0, SEEK_SET) : -1;
            if (size > 0 && origin == 0) {
                s->upstream_size = size;
                s->upstream_pos = 0;
                return 0;
            }
            rc = origin < 0 ? (int)origin : AVERROR(EIO);
        }
        if (nova_weak_terminal_error(rc)) {
            LOGE("NOVA_WEAKNET_TERMINAL phase=open rc=%d", rc);
            return -1;
        }
        ++failures;
        LOGI("NOVA_WEAKNET_RETRY phase=open count=%u rc=%d", failures, rc);
        nova_upstream_drop(s);
        nova_weak_backoff(s, failures);
    }
    return -1;
}

static int nova_upstream_seek_retry(nova_session *s, int64_t target)
{
    unsigned failures = 0;
    while (!s->stopping) {
        if (!s->upstream) {
            int rc = nova_upstream_connect(s);
            if (rc < 0) {
                if (nova_weak_terminal_error(rc))
                    return -1;
                ++failures;
                LOGI("NOVA_WEAKNET_RETRY phase=reconnect count=%u rc=%d at=%" PRId64,
                     failures, rc, target);
                nova_weak_backoff(s, failures);
                continue;
            }
        }
        if (s->upstream_pos == target)
            return 0;
        int64_t moved = avio_seek(s->upstream, target, SEEK_SET);
        if (moved == target) {
            s->upstream_pos = moved;
            return 0;
        }
        if (moved < 0 && nova_weak_terminal_error((int)moved))
            return -1;
        ++failures;
        LOGI("NOVA_WEAKNET_RETRY phase=seek count=%u at=%" PRId64 " result=%" PRId64,
             failures, target, moved);
        nova_upstream_drop(s);
        nova_weak_backoff(s, failures);
    }
    return -1;
}

static int nova_upstream_read_exact_retry(nova_session *s, uint8_t *dst,
                                          int64_t offset, int bytes)
{
    if (bytes <= 0 || offset < 0 ||
        s->upstream_size <= 0 || offset > s->upstream_size ||
        bytes > s->upstream_size - offset)
        return -1;
    int done = 0;
    unsigned failures = 0;
    while (!s->stopping && done < bytes) {
        if (nova_upstream_seek_retry(s, offset + done) < 0)
            return -1;
        int got = avio_read(s->upstream, dst + done, bytes - done);
        if (got > 0) {
            done += got;
            s->upstream_pos += got;
            failures = 0;
            continue;
        }
        if (got < 0 && nova_weak_terminal_error(got))
            return -1;
        ++failures;
        LOGI("NOVA_WEAKNET_RETRY phase=iso_read count=%u at=%" PRId64
             " remaining=%d rc=%d", failures, offset + done, bytes - done, got);
        nova_upstream_drop(s);
        nova_weak_backoff(s, failures);
    }
    return done == bytes ? done : -1;
}

/* NOVA_NONISO_SEEK_HEAL_V1: file-only transactional seek and reconnect.
 * A valid in-range byte seek can fail EINVAL after a stale HTTP Range stream.
 * Never reuse the failed AVIOContext; never advance file_cursor on error.
 * The ISO CLPI/time seek path remains separate and unmodified.
 */
/* NOVA_HTTP_RANGE_ROOT_DIAG_V1: independent protocol diagnosis, never
 * a retry or seek fallback. At the first EINVAL on a valid FILE seek,
 * issue two separate HTTP GETs (Range target and Range zero), compare
 * 32 bytes, and log only result codes/sizes. The active reader, offsets,
 * credentials and the established ISO seek are never altered. */
static int nova_file_sample_at(nova_session *s,int64_t offset,
                               uint8_t sample[32],int64_t *size)
{
    AVIOContext *probe=NULL;
    AVDictionary *opts=NULL;
    char pos[40];
    snprintf(pos,sizeof(pos),"%" PRId64,offset);
    if(s->upstream_headers && *s->upstream_headers)
        av_dict_set(&opts,"headers",s->upstream_headers,0);
    av_dict_set(&opts,"offset",pos,0);
    av_dict_set(&opts,"reconnect","0",0);
    av_dict_set(&opts,"rw_timeout","5000000",0);
    AVIOInterruptCB cb={.callback=transport_interrupt,.opaque=s};
    int rc=avio_open2(&probe,s->upstream_url,AVIO_FLAG_READ,&cb,&opts);
    av_dict_free(&opts);
    if(rc<0 || !probe){
        if(probe) avio_closep(&probe);
        return rc<0?rc:AVERROR(EIO);
    }
    *size=avio_size(probe);
    int got=avio_read(probe,sample,32);
    avio_closep(&probe);
    return got;
}

static void nova_file_probe_first_range_failure(nova_session *s,
    int64_t target,int64_t seek_rc,int original_error,
    int original_eof,int64_t original_tell)
{
    if(s->file_range_probe_done || s->stopping ||
       target<32 || target>=s->upstream_size) return;
    s->file_range_probe_done=1;
    uint8_t at[32]={0},zero[32]={0};
    int64_t at_size=-1,zero_size=-1;
    int at_rc=nova_file_sample_at(s,target,at,&at_size);
    int zero_rc=nova_file_sample_at(s,0,zero,&zero_size);
    int same=(at_rc==32 && zero_rc==32) ?
             (memcmp(at,zero,32)==0) : -1;
    LOGI("NOVA_HTTP_RANGE_ROOT_DIAG_V1: offset=%" PRId64
         " seek_rc=%" PRId64 " orig_err=%d orig_eof=%d"
         " orig_tell=%" PRId64 " fresh_at=%d fresh_zero=%d"
         " same32=%d expected_size=%" PRId64
         " at_size=%" PRId64 " zero_size=%" PRId64,
         target,seek_rc,original_error,original_eof,original_tell,
         at_rc,zero_rc,same,s->upstream_size,at_size,zero_size);
}

static int nova_file_seek_retry(nova_session *s, int64_t target)
{
    if (target<0 || target>s->upstream_size) return AVERROR(EINVAL);
    for (unsigned attempt=1; attempt<=3 && !s->stopping; ++attempt) {
        if (s->upstream &&
            (s->upstream->error || s->upstream->eof_reached)) {
            LOGI("NOVA_FILE_AVIO_REOPEN: at=%" PRId64
                 " err=%d eof=%d attempt=%u",target,
                 s->upstream->error,s->upstream->eof_reached,attempt);
            nova_upstream_drop(s);
        }
        if (!s->upstream) {
            int rc=nova_upstream_connect(s);
            if (rc<0) {
                LOGI("NOVA_FILE_SEEK_RETRY: phase=open at=%" PRId64
                     " attempt=%u rc=%d",target,attempt,rc);
                if (nova_weak_terminal_error(rc)) return rc;
                if (attempt<3) nova_weak_backoff(s,attempt);
                continue;
            }
        }
        if (s->upstream_pos==target) return 0;
        int original_error=s->upstream->error;
        int original_eof=s->upstream->eof_reached;
        int64_t original_tell=avio_tell(s->upstream);
        int64_t moved=avio_seek(s->upstream,target,SEEK_SET);
        if (moved==target) {
            s->upstream_pos=target;
            if (attempt>1)
                LOGI("NOVA_FILE_SEEK_RECOVERED: at=%" PRId64
                     " attempt=%u",target,attempt);
            return 0;
        }
        LOGI("NOVA_FILE_SEEK_RETRY: phase=seek at=%" PRId64
             " attempt=%u rc=%" PRId64,target,attempt,moved);
        if(moved==AVERROR(EINVAL))
            nova_file_probe_first_range_failure(s,target,moved,
                original_error,original_eof,original_tell);
        /* Even a failed HTTP seek can change protocol state. Drop it. */
        nova_upstream_drop(s);
        if (moved==AVERROR_HTTP_BAD_REQUEST ||
            moved==AVERROR_HTTP_UNAUTHORIZED ||
            moved==AVERROR_HTTP_FORBIDDEN ||
            moved==AVERROR_HTTP_NOT_FOUND ||
            moved==AVERROR(EACCES) || moved==AVERROR(ENOENT) ||
            moved==AVERROR(ENOSYS)) return (int)moved;
        if (attempt<3) nova_weak_backoff(s,attempt);
    }
    /* A finite error frees source_mutex so a new remote seek can proceed. */
    return s->stopping ? AVERROR_EXIT : AVERROR(EAGAIN);
}

static int nova_upstream_read_some_retry(nova_session *s, uint8_t *dst, int bytes)
{
    if (s->stopping) return AVERROR_EXIT;
    if (!dst || bytes<=0) return AVERROR(EINVAL);
    const int64_t at=s->file_cursor;
    if (at<0 || at>s->upstream_size) return AVERROR(EINVAL);
    if (at==s->upstream_size) return AVERROR_EOF;
    for (unsigned attempt=1; attempt<=3 && !s->stopping; ++attempt) {
        int rc=nova_file_seek_retry(s,at);
        if (rc<0) {
            LOGI("NOVA_FILE_READ_RETRY: phase=seek at=%" PRId64
                 " attempt=%u rc=%d",at,attempt,rc);
            if (rc==AVERROR_HTTP_UNAUTHORIZED ||
                rc==AVERROR_HTTP_FORBIDDEN ||
                rc==AVERROR_HTTP_NOT_FOUND ||
                rc==AVERROR(EACCES) || rc==AVERROR(ENOENT) ||
                rc==AVERROR(ENOSYS)) return rc;
            return s->stopping ? AVERROR_EXIT : AVERROR(EAGAIN);
        }
        int got=avio_read(s->upstream,dst,bytes);
        if (got>0) {
            s->upstream_pos=at+got;
            s->file_cursor=at+got;
            return got;
        }
        if (got==AVERROR_HTTP_UNAUTHORIZED ||
            got==AVERROR_HTTP_FORBIDDEN ||
            got==AVERROR_HTTP_NOT_FOUND ||
            got==AVERROR(EACCES) || got==AVERROR(ENOENT)) return got;
        /* Early EOF below known file size is a broken stream, not EOF. */
        LOGI("NOVA_FILE_READ_RETRY: phase=read at=%" PRId64
             " attempt=%u rc=%d",at,attempt,got);
        nova_upstream_drop(s);
        if (attempt<3) nova_weak_backoff(s,attempt);
    }
    return s->stopping ? AVERROR_EXIT : AVERROR(EAGAIN);
}

/* ISO_META_CACHE_BEGIN
 * Only UDF indexing / playlist scanning. Never a movie data buffer.
 */
static void nova_iso_meta_release(nova_session *s)
{
    if (!s) return;
    s->iso_meta_active = 0;
    for (int i = 0; i < NOVA_ISO_META_PAGE_COUNT; ++i) {
        free(s->iso_meta_pages[i].data);
        s->iso_meta_pages[i].data = NULL;
        s->iso_meta_pages[i].length = 0;
    }
}

static int nova_iso_meta_read(nova_session *s, uint8_t *dst, int64_t start, int bytes)
{
    if (!s->iso_meta_active || s->upstream_size <= 0 ||
        start < 0 || bytes <= 0 || start > s->upstream_size ||
        (int64_t)bytes > s->upstream_size - start)
        return -1;
    ++s->iso_meta_reads;
    int copied = 0;
    while (copied < bytes) {
        int64_t pos = start + copied;
        int page_bytes = s->iso_meta_degraded ? NOVA_ISO_WEAK_PAGE_BYTES
                                               : NOVA_ISO_META_PAGE_BYTES;
        int64_t aligned = pos & ~((int64_t)page_bytes - 1);
        int hit = -1, first_free = -1, lru = -1;
        uint64_t oldest = UINT64_MAX;
        for (int i = 0; i < NOVA_ISO_META_PAGE_COUNT; ++i) {
            nova_iso_meta_page *entry = &s->iso_meta_pages[i];
            if (entry->data && entry->length > 0 &&
                pos >= entry->start && pos - entry->start < entry->length) {
                hit = i;
                break;
            }
            if (!entry->data && first_free < 0)
                first_free = i;
            if (entry->data && entry->touched < oldest) {
                oldest = entry->touched;
                lru = i;
            }
        }
        if (hit >= 0) {
            ++s->iso_meta_hits;
        } else {
            hit = first_free >= 0 ? first_free : lru;
            if (hit < 0) return -1;
            nova_iso_meta_page *entry = &s->iso_meta_pages[hit];
            /* Stage the new range separately. Never overwrite an LRU page
             * until the network fetch has actually returned useful bytes.
             * Otherwise one transient timeout destroys already-good metadata
             * that libbluray may need later in the same title scan. */
            uint8_t *staging = malloc((size_t)page_bytes);
            if (!staging) return -1;
            int64_t moved = avio_seek(s->upstream, aligned, SEEK_SET);
            if (moved != aligned) {
                free(staging);
                s->iso_meta_degraded = 1;
                return -1;
            }
            s->upstream_pos = moved;
            int64_t remaining = s->upstream_size - aligned;
            int request = (int)(remaining < page_bytes ?
                                remaining : page_bytes);
            int got = read_exact(s->upstream, staging, request);
            if (got <= 0) {
                free(staging);
                s->iso_meta_degraded = 1;
                return -1;
            }
            s->upstream_pos += got;
            if (got < request)
                s->iso_meta_degraded = 1;
            free(entry->data);
            entry->data = staging;
            entry->start = aligned;
            entry->length = got;
            ++s->iso_meta_misses;
            s->iso_meta_fetched += (uint64_t)got;
        }
        nova_iso_meta_page *entry = &s->iso_meta_pages[hit];
        entry->touched = ++s->iso_meta_tick;
        /* Hits can be older 4 MiB pages while new requests use 256 KiB. */
        int offset = (int)(pos - entry->start);
        int available = entry->length - offset;
        if (available <= 0) {
            s->iso_meta_degraded = 1;
            return -1;
        }
        int chunk = bytes - copied;
        if (chunk > available) chunk = available;
        memcpy(dst + copied, entry->data + offset, (size_t)chunk);
        copied += chunk;
    }
    return copied / UDF_BLOCK;
}
/* ISO_META_CACHE_END */

static int upstream_read_blocks(void *handle, void *buf, int lba, int num_blocks)
{
    nova_session *s = (nova_session *)handle;
    if (!s || !buf || lba < 0 || num_blocks <= 0 ||
        num_blocks > INT32_MAX / UDF_BLOCK || s->stopping)
        return -1;
    int64_t target = (int64_t)lba * UDF_BLOCK;
    int bytes = num_blocks * UDF_BLOCK;
    if (s->iso_meta_active && s->upstream_size > 0) {
        int blocks = nova_iso_meta_read(s, (uint8_t *)buf, target, bytes);
        if (blocks > 0)
            return blocks;
        LOGI("ISO_META_CACHE: fallback_direct=1 start=%" PRId64
             " retain_pages=1 weak_page_bytes=%d", target, NOVA_ISO_WEAK_PAGE_BYTES);
        s->iso_meta_degraded = 1;
    }
    /* Demand-read only the requested UDF blocks, reconnecting at the exact
     * byte offset after transient errors. Previously cached pages survive. */
    int got = nova_upstream_read_exact_retry(s, (uint8_t *)buf, target, bytes);
    return got == bytes ? num_blocks : -1;
}

static int select_main_title(nova_session *s)
{
    int64_t scan_start_ms = nova_iso_uptime_ms();
    int titles = bd_get_titles(s->bd, TITLES_RELEVANT, 180);
    if (titles <= 0)
        titles = bd_get_titles(s->bd, TITLES_RELEVANT, 0);
    LOGI("ISO_OPEN_STAGE titles_scan_ms=%" PRId64 " titles=%d",
         nova_iso_uptime_ms() - scan_start_ms, titles);
    if (titles <= 0)
        return -1;
    int main_title = bd_get_main_title(s->bd);
    if (main_title < 0 || main_title >= titles) {
        uint64_t best = 0;
        main_title = 0;
        for (int i = 0; i < titles; ++i) {
            BLURAY_TITLE_INFO *ti = bd_get_title_info(s->bd, (uint32_t)i, 0);
            if (!ti)
                continue;
            if (ti->duration > best) {
                best = ti->duration;
                main_title = i;
            }
            bd_free_title_info(ti);
        }
    }
    int64_t select_start_ms = nova_iso_uptime_ms();
    if (!bd_select_title(s->bd, (uint32_t)main_title))
        return -1;
    s->output_size = bd_get_title_size(s->bd);
    BLURAY_TITLE_INFO *ti = bd_get_title_info(s->bd, (uint32_t)main_title, 0);
    if (ti) {
        s->clip_count = ti->clip_count;
        if (ti->duration >= 10ULL * 90000 &&
            ti->duration <= 24ULL * 3600 * 90000)
            s->duration_us = (ti->duration * 100) / 9;
        LOGI("MAIN_TITLE title=%d playlist=%05u duration=%" PRIu64
             "s clips=%u size=%" PRIu64,
             main_title, ti->playlist, ti->duration / 90000,
             ti->clip_count, s->output_size);
        bd_free_title_info(ti);
    }
    LOGI("ISO_OPEN_STAGE title_select_info_ms=%" PRId64 " clips=%u",
         nova_iso_uptime_ms() - select_start_ms, s->clip_count);
    return s->output_size ? 0 : -1;
}


static nova_session *session_acquire(uint64_t generation)
{
    pthread_mutex_lock(&g_lock);
    nova_session *s = g_session;
    if (!s || s->generation != generation || s->stopping) {
        pthread_mutex_unlock(&g_lock);
        return NULL;
    }
    s->active_calls++;
    pthread_mutex_unlock(&g_lock);
    return s;
}

static void session_release(nova_session *s)
{
    pthread_mutex_lock(&g_lock);
    if (s->active_calls > 0)
        s->active_calls--;
    if (s->active_calls == 0)
        pthread_cond_broadcast(&s->idle);
    pthread_mutex_unlock(&g_lock);
}

static void session_free(nova_session *s)
{
    if (!s)
        return;
    pthread_mutex_lock(&g_lock);
    if (g_opening_session == s)
        g_opening_session = NULL;
    s->stopping = 1;
    pthread_mutex_unlock(&g_lock);
    pthread_mutex_lock(&g_lock);
    while (s->active_calls > 0)
        pthread_cond_wait(&s->idle, &g_lock);
    pthread_mutex_unlock(&g_lock);

    pthread_mutex_lock(&s->io_lock);
    if (s->bd) {
        bd_close(s->bd);
        s->bd = NULL;
    }
    nova_iso_meta_release(s);
    if (s->upstream) {
        avio_closep(&s->upstream);
        s->upstream = NULL;
    }
    pthread_mutex_unlock(&s->io_lock);
    pthread_mutex_destroy(&s->io_lock);
    pthread_cond_destroy(&s->idle);
    free(s->upstream_url);
    free(s->upstream_headers);
    free(s);
}

static nova_session *session_create(const char *url, const char *headers, int iso)
{
    int64_t iso_start_ms = iso ? nova_iso_uptime_ms() : 0;
    int64_t stage_start_ms = iso_start_ms;
    nova_session *s = calloc(1, sizeof(*s));
    if (!s)
        return NULL;
    s->upstream_pos = -1;
    s->upstream_size = -1;
    s->mode = iso ? NOVA_MODE_BLURAY_ISO : NOVA_MODE_FILE;
    pthread_mutex_init(&s->io_lock, NULL);
    pthread_cond_init(&s->idle, NULL);

    s->upstream_url = strdup(url);
    s->upstream_headers = strdup(headers ? headers : "");
    if (!s->upstream_url || !s->upstream_headers) {
        session_free(s);
        return NULL;
    }
    /* Make an in-flight open cancellable by nativeClose, even before
     * publication of g_session. A newer open invalidates the prior one. */
    pthread_mutex_lock(&g_lock);
    if (g_opening_session)
        g_opening_session->stopping = 1;
    g_opening_session = s;
    pthread_mutex_unlock(&g_lock);
    if (nova_upstream_open_until_ready(s) < 0) {
        session_free(s);
        return NULL;
    }
    /* Temporary UDF scanning cache, OFF before first streaming byte. */
    if (iso && s->upstream_size > 0)
        s->iso_meta_active = 1;
    if (iso) {
        LOGI("ISO_OPEN_STAGE upstream_open_seek0_ms=%" PRId64,
             nova_iso_uptime_ms() - stage_start_ms);
        stage_start_ms = nova_iso_uptime_ms();
    }

    if (s->mode == NOVA_MODE_BLURAY_ISO) {
        s->bd = bd_init();
        if (!s->bd || !bd_open_stream(s->bd, s, upstream_read_blocks)) {
            LOGE("BLURAY_OPEN_FAIL");
            session_free(s);
            return NULL;
        }
        LOGI("ISO_OPEN_STAGE bd_init_open_ms=%" PRId64,
             nova_iso_uptime_ms() - stage_start_ms);
        stage_start_ms = nova_iso_uptime_ms();
        const BLURAY_DISC_INFO *di = bd_get_disc_info(s->bd);
        if (di && di->aacs_detected && !di->aacs_handled) {
            LOGE("AACS_UNSUPPORTED");
            session_free(s);
            return NULL;
        }
        if (select_main_title(s) < 0) {
            LOGE("BLURAY_MAIN_TITLE_FAIL");
            session_free(s);
            return NULL;
        }
        LOGI("ISO_OPEN_STAGE select_main_title_ms=%" PRId64 " total_native_ms=%" PRId64,
             nova_iso_uptime_ms() - stage_start_ms, nova_iso_uptime_ms() - iso_start_ms);
        LOGI("ISO_META_CACHE: reads=%" PRIu64 " hits=%" PRIu64
             " misses=%" PRIu64 " fetched_bytes=%" PRIu64
             " page_bytes=%d pages=%d phase=metadata_only",
             s->iso_meta_reads, s->iso_meta_hits, s->iso_meta_misses,
             s->iso_meta_fetched, NOVA_ISO_META_PAGE_BYTES, NOVA_ISO_META_PAGE_COUNT);
        /* ISO scan finished: remove metadata cache BEFORE RAW128 playback. */
        nova_iso_meta_release(s);
    } else {
        if (s->upstream_size <= 0) {
            LOGE("UPSTREAM_SIZE_INVALID size=%" PRId64, s->upstream_size);
            session_free(s);
            return NULL;
        }
        s->output_size = (uint64_t)s->upstream_size;
    }
    return s;
}

__attribute__((visibility("default")))
int nova_transport_read(uint64_t generation, uint8_t *dst, int size)
{
    if (!dst || size <= 0)
        return AVERROR(EINVAL);
    nova_session *s = session_acquire(generation);
    if (!s)
        return AVERROR_EXIT;

    pthread_mutex_lock(&s->io_lock);
    int ret;
    if (s->stopping) {
        ret = AVERROR_EXIT;
    } else if (s->mode == NOVA_MODE_BLURAY_ISO) {
        ret = bd_read(s->bd, dst, size);
        if (ret == 0)
            ret = AVERROR_EOF;
    } else {
        ret = nova_upstream_read_some_retry(s, dst, size);
    }
    pthread_mutex_unlock(&s->io_lock);
    session_release(s);
    return ret;
}


__attribute__((visibility("default")))
int64_t nova_transport_seek(uint64_t generation, int64_t offset, int whence)
{
    nova_session *s = session_acquire(generation);
    if (!s)
        return AVERROR_EXIT;

    pthread_mutex_lock(&s->io_lock);
    int64_t ret = AVERROR(EINVAL);
    if (whence == AVSEEK_SIZE) {
        ret = (int64_t)s->output_size;
    } else if (!s->stopping) {
        whence &= ~AVSEEK_FORCE;
        if (s->mode == NOVA_MODE_BLURAY_ISO) {
            int64_t current = bd_tell(s->bd);
            int64_t target = offset;
            if (whence == SEEK_CUR)
                target = current + offset;
            else if (whence == SEEK_END)
                target = (int64_t)s->output_size + offset;
            else if (whence != SEEK_SET)
                target = -1;

            if (target >= 0 && (uint64_t)target <= s->output_size) {
                ret = bd_seek(s->bd, (uint64_t)target);
                if (ret >= 0 && ret < target) {
                    uint8_t discard[64 * 1024];
                    while (ret < target) {
                        int ask = (int)((target - ret) < (int64_t)sizeof(discard)
                                        ? (target - ret) : (int64_t)sizeof(discard));
                        int got = bd_read(s->bd, discard, ask);
                        if (got <= 0) {
                            ret = AVERROR(EIO);
                            break;
                        }
                        ret += got;
                    }
                }
            }
        } else {
            int64_t target = offset;
            if (whence == SEEK_CUR)
                target = s->file_cursor + offset;
            else if (whence == SEEK_END)
                target = s->upstream_size + offset;
            else if (whence != SEEK_SET)
                target = -1;
            if (target>=0 && target<=s->upstream_size) {
                int rc=nova_file_seek_retry(s,target);
                if (rc==0) {
                    s->file_cursor=target;
                    ret=target;
                } else {
                    ret=rc;
                    LOGI("NOVA_FILE_SEEK_FAIL: requested=%" PRId64
                         " committed=%" PRId64 " rc=%d",
                         target,s->file_cursor,rc);
                }
            }
        }
    }
    if (whence != AVSEEK_SIZE)
        LOGI("SEEK generation=%" PRIu64 " offset=%" PRId64 " whence=%d result=%" PRId64,
             generation, offset, whence, ret);
    pthread_mutex_unlock(&s->io_lock);
    session_release(s);
    return ret;
}

__attribute__((visibility("default")))
int64_t nova_transport_size(uint64_t generation)
{
    nova_session *s = session_acquire(generation);
    if (!s)
        return AVERROR_EXIT;
    int64_t size = (int64_t)s->output_size;
    session_release(s);
    return size;
}

__attribute__((visibility("default")))
int nova_transport_abort(uint64_t generation)
{
    pthread_mutex_lock(&g_lock);
    nova_session *s = g_session;
    if (!s || s->generation != generation) {
        pthread_mutex_unlock(&g_lock);
        return 0;
    }
    s->stopping = 1;
    pthread_mutex_unlock(&g_lock);
    LOGI("ABORT generation=%" PRIu64, generation);
    return 1;
}

JNIEXPORT jstring JNICALL
Java_com_archos_mediacenter_video_player_DirectTransportProxy_nativeOpen(
        JNIEnv *env, jclass cls, jstring jurl, jstring jheaders, jboolean jiso)
{
    (void)cls;
    if (!jurl)
        return NULL;

    const char *url = (*env)->GetStringUTFChars(env, jurl, NULL);
    const char *headers = jheaders
        ? (*env)->GetStringUTFChars(env, jheaders, NULL) : NULL;

    nova_session *fresh = session_create(url, headers ? headers : "", jiso ? 1 : 0);

    if (headers)
        (*env)->ReleaseStringUTFChars(env, jheaders, headers);
    (*env)->ReleaseStringUTFChars(env, jurl, url);
    if (!fresh)
        return NULL;

    char out[512];
    pthread_mutex_lock(&g_lock);
    if (fresh->stopping || g_opening_session != fresh) {
        pthread_mutex_unlock(&g_lock);
        session_free(fresh);
        return NULL;
    }
    g_opening_session = NULL;
    nova_session *old = g_session;
    fresh->generation = ++g_generation;
    g_session = fresh;
    /* Snapshot the new URI while it cannot be closed by another thread. */
    if (fresh->mode == NOVA_MODE_BLURAY_ISO) {
        snprintf(out, sizeof(out),
            "novatransport://%" PRIu64 "/main.m2ts?mpegts&nova_direct=1"
            "&nova_iso=1&nova_iso_duration_us=%" PRIu64
            "&nova_iso_generation=%" PRIu64
            "&nova_iso_clip_count=%u&nova_iso_title_size=%" PRIu64,
            fresh->generation, fresh->duration_us, fresh->generation,
            fresh->clip_count, fresh->output_size);
    } else {
        snprintf(out, sizeof(out),
            "novatransport://%" PRIu64 "/stream?nova_direct=1"
            "&nova_generation=%" PRIu64 "&nova_source_size=%" PRIu64,
            fresh->generation, fresh->generation, fresh->output_size);
    }
    const uint64_t ready_generation = fresh->generation;
    const uint64_t ready_size = fresh->output_size;
    const int ready_iso = fresh->mode == NOVA_MODE_BLURAY_ISO;
    pthread_mutex_unlock(&g_lock);
    if (old)
        session_free(old);

    LOGI("OPEN_READY mode=%s generation=%" PRIu64 " size=%" PRIu64,
         ready_iso ? "iso" : "file", ready_generation, ready_size);
    return (*env)->NewStringUTF(env, out);
}


/* Detach under the same lock used by session_acquire. No new operation can
 * acquire this session after ABORT; CLOSE is emitted only after active calls
 * have drained and the upstream has actually been released. */
static void transport_close(uint64_t generation, int match_generation)
{
    pthread_mutex_lock(&g_lock);
    if (!match_generation && g_opening_session) {
        g_opening_session->stopping = 1;
        LOGI("NOVA_WEAKNET_CANCEL phase=pending_open");
    }
    nova_session *old = g_session;
    if (old && (!match_generation ||
                (generation > 0 && old->generation == generation))) {
        g_session = NULL;
        old->stopping = 1;
        LOGI("ABORT generation=%" PRIu64 " reason=close", old->generation);
    } else {
        old = NULL;
    }
    pthread_mutex_unlock(&g_lock);
    if (old) {
        uint64_t closed_generation = old->generation;
        session_free(old);
        LOGI("CLOSE generation=%" PRIu64 " complete=1", closed_generation);
    }
}

JNIEXPORT void JNICALL
Java_com_archos_mediacenter_video_player_DirectTransportProxy_nativeCloseGeneration(
        JNIEnv *env, jclass cls, jlong generation)
{
    (void)env;
    (void)cls;
    transport_close((uint64_t)generation, 1);
}

JNIEXPORT void JNICALL
Java_com_archos_mediacenter_video_player_DirectTransportProxy_nativeClose(
        JNIEnv *env, jclass cls)
{
    (void)env;
    (void)cls;
    transport_close(0, 0);
}

JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *vm, void *reserved)
{
    (void)vm;
    (void)reserved;
    return JNI_VERSION_1_6;
}
