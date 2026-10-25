
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
#include <strings.h>
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
    int64_t upstream_size;
    BLURAY *bd;
    uint64_t output_size;
    uint64_t duration_us;
    uint32_t clip_count;
    int iso_meta_active;
    int iso_meta_degraded;
    char *upstream_url;
    char *upstream_headers;
    /* NOVA_FILE_ORIGIN_FRESH_V1: keep the canonical WebDAV URL. The
     * initially resolved redirect target can expire during playback.
     * Refresh only FILE; ISO continues to use Run680's fixed path. */
    char *origin_url;
    char *origin_auth;
    JavaVM *resolver_vm;
    jclass resolver_class;
    jmethodID resolver_method;
    int requires_origin_refresh;
    /* NOVA_NONISO_SINGLE_GET_V1: live one-GET HTTP range via JNI.
     * ISO never uses these fields or callbacks. */
    int file_http_mode;
    jobject file_conn;
    jobject file_stream;
    jclass file_http_class;
    jmethodID file_http_open;
    jmethodID file_conn_disconnect;
    jmethodID file_stream_read;
    jmethodID file_stream_close;
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
static JavaVM *g_java_vm = NULL;
/* Implemented after the ISO metadata helpers, isolated from UDF/CLPI. */
static int nova_file_open_fresh_at(nova_session *s, int64_t target);
static int nova_file_java_open_at(nova_session *s,int64_t target);
static int nova_file_java_read(nova_session *s,uint8_t *dst,int bytes);
static void nova_file_java_close_active(nova_session *s);


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
static int nova_file_seek_retry(nova_session *s, int64_t target)
{
    if (target<0 || target>s->upstream_size) return AVERROR(EINVAL);
    /* Logical EOF seek is legal: no HTTP Range=bytes=size- request (416). */
    if(target==s->upstream_size){
        s->upstream_pos=target;
        return 0;
    }
    for (unsigned attempt=1; attempt<=3 && !s->stopping; ++attempt) {
        /* Refresh the logical WebDAV redirect BEFORE a new byte-range
         * request, not as a retry of an already expired signed URL. */
        if (s->requires_origin_refresh &&
            (!s->upstream || s->upstream_pos!=target ||
             s->upstream->error || s->upstream->eof_reached)) {
            int rc=nova_file_open_fresh_at(s,target);
            if(rc==0) return 0;
            LOGI("NOVA_FILE_FRESH_RANGE_FAIL_V1: at=%" PRId64
                 " result=%d",target,rc);
            if(nova_weak_terminal_error(rc)) return rc;
            if(attempt<3) nova_weak_backoff(s,attempt);
            continue;
        }
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


/* NOVA_FILE_ORIGIN_FRESH_V1: do not reuse the one-time redirect obtained
 * before playback. Java performs redirect resolution using the *original*
 * WebDAV URL and its Basic credential and strips Authorization on cross-
 * origin redirects. This prevents leaking the original WebDAV password to
 * a third-party CDN. Only FILE sessions hold these JNI references.
 */
static JNIEnv *nova_file_get_env(JavaVM *vm,int *needs_detach)
{
    *needs_detach=0;
    if(!vm) return NULL;
    JNIEnv *env=NULL;
    jint rc=(*vm)->GetEnv(vm,(void **)&env,JNI_VERSION_1_6);
    if(rc==JNI_OK) return env;
    if(rc!=JNI_EDETACHED) return NULL;
    if((*vm)->AttachCurrentThread(vm,&env,NULL)!=JNI_OK) return NULL;
    *needs_detach=1;
    return env;
}

static void nova_file_release_java(nova_session *s)
{
    if(s->file_http_mode){
        nova_file_java_close_active(s);
        if(s->file_http_class && s->resolver_vm){
            int detached=0;
            JNIEnv *env=nova_file_get_env(s->resolver_vm,&detached);
            if(env)(*env)->DeleteGlobalRef(env,s->file_http_class);
            if(detached)(*s->resolver_vm)->DetachCurrentThread(s->resolver_vm);
            s->file_http_class=NULL;
        }
    }
    if(s->resolver_class && s->resolver_vm){
        int detach=0;
        JNIEnv *env=nova_file_get_env(s->resolver_vm,&detach);
        if(env)(*env)->DeleteGlobalRef(env,s->resolver_class);
        if(detach)(*s->resolver_vm)->DetachCurrentThread(s->resolver_vm);
        s->resolver_class=NULL;
    }
    free(s->origin_url);
    free(s->origin_auth);
}

static int nova_file_refresh_origin(nova_session *s)
{
    if(s->mode!=NOVA_MODE_FILE || !s->requires_origin_refresh)
        return 0;
    if(!s->resolver_vm || !s->resolver_class ||
       !s->resolver_method || !s->origin_url)
        return AVERROR(EINVAL);
    int detached=0,ret=AVERROR(EIO);
    JNIEnv *env=nova_file_get_env(s->resolver_vm,&detached);
    if(!env)return ret;
    jstring src=(*env)->NewStringUTF(env,s->origin_url);
    jstring auth=(*env)->NewStringUTF(env,
                         s->origin_auth ? s->origin_auth : "");
    jobjectArray pair=NULL;
    jstring jurl=NULL,jauth=NULL;
    char *url=NULL,*headers=NULL;
    if(src && auth)
        pair=(jobjectArray)(*env)->CallStaticObjectMethod(env,
                  s->resolver_class,s->resolver_method,src,auth);
    if((*env)->ExceptionCheck(env)){
        (*env)->ExceptionClear(env);
        pair=NULL;
    }
    if(pair && (*env)->GetArrayLength(env,pair)>=2){
        jurl=(jstring)(*env)->GetObjectArrayElement(env,pair,0);
        jauth=(jstring)(*env)->GetObjectArrayElement(env,pair,1);
    }
    if(jurl){
        const char *value=(*env)->GetStringUTFChars(env,jurl,NULL);
        if(value && *value)url=strdup(value);
        if(value)(*env)->ReleaseStringUTFChars(env,jurl,value);
    }
    if(jauth){
        const char *value=(*env)->GetStringUTFChars(env,jauth,NULL);
        if(value){
            size_t n=strlen(value);
            if(n && n<8192){
                headers=malloc(n+18);
                if(headers)snprintf(headers,n+18,
                                     "Authorization: %s\r\n",value);
            }
            (*env)->ReleaseStringUTFChars(env,jauth,value);
        }
    }
    if(!headers)headers=strdup("");
    if(url && headers){
        free(s->upstream_url);
        free(s->upstream_headers);
        s->upstream_url=url;
        s->upstream_headers=headers;
        url=headers=NULL;
        ret=0;
    }
    free(url);free(headers);
    if(jauth)(*env)->DeleteLocalRef(env,jauth);
    if(jurl)(*env)->DeleteLocalRef(env,jurl);
    if(pair)(*env)->DeleteLocalRef(env,pair);
    if(auth)(*env)->DeleteLocalRef(env,auth);
    if(src)(*env)->DeleteLocalRef(env,src);
    if(detached)(*s->resolver_vm)->DetachCurrentThread(s->resolver_vm);
    if(ret==0)LOGI("NOVA_FILE_ORIGIN_REFRESH_V1: refreshed=1");
    return ret;
}

/* One fresh HTTP 206 connection opened AT the requested absolute byte.
 * Avoids a redundant GET-at-zero followed by a second range seek.
 * The committed FILE cursor is only advanced after an opened connection.
 * ISO's existing avio_seek/bd_seek path is NOT used or modified here. */
static int nova_file_open_fresh_at(nova_session *s,int64_t target)
{
    if(s->mode!=NOVA_MODE_FILE || target<0 ||
       target>=s->upstream_size)return AVERROR(EINVAL);
    int rc=nova_file_refresh_origin(s);
    if(rc<0)return rc;
    AVIOContext *fresh=NULL;
    AVDictionary *opts=NULL;
    char at[40];
    snprintf(at,sizeof(at),"%" PRId64,target);
    if(s->upstream_headers && *s->upstream_headers)
        av_dict_set(&opts,"headers",s->upstream_headers,0);
    av_dict_set(&opts,"offset",at,0);
    av_dict_set(&opts,"reconnect","0",0);
    av_dict_set(&opts,"rw_timeout","5000000",0);
    AVIOInterruptCB interrupt={
        .callback=transport_interrupt,.opaque=s
    };
    rc=avio_open2(&fresh,s->upstream_url,AVIO_FLAG_READ,&interrupt,&opts);
    av_dict_free(&opts);
    if(rc<0 || !fresh){
        if(fresh)avio_closep(&fresh);
        return rc<0?rc:AVERROR(EIO);
    }
    if(s->upstream)avio_closep(&s->upstream);
    s->upstream=fresh;
    s->upstream_pos=target;
    LOGI("NOVA_FILE_FRESH_RANGE_V1: at=%" PRId64 " result=ok",target);
    return 0;
}

static void nova_file_java_clear_exception(JNIEnv *env)
{
    if((*env)->ExceptionCheck(env)){
        (*env)->ExceptionClear(env);
    }
}

static void nova_file_java_close_active(nova_session *s)
{
    if(!s->file_conn && !s->file_stream)return;
    int detached=0;
    JNIEnv *env=nova_file_get_env(s->resolver_vm,&detached);
    if(env){
        if(s->file_stream){
            if(s->file_stream_close)
                (*env)->CallVoidMethod(env,s->file_stream,s->file_stream_close);
            nova_file_java_clear_exception(env);
            (*env)->DeleteGlobalRef(env,s->file_stream);
        }
        if(s->file_conn){
            if(s->file_conn_disconnect)
                (*env)->CallVoidMethod(env,s->file_conn,s->file_conn_disconnect);
            nova_file_java_clear_exception(env);
            (*env)->DeleteGlobalRef(env,s->file_conn);
        }
    }
    s->file_stream=NULL;
    s->file_conn=NULL;
    if(detached)(*s->resolver_vm)->DetachCurrentThread(s->resolver_vm);
}

static int nova_file_java_http_error(jint code)
{
    switch(code){
        case 400:return AVERROR_HTTP_BAD_REQUEST;
        case 401:return AVERROR_HTTP_UNAUTHORIZED;
        case 403:return AVERROR_HTTP_FORBIDDEN;
        case 404:return AVERROR_HTTP_NOT_FOUND;
        case 416:return AVERROR(EINVAL);
        default:return AVERROR(EIO);
    }
}

/* Verifies a real Content-Range START and immutable TOTAL before committing
 * the new connection/cursor. HTTP 200 for offset>0 is always rejected. */
static int nova_file_java_open_at(nova_session *s,int64_t target)
{
    if(!s->file_http_mode || !s->resolver_vm || !s->file_http_class ||
       !s->file_http_open || !s->origin_url || s->stopping ||
       target<0 || (s->upstream_size>=0 && target>=s->upstream_size))
        return AVERROR(EINVAL);
    int detached=0;
    int ret=AVERROR(EIO);
    JNIEnv *env=nova_file_get_env(s->resolver_vm,&detached);
    if(!env)return ret;
    jstring origin=(*env)->NewStringUTF(env,s->origin_url);
    jstring auth=(*env)->NewStringUTF(env,
                     s->origin_auth ? s->origin_auth : "");
    jobject conn=NULL,stream=NULL;
    jclass conn_class=NULL,stream_class=NULL;
    jstring header_name=NULL,content_range=NULL;
    int64_t file_size=-1;
    if(!origin || !auth)goto done;
    conn=(*env)->CallStaticObjectMethod(env,s->file_http_class,
           s->file_http_open,origin,auth,(jlong)target);
    if((*env)->ExceptionCheck(env)){
        nova_file_java_clear_exception(env);
        goto done;
    }
    if(!conn)goto done;
    conn_class=(*env)->GetObjectClass(env,conn);
    if(!conn_class)goto done;
    jmethodID get_code=(*env)->GetMethodID(env,conn_class,"getResponseCode","()I");
    jmethodID get_header=(*env)->GetMethodID(env,conn_class,"getHeaderField",
                                           "(Ljava/lang/String;)Ljava/lang/String;");
    jmethodID get_length=(*env)->GetMethodID(env,conn_class,"getContentLengthLong","()J");
    jmethodID get_input=(*env)->GetMethodID(env,conn_class,"getInputStream",
                                          "()Ljava/io/InputStream;");
    jmethodID disconnect=(*env)->GetMethodID(env,conn_class,"disconnect","()V");
    if(!get_code || !get_header || !get_length || !get_input || !disconnect){
        nova_file_java_clear_exception(env);
        goto done;
    }
    jint status=(*env)->CallIntMethod(env,conn,get_code);
    if((*env)->ExceptionCheck(env)){
        nova_file_java_clear_exception(env);
        goto done;
    }
    if(status!=206 && !(status==200 && target==0)){
        ret=nova_file_java_http_error(status);
        LOGI("NOVA_NONISO_SINGLE_GET_FAIL_V1: at=%" PRId64
             " http=%d error=%d",target,(int)status,ret);
        goto done;
    }
    header_name=(*env)->NewStringUTF(env,"Content-Range");
    if(!header_name)goto done;
    content_range=(jstring)(*env)->CallObjectMethod(env,conn,get_header,header_name);
    if((*env)->ExceptionCheck(env)){
        nova_file_java_clear_exception(env);
        goto done;
    }
    if(status==206){
        if(!content_range)goto done;
        const char *v=(*env)->GetStringUTFChars(env,content_range,NULL);
        if(!v)goto done;
        int64_t first=-1,last=-1,total=-1;
        int fields=sscanf(v,"bytes %" SCNd64 "-%" SCNd64 "/%" SCNd64,
                           &first,&last,&total);
        (*env)->ReleaseStringUTFChars(env,content_range,v);
        if(fields!=3 || first!=target || last<first ||
           total<=0 || last>=total){
            LOGI("NOVA_NONISO_BAD_RANGE_V1: requested=%" PRId64
                 " status=%d",target,(int)status);
            ret=AVERROR(EINVAL);
            goto done;
        }
        file_size=total;
    }else{
        jlong length=(*env)->CallLongMethod(env,conn,get_length);
        if((*env)->ExceptionCheck(env)){
            nova_file_java_clear_exception(env);
            goto done;
        }
        file_size=(int64_t)length;
        if(file_size<=0){
            ret=AVERROR(EINVAL);
            goto done;
        }
    }
    if(s->upstream_size>0 && file_size!=s->upstream_size){
        LOGI("NOVA_NONISO_SIZE_CHANGED_V1: expected=%" PRId64
             " got=%" PRId64,s->upstream_size,file_size);
        ret=AVERROR(EINVAL);
        goto done;
    }
    stream=(*env)->CallObjectMethod(env,conn,get_input);
    if((*env)->ExceptionCheck(env)){
        nova_file_java_clear_exception(env);
        goto done;
    }
    if(!stream)goto done;
    stream_class=(*env)->GetObjectClass(env,stream);
    if(!stream_class)goto done;
    jmethodID read=(*env)->GetMethodID(env,stream_class,"read","([BII)I");
    jmethodID close=(*env)->GetMethodID(env,stream_class,"close","()V");
    if(!read || !close){
        nova_file_java_clear_exception(env);
        goto done;
    }
    jobject live_conn=(*env)->NewGlobalRef(env,conn);
    jobject live_stream=(*env)->NewGlobalRef(env,stream);
    if(!live_conn || !live_stream){
        if(live_conn)(*env)->DeleteGlobalRef(env,live_conn);
        if(live_stream)(*env)->DeleteGlobalRef(env,live_stream);
        goto done;
    }
    /* Transactional commit: old connection stays valid until the fresh
     * exact-byte response has been validated and its stream is live. */
    nova_file_java_close_active(s);
    s->file_conn=live_conn;
    s->file_stream=live_stream;
    s->file_conn_disconnect=disconnect;
    s->file_stream_read=read;
    s->file_stream_close=close;
    s->upstream_size=file_size;
    s->upstream_pos=target;
    ret=0;
    LOGI("NOVA_NONISO_SINGLE_GET_V1: at=%" PRId64
         " http=%d size=%" PRId64,target,(int)status,file_size);
done:
    if(ret<0 && conn){
        jmethodID disconnect=s->file_conn_disconnect;
        if(!disconnect && conn_class)
            disconnect=(*env)->GetMethodID(env,conn_class,"disconnect","()V");
        if(disconnect)(*env)->CallVoidMethod(env,conn,disconnect);
        nova_file_java_clear_exception(env);
    }
    if(stream)(*env)->DeleteLocalRef(env,stream);
    if(conn)(*env)->DeleteLocalRef(env,conn);
    if(stream_class)(*env)->DeleteLocalRef(env,stream_class);
    if(conn_class)(*env)->DeleteLocalRef(env,conn_class);
    if(content_range)(*env)->DeleteLocalRef(env,content_range);
    if(header_name)(*env)->DeleteLocalRef(env,header_name);
    if(origin)(*env)->DeleteLocalRef(env,origin);
    if(auth)(*env)->DeleteLocalRef(env,auth);
    if(detached)(*s->resolver_vm)->DetachCurrentThread(s->resolver_vm);
    return ret;
}

static int nova_file_java_read(nova_session *s,uint8_t *dst,int bytes)
{
    if(!s->file_stream || !s->file_stream_read || !dst ||
       bytes<=0 || s->stopping)return AVERROR_EXIT;
    int detached=0;
    JNIEnv *env=nova_file_get_env(s->resolver_vm,&detached);
    if(!env)return AVERROR(EIO);
    int ask=bytes>65536 ? 65536 : bytes;
    if((int64_t)ask>s->upstream_size-s->file_cursor)
        ask=(int)(s->upstream_size-s->file_cursor);
    if(ask<=0){
        if(detached)(*s->resolver_vm)->DetachCurrentThread(s->resolver_vm);
        return AVERROR_EOF;
    }
    jbyteArray buf=(*env)->NewByteArray(env,ask);
    int ret=AVERROR(EIO);
    if(buf){
        jint got=(*env)->CallIntMethod(env,s->file_stream,
                                    s->file_stream_read,buf,0,ask);
        if(!(*env)->ExceptionCheck(env) && got>0 && got<=ask){
            (*env)->GetByteArrayRegion(env,buf,0,got,(jbyte *)dst);
            if(!(*env)->ExceptionCheck(env))ret=(int)got;
        }else{
            nova_file_java_clear_exception(env);
            if(got==-1 && s->file_cursor>=s->upstream_size)ret=AVERROR_EOF;
        }
        (*env)->DeleteLocalRef(env,buf);
    }
    nova_file_java_clear_exception(env);
    if(detached)(*s->resolver_vm)->DetachCurrentThread(s->resolver_vm);
    return ret;
}


/* NOVA_MKV_SINGLE_GET_V2: MKV only. Run687 TS/MP4/ISO AVIO remains unchanged.
 * Restart truncated reads exactly at committed byte, never at the old probe.
 */
static int nova_mkv_single_get_read(nova_session *s, uint8_t *dst, int bytes)
{
    if(s->stopping)return AVERROR_EXIT;
    if(s->file_cursor<0 || s->file_cursor>s->upstream_size)
        return AVERROR(EINVAL);
    if(s->file_cursor==s->upstream_size)return AVERROR_EOF;
    for(unsigned attempt=1;attempt<=3 && !s->stopping;++attempt){
        int64_t at=s->file_cursor;
        if(!s->file_stream || s->upstream_pos!=at){
            int opened=nova_file_java_open_at(s,at);
            if(opened<0){
                LOGI("NOVA_MKV_SINGLE_READ_FAIL_V2: phase=open at=%" PRId64
                     " attempt=%u rc=%d",at,attempt,opened);
                if(nova_weak_terminal_error(opened))return opened;
                if(attempt<3)nova_weak_backoff(s,attempt);
                continue;
            }
        }
        int got=nova_file_java_read(s,dst,bytes);
        if(got>0){
            s->file_cursor=at+got;
            s->upstream_pos=at+got;
            return got;
        }
        LOGI("NOVA_MKV_SINGLE_READ_FAIL_V2: phase=read at=%" PRId64
             " attempt=%u rc=%d",at,attempt,got);
        nova_file_java_close_active(s);
        s->upstream_pos=-1;
        if(got==AVERROR_HTTP_UNAUTHORIZED || got==AVERROR_HTTP_FORBIDDEN ||
           got==AVERROR_HTTP_NOT_FOUND || got==AVERROR(EACCES) ||
           got==AVERROR(ENOENT))return got;
        if(attempt<3)nova_weak_backoff(s,attempt);
    }
    return s->stopping ? AVERROR_EXIT : AVERROR(EAGAIN);
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
    nova_file_release_java(s);
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

static nova_session *session_create_file(JNIEnv *env,const char *url,
                                         const char *auth)
{
    nova_session *s=calloc(1,sizeof(*s));
    if(!s)return NULL;
    s->mode=NOVA_MODE_FILE;
    s->file_http_mode=1;
    s->resolver_vm=g_java_vm;
    s->upstream_pos=-1;
    s->upstream_size=-1;
    pthread_mutex_init(&s->io_lock,NULL);
    pthread_cond_init(&s->idle,NULL);
    s->origin_url=strdup(url ? url : "");
    s->origin_auth=strdup(auth ? auth : "");
    s->upstream_url=strdup(url ? url : "");
    s->upstream_headers=strdup("");
    if(!s->origin_url || !*s->origin_url || !s->origin_auth ||
       !s->upstream_url || !s->upstream_headers){
        session_free(s);
        return NULL;
    }
    jclass local=(*env)->FindClass(env,
        "com/archos/mediacenter/video/player/DirectRangeHttp");
    if(local){
        s->file_http_class=(jclass)(*env)->NewGlobalRef(env,local);
        (*env)->DeleteLocalRef(env,local);
    }else{
        nova_file_java_clear_exception(env);
    }
    if(s->file_http_class){
        s->file_http_open=(*env)->GetStaticMethodID(env,s->file_http_class,
            "open","(Ljava/lang/String;Ljava/lang/String;J)Ljava/net/HttpURLConnection;");
        nova_file_java_clear_exception(env);
    }
    if(!s->file_http_class || !s->file_http_open){
        LOGE("NOVA_NONISO_JAVA_RANGE_CLASS_MISSING");
        session_free(s);
        return NULL;
    }
    pthread_mutex_lock(&g_lock);
    if(g_opening_session)g_opening_session->stopping=1;
    g_opening_session=s;
    pthread_mutex_unlock(&g_lock);
    /* A temporary HTTP 503 at the first request cannot destroy playback
     * startup. The original logical resource remains authoritative;
     * only retry transient I/O, never 401/403/404 or corrupt ranges. */
    int startup_rc=AVERROR(EIO);
    for(int attempt=1;attempt<=3 && !s->stopping;++attempt){
        startup_rc=nova_file_java_open_at(s,0);
        if(startup_rc==0)break;
        if(nova_weak_terminal_error(startup_rc))break;
        if(attempt<3)nova_weak_backoff(s,(unsigned)attempt);
    }
    if(startup_rc<0 || s->upstream_size<=0){
        session_free(s);
        return NULL;
    }
    s->output_size=(uint64_t)s->upstream_size;
    s->file_cursor=0;
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
        ret = s->file_http_mode ? nova_mkv_single_get_read(s, dst, size)
                                : nova_upstream_read_some_retry(s, dst, size);
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
                int rc=s->file_http_mode ?
                  (target==s->upstream_size ? 0 : nova_file_java_open_at(s,target)) :
                  nova_file_seek_retry(s,target);
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


/* Match only the original logical path; ignore signed query parameters. */
static int nova_is_mkv_origin_url(const char *url)
{
    if(!url)return 0;
    const char *end=url+strlen(url);
    for(const char *p=url;*p;++p)
        if(*p=='?' || *p=='#'){end=p;break;}
    return end-url>=4 && strncasecmp(end-4,".mkv",4)==0;
}

JNIEXPORT jstring JNICALL
Java_com_archos_mediacenter_video_player_DirectTransportProxy_nativeOpen(
        JNIEnv *env, jclass cls, jstring jurl, jstring jheaders, jboolean jiso,
        jstring jorigin_url, jstring jorigin_auth)
{
    if (!jurl)
        return NULL;

    const char *url = (*env)->GetStringUTFChars(env, jurl, NULL);
    const char *headers = jheaders
        ? (*env)->GetStringUTFChars(env, jheaders, NULL) : NULL;

    /* NOVA_MKV_SINGLE_GET_V2: only canonical *.mkv selects single live GET.
     * All other formats preserve Run687 transport creation and credentials. */
    const char *origin=(!jiso && jorigin_url)
        ? (*env)->GetStringUTFChars(env,jorigin_url,NULL) : NULL;
    const char *original_auth=(!jiso && jorigin_auth)
        ? (*env)->GetStringUTFChars(env,jorigin_auth,NULL) : NULL;
    const int mkv=(!jiso && origin && nova_is_mkv_origin_url(origin));
    nova_session *fresh=mkv ?
        session_create_file(env,origin,original_auth ? original_auth : "") :
        session_create(url,headers ? headers : "",jiso ? 1 : 0);
    if(fresh && !jiso && origin && !mkv &&
       *origin && strcmp(origin,url)!=0){
            fresh->origin_url=strdup(origin);
            fresh->origin_auth=strdup(original_auth ? original_auth : "");
            fresh->resolver_vm=g_java_vm;
            jclass local=(*env)->FindClass(env,
                  "com/archos/mediacenter/video/player/DirectRedirectResolver");
            if(local){
                fresh->resolver_class=(jclass)(*env)->NewGlobalRef(env,local);
                (*env)->DeleteLocalRef(env,local);
            }else if((*env)->ExceptionCheck(env)){
                (*env)->ExceptionClear(env);
            }
            if(fresh->resolver_class)
                fresh->resolver_method=(*env)->GetStaticMethodID(env,
                    fresh->resolver_class,"resolve",
                    "(Ljava/lang/String;Ljava/lang/String;)[Ljava/lang/String;");
            if((*env)->ExceptionCheck(env))
                (*env)->ExceptionClear(env);
            if(!fresh->origin_url || !fresh->origin_auth ||
               !fresh->resolver_class || !fresh->resolver_method){
                LOGE("NOVA_FILE_ORIGIN_REFRESH_UNAVAILABLE_V1");
                session_free(fresh);
                fresh=NULL;
            }else{
                fresh->requires_origin_refresh=1;
                LOGI("NOVA_FILE_ORIGIN_FRESH_V1: enabled=1");
            }
    }
    if(original_auth)(*env)->ReleaseStringUTFChars(env,jorigin_auth,original_auth);
    if(origin)(*env)->ReleaseStringUTFChars(env,jorigin_url,origin);

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
    } else if(fresh->file_http_mode){
        snprintf(out,sizeof(out),
            "novatransport://%" PRIu64 "/stream?nova_direct=1"
            "&nova_generation=%" PRIu64 "&nova_source_size=%" PRIu64
            "&nova_mkv=1",
            fresh->generation,fresh->generation,fresh->output_size);
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
    g_java_vm=vm;
    (void)reserved;
    return JNI_VERSION_1_6;
}
