
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

#include <libavformat/avio.h>
#include <libavutil/dict.h>
#include <libavutil/error.h>
#include "libbluray/bluray.h"

#define TAG "NovaTransport"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)
#define UDF_BLOCK 2048

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
    int64_t upstream_size;
    BLURAY *bd;
    uint64_t output_size;
    uint64_t duration_us;
    uint32_t clip_count;
} nova_session;

static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static nova_session *g_session = NULL;
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

static int upstream_read_blocks(void *handle, void *buf, int lba, int num_blocks)
{
    nova_session *s = (nova_session *)handle;
    if (!s || !buf || lba < 0 || num_blocks <= 0 || s->stopping)
        return -1;
    int64_t target = (int64_t)lba * UDF_BLOCK;
    int bytes = num_blocks * UDF_BLOCK;
    if (s->upstream_pos != target) {
        int64_t pos = avio_seek(s->upstream, target, SEEK_SET);
        if (pos < 0)
            return -1;
        s->upstream_pos = pos;
    }
    int got = read_exact(s->upstream, (uint8_t *)buf, bytes);
    if (got <= 0)
        return -1;
    s->upstream_pos += got;
    return got / UDF_BLOCK;
}

static int select_main_title(nova_session *s)
{
    int titles = bd_get_titles(s->bd, TITLES_RELEVANT, 180);
    if (titles <= 0)
        titles = bd_get_titles(s->bd, TITLES_RELEVANT, 0);
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
    s->stopping = 1;
    pthread_mutex_lock(&g_lock);
    while (s->active_calls > 0)
        pthread_cond_wait(&s->idle, &g_lock);
    pthread_mutex_unlock(&g_lock);

    pthread_mutex_lock(&s->io_lock);
    if (s->bd) {
        bd_close(s->bd);
        s->bd = NULL;
    }
    if (s->upstream) {
        avio_closep(&s->upstream);
        s->upstream = NULL;
    }
    pthread_mutex_unlock(&s->io_lock);
    pthread_mutex_destroy(&s->io_lock);
    pthread_cond_destroy(&s->idle);
    free(s);
}

static nova_session *session_create(const char *url, const char *headers, int iso)
{
    nova_session *s = calloc(1, sizeof(*s));
    if (!s)
        return NULL;
    s->upstream_pos = -1;
    s->upstream_size = -1;
    s->mode = iso ? NOVA_MODE_BLURAY_ISO : NOVA_MODE_FILE;
    pthread_mutex_init(&s->io_lock, NULL);
    pthread_cond_init(&s->idle, NULL);

    AVDictionary *opts = NULL;
    if (headers && *headers)
        av_dict_set(&opts, "headers", headers, 0);
    av_dict_set(&opts, "reconnect", "1", 0);
    av_dict_set(&opts, "reconnect_streamed", "1", 0);
    av_dict_set(&opts, "reconnect_at_eof", "0", 0);
    av_dict_set(&opts, "reconnect_delay_max", "3", 0);
    av_dict_set(&opts, "rw_timeout", "15000000", 0);

    AVIOInterruptCB cb = { .callback = transport_interrupt, .opaque = s };
    int rc = avio_open2(&s->upstream, url, AVIO_FLAG_READ, &cb, &opts);
    av_dict_free(&opts);
    if (rc < 0 || !s->upstream) {
        char err[128] = {0};
        av_strerror(rc, err, sizeof(err));
        LOGE("UPSTREAM_OPEN_FAIL rc=%d err=%s", rc, err);
        session_free(s);
        return NULL;
    }

    s->upstream_size = avio_size(s->upstream);
    int64_t origin = avio_seek(s->upstream, 0, SEEK_SET);
    if (origin < 0) {
        LOGE("UPSTREAM_SEEK0_FAIL rc=%" PRId64, origin);
        session_free(s);
        return NULL;
    }
    s->upstream_pos = origin;

    if (s->mode == NOVA_MODE_BLURAY_ISO) {
        s->bd = bd_init();
        if (!s->bd || !bd_open_stream(s->bd, s, upstream_read_blocks)) {
            LOGE("BLURAY_OPEN_FAIL");
            session_free(s);
            return NULL;
        }
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
        ret = avio_read(s->upstream, dst, size);
        if (ret > 0)
            s->upstream_pos += ret;
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
            ret = avio_seek(s->upstream, offset, whence);
            if (ret >= 0)
                s->upstream_pos = ret;
        }
    }
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

    pthread_mutex_lock(&g_lock);
    nova_session *old = g_session;
    fresh->generation = ++g_generation;
    g_session = fresh;
    pthread_mutex_unlock(&g_lock);

    if (old)
        session_free(old);

    char out[512];
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

    LOGI("OPEN_READY mode=%s generation=%" PRIu64 " size=%" PRIu64,
         fresh->mode == NOVA_MODE_BLURAY_ISO ? "iso" : "file",
         fresh->generation, fresh->output_size);
    return (*env)->NewStringUTF(env, out);
}
