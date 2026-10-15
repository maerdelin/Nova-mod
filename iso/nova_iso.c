#define _GNU_SOURCE
#include <jni.h>
#include <android/log.h>
#include <arpa/inet.h>
#include <errno.h>
#include <inttypes.h>
#include <netinet/in.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>
#include <time.h>

#include "libbluray/bluray.h"

#define TAG "NovaIso"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

#define UDF_BLOCK 2048
#define CACHE_BYTES (4 * 1024 * 1024)
#define CACHE_SLOTS 8
#define IO_CHUNK (256 * 1024)
#define HEADER_MAX 32768

typedef struct {
    uint8_t *data;
    int64_t start;
    size_t len;
    uint64_t last_use;
} iso_cache_slot;

typedef struct {
    int port;
    char path[4096];
    iso_cache_slot cache[CACHE_SLOTS];
    uint64_t cache_clock;
    uint64_t range_requests;
    uint64_t fetched_bytes;
    pthread_mutex_t lock;
} iso_input;

typedef struct {
    iso_input input;
    BLURAY *bd;
    uint64_t title_size;
    int listen_fd;
    int client_fd;
    int port;
    volatile int stopping;
    pthread_t thread;
    int thread_started;
    pthread_mutex_t io_lock;
} iso_session;

static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static iso_session *g_session = NULL;

static int64_t mono_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static int send_all(int fd, const void *buf, size_t len) {
    const uint8_t *p = (const uint8_t *)buf;
    while (len) {
        ssize_t n = send(fd, p, len, 0);
        if (n < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (n == 0) return -1;
        p += n;
        len -= (size_t)n;
    }
    return 0;
}

static int connect_loopback(int port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    struct sockaddr_in sa;
    memset(&sa, 0, sizeof(sa));
    sa.sin_family = AF_INET;
    sa.sin_port = htons((uint16_t)port);
    sa.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (connect(fd, (struct sockaddr *)&sa, sizeof(sa)) < 0) {
        close(fd);
        return -1;
    }
    return fd;
}

static int parse_local_url(const char *url, iso_input *in) {
    const char *prefix1 = "http://127.0.0.1:";
    const char *prefix2 = "http://localhost:";
    const char *p = NULL;
    if (!strncmp(url, prefix1, strlen(prefix1))) p = url + strlen(prefix1);
    else if (!strncmp(url, prefix2, strlen(prefix2))) p = url + strlen(prefix2);
    else return -1;

    char *end = NULL;
    long port = strtol(p, &end, 10);
    if (!end || port <= 0 || port > 65535 || *end != '/') return -1;
    if (strlen(end) >= sizeof(in->path)) return -1;
    in->port = (int)port;
    strcpy(in->path, end);
    return 0;
}

static ssize_t fetch_range(iso_input *in, int64_t start, size_t want, uint8_t *out) {
    uint64_t req_id = ++in->range_requests;
    int64_t t0 = mono_ms();
    LOGI("RANGE_BEGIN id=%" PRIu64 " start=%" PRId64 " want=%zu totalFetched=%" PRIu64,
         req_id, start, want, in->fetched_bytes);
    int fd = connect_loopback(in->port);
    if (fd < 0) {
        LOGE("RANGE_CONNECT_FAIL id=%" PRIu64 " start=%" PRId64 " errno=%d", req_id, start, errno);
        return -1;
    }

    uint64_t end = (uint64_t)start + want - 1;
    char req[8192];
    int q = snprintf(req, sizeof(req),
        "GET %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n"
        "Range: bytes=%" PRId64 "-%" PRIu64 "\r\nConnection: close\r\n\r\n",
        in->path, in->port, start, end);
    if (q <= 0 || (size_t)q >= sizeof(req) || send_all(fd, req, (size_t)q) < 0) {
        close(fd);
        return -1;
    }

    uint8_t header[HEADER_MAX];
    size_t used = 0;
    ssize_t body_at = -1;
    while (used < sizeof(header)) {
        ssize_t n = recv(fd, header + used, sizeof(header) - used, 0);
        if (n <= 0) { close(fd); return -1; }
        size_t old = used;
        used += (size_t)n;
        size_t begin = old > 3 ? old - 3 : 0;
        for (size_t i = begin; i + 3 < used; i++) {
            if (header[i] == '\r' && header[i+1] == '\n' &&
                header[i+2] == '\r' && header[i+3] == '\n') {
                body_at = (ssize_t)(i + 4);
                break;
            }
        }
        if (body_at >= 0) break;
    }
    if (body_at < 0) {
        LOGE("RANGE_HEADER_FAIL id=%" PRIu64 " start=%" PRId64, req_id, start);
        close(fd);
        return -1;
    }

    header[(size_t)body_at > 0 ? (size_t)body_at - 1 : 0] = 0;
    int status = 0;
    if (sscanf((char *)header, "HTTP/%*s %d", &status) != 1 || (status != 206 && status != 200)) {
        LOGE("RANGE_STATUS_FAIL id=%" PRIu64 " start=%" PRId64 " status=%d", req_id, start, status);
        close(fd);
        return -1;
    }
    LOGI("RANGE_HEADERS id=%" PRIu64 " start=%" PRId64 " status=%d headerMs=%" PRId64,
         req_id, start, status, mono_ms() - t0);

    size_t copied = used - (size_t)body_at;
    if (copied > want) copied = want;
    if (copied) memcpy(out, header + body_at, copied);

    while (copied < want) {
        ssize_t n = recv(fd, out + copied, want - copied, 0);
        if (n < 0) {
            if (errno == EINTR) continue;
            close(fd);
            return -1;
        }
        if (n == 0) break;
        copied += (size_t)n;
    }
    close(fd);
    in->fetched_bytes += copied;
    LOGI("RANGE_END id=%" PRIu64 " start=%" PRId64 " got=%zu ms=%" PRId64 " totalFetched=%" PRIu64,
         req_id, start, copied, mono_ms() - t0, in->fetched_bytes);
    return (ssize_t)copied;
}

static iso_cache_slot *cache_find(iso_input *in, int64_t byte_pos) {
    for (int i = 0; i < CACHE_SLOTS; i++) {
        iso_cache_slot *slot = &in->cache[i];
        if (slot->data && slot->len > 0 &&
            byte_pos >= slot->start &&
            byte_pos + UDF_BLOCK <= slot->start + (int64_t)slot->len) {
            slot->last_use = ++in->cache_clock;
            return slot;
        }
    }
    return NULL;
}

static iso_cache_slot *cache_victim(iso_input *in) {
    iso_cache_slot *victim = &in->cache[0];
    for (int i = 0; i < CACHE_SLOTS; i++) {
        iso_cache_slot *slot = &in->cache[i];
        if (!slot->data || slot->len == 0) return slot;
        if (slot->last_use < victim->last_use) victim = slot;
    }
    return victim;
}

static int cache_fill(iso_input *in, int64_t byte_pos, iso_cache_slot **out) {
    iso_cache_slot *slot = cache_victim(in);
    if (!slot->data) {
        slot->data = malloc(CACHE_BYTES);
        if (!slot->data) return -1;
    }

    int slot_index = (int)(slot - in->cache);
    int64_t aligned = (byte_pos / CACHE_BYTES) * CACHE_BYTES;
    LOGI("CACHE_MISS slot=%d byte=%" PRId64 " aligned=%" PRId64
         " evictStart=%" PRId64 " evictLen=%zu",
         slot_index, byte_pos, aligned, slot->start, slot->len);

    ssize_t got = fetch_range(in, aligned, CACHE_BYTES, slot->data);
    if (got < UDF_BLOCK || byte_pos < aligned ||
        byte_pos + UDF_BLOCK > aligned + got) {
        LOGE("CACHE_FILL_FAIL slot=%d byte=%" PRId64 " aligned=%" PRId64 " got=%zd",
             slot_index, byte_pos, aligned, got);
        slot->len = 0;
        return -1;
    }

    slot->start = aligned;
    slot->len = (size_t)got;
    slot->last_use = ++in->cache_clock;
    *out = slot;
    return 0;
}

static int iso_read_blocks(void *handle, void *buf, int lba, int num_blocks) {
    iso_input *in = (iso_input *)handle;
    if (!in || !buf || lba < 0 || num_blocks <= 0) return -1;

    pthread_mutex_lock(&in->lock);
    uint8_t *dst = (uint8_t *)buf;
    int done = 0;

    while (done < num_blocks) {
        int64_t byte_pos = (int64_t)(lba + done) * UDF_BLOCK;
        iso_cache_slot *slot = cache_find(in, byte_pos);
        if (!slot && cache_fill(in, byte_pos, &slot) < 0) break;

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
    }

    pthread_mutex_unlock(&in->lock);
    return done > 0 ? done : -1;
}

static int read_request(int fd, char *buf, size_t cap) {
    size_t used = 0;
    while (used + 1 < cap) {
        ssize_t n = recv(fd, buf + used, cap - used - 1, 0);
        if (n <= 0) return -1;
        size_t old = used;
        used += (size_t)n;
        buf[used] = 0;
        size_t begin = old > 3 ? old - 3 : 0;
        for (size_t i = begin; i + 3 < used; i++) {
            if (buf[i] == '\r' && buf[i+1] == '\n' && buf[i+2] == '\r' && buf[i+3] == '\n')
                return 0;
        }
    }
    return -1;
}

static const char *find_header(const char *req, const char *name) {
    size_t nl = strlen(name);
    const char *p = strstr(req, "\r\n");
    if (!p) return NULL;
    p += 2;
    while (*p) {
        const char *e = strstr(p, "\r\n");
        if (!e || e == p) return NULL;
        if ((size_t)(e - p) > nl && !strncasecmp(p, name, nl) && p[nl] == ':') {
            p += nl + 1;
            while (*p == ' ' || *p == '\t') p++;
            return p;
        }
        p = e + 2;
    }
    return NULL;
}

static int parse_range(const char *req, uint64_t size, uint64_t *start, uint64_t *end, int *partial) {
    *start = 0;
    *end = size ? size - 1 : 0;
    *partial = 0;
    const char *r = find_header(req, "Range");
    if (!r) return 0;
    if (strncasecmp(r, "bytes=", 6)) return -1;
    r += 6;
    char *tail = NULL;
    if (*r == '-') {
        uint64_t suffix = strtoull(r + 1, &tail, 10);
        if (!suffix || suffix > size) suffix = size;
        *start = size - suffix;
        *end = size - 1;
    } else {
        uint64_t a = strtoull(r, &tail, 10);
        if (tail == r || *tail != '-') return -1;
        *start = a;
        tail++;
        if (*tail >= '0' && *tail <= '9') {
            char *e2 = NULL;
            uint64_t b = strtoull(tail, &e2, 10);
            *end = b < size ? b : size - 1;
        } else {
            *end = size - 1;
        }
    }
    if (*start >= size || *end < *start) return -1;
    *partial = 1;
    return 0;
}

static int seek_exact(BLURAY *bd, uint64_t target) {
    int64_t pos = bd_seek(bd, target);
    if (pos < 0 || (uint64_t)pos > target) return -1;
    uint8_t discard[64 * 1024];
    while ((uint64_t)pos < target) {
        uint64_t left = target - (uint64_t)pos;
        int ask = (int)(left < sizeof(discard) ? left : sizeof(discard));
        int got = bd_read(bd, discard, ask);
        if (got <= 0) return -1;
        pos += got;
    }
    return 0;
}

static void serve_client(iso_session *s, int fd) {
    int64_t request_t0 = mono_ms();
    char req[HEADER_MAX];
    if (read_request(fd, req, sizeof(req)) < 0) return;

    char method[8] = {0};
    char path[1024] = {0};
    if (sscanf(req, "%7s %1023s HTTP/%*s", method, path) != 2) return;
    int is_head = !strcmp(method, "HEAD");
    if (strcmp(method, "GET") && !is_head) return;

    uint64_t start, end;
    int partial;
    if (!s->title_size || parse_range(req, s->title_size, &start, &end, &partial) < 0) {
        const char *bad = "HTTP/1.1 416 Range Not Satisfiable\r\nConnection: close\r\n\r\n";
        send_all(fd, bad, strlen(bad));
        return;
    }

    uint64_t count = end - start + 1;
    LOGI("PLAYER_REQ method=%s path=%s start=%" PRIu64 " end=%" PRIu64 " count=%" PRIu64 " partial=%d",
         method, path, start, end, count, partial);
    char hdr[1024];
    int n;
    if (partial) {
        n = snprintf(hdr, sizeof(hdr),
            "HTTP/1.1 206 Partial Content\r\n"
            "Content-Type: video/mp2t\r\nAccept-Ranges: bytes\r\n"
            "Content-Length: %" PRIu64 "\r\n"
            "Content-Range: bytes %" PRIu64 "-%" PRIu64 "/%" PRIu64 "\r\n"
            "Connection: close\r\n\r\n",
            count, start, end, s->title_size);
    } else {
        n = snprintf(hdr, sizeof(hdr),
            "HTTP/1.1 200 OK\r\nContent-Type: video/mp2t\r\n"
            "Accept-Ranges: bytes\r\nContent-Length: %" PRIu64 "\r\n"
            "Connection: close\r\n\r\n", count);
    }
    if (n <= 0 || send_all(fd, hdr, (size_t)n) < 0 || is_head) return;

    uint8_t *buf = malloc(IO_CHUNK);
    if (!buf) return;

    pthread_mutex_lock(&s->io_lock);
    LOGI("PLAYER_SEEK_BEGIN start=%" PRIu64, start);
    if (seek_exact(s->bd, start) < 0) {
        LOGE("PLAYER_SEEK_FAIL start=%" PRIu64, start);
        pthread_mutex_unlock(&s->io_lock);
        free(buf);
        return;
    }
    LOGI("PLAYER_SEEK_READY start=%" PRIu64 " ms=%" PRId64, start, mono_ms() - request_t0);

    uint64_t left = count;
    uint64_t sent = 0;
    int first_data = 1;
    while (left && !s->stopping) {
        int ask = (int)(left < IO_CHUNK ? left : IO_CHUNK);
        int got = bd_read(s->bd, buf, ask);
        if (got <= 0) {
            LOGE("PLAYER_BD_READ_STOP got=%d sent=%" PRIu64 " left=%" PRIu64, got, sent, left);
            break;
        }
        if (first_data) {
            LOGI("PLAYER_FIRST_DATA got=%d ms=%" PRId64, got, mono_ms() - request_t0);
            first_data = 0;
        }
        if (send_all(fd, buf, (size_t)got) < 0) {
            LOGI("PLAYER_SOCKET_CLOSED sent=%" PRIu64 " left=%" PRIu64, sent, left);
            break;
        }
        left -= (uint64_t)got;
        sent += (uint64_t)got;
        if (sent && (sent % (16ULL * 1024 * 1024)) < (uint64_t)got) {
            LOGI("PLAYER_PROGRESS sent=%" PRIu64 " left=%" PRIu64 " totalFetched=%" PRIu64,
                 sent, left, s->input.fetched_bytes);
        }
    }
    pthread_mutex_unlock(&s->io_lock);
    LOGI("PLAYER_REQ_END sent=%" PRIu64 " expected=%" PRIu64 " ms=%" PRId64 " totalFetched=%" PRIu64,
         sent, count, mono_ms() - request_t0, s->input.fetched_bytes);
    free(buf);
}

static void *server_main(void *opaque) {
    iso_session *s = (iso_session *)opaque;
    while (!s->stopping) {
        struct sockaddr_in peer;
        socklen_t plen = sizeof(peer);
        int fd = accept(s->listen_fd, (struct sockaddr *)&peer, &plen);
        if (fd < 0) {
            if (s->stopping) break;
            if (errno == EINTR) continue;
            break;
        }
        s->client_fd = fd;
        serve_client(s, fd);
        shutdown(fd, SHUT_RDWR);
        close(fd);
        s->client_fd = -1;
    }
    return NULL;
}

static void session_destroy(iso_session *s) {
    if (!s) return;
    s->stopping = 1;
    if (s->client_fd >= 0) shutdown(s->client_fd, SHUT_RDWR);
    if (s->listen_fd >= 0) {
        shutdown(s->listen_fd, SHUT_RDWR);
        close(s->listen_fd);
        s->listen_fd = -1;
    }
    if (s->thread_started) pthread_join(s->thread, NULL);
    if (s->bd) bd_close(s->bd);
    for (int i = 0; i < CACHE_SLOTS; i++) free(s->input.cache[i].data);
    pthread_mutex_destroy(&s->input.lock);
    pthread_mutex_destroy(&s->io_lock);
    free(s);
}

static iso_session *session_create(const char *url) {
    int64_t open_t0 = mono_ms();
    LOGI("OPEN_BEGIN url=%s", url);
    iso_session *s = calloc(1, sizeof(*s));
    if (!s) return NULL;
    s->listen_fd = -1;
    s->client_fd = -1;
    pthread_mutex_init(&s->input.lock, NULL);
    pthread_mutex_init(&s->io_lock, NULL);

    if (parse_local_url(url, &s->input) < 0) {
        session_destroy(s);
        return NULL;
    }

    s->bd = bd_init();
    LOGI("UDF_OPEN_BEGIN");
    if (!s->bd || !bd_open_stream(s->bd, &s->input, iso_read_blocks)) {
        LOGE("bd_open_stream failed");
        session_destroy(s);
        return NULL;
    }
    LOGI("UDF_OPEN_END ms=%" PRId64 " ranges=%" PRIu64 " fetched=%" PRIu64,
         mono_ms() - open_t0, s->input.range_requests, s->input.fetched_bytes);

    const BLURAY_DISC_INFO *di = bd_get_disc_info(s->bd);
    if (di && di->aacs_detected && !di->aacs_handled) {
        LOGE("AACS encrypted Blu-ray ISO is not supported");
        session_destroy(s);
        return NULL;
    }

    int64_t scan_t0 = mono_ms();
    LOGI("PLAYLIST_SCAN_BEGIN ranges=%" PRIu64 " fetched=%" PRIu64,
         s->input.range_requests, s->input.fetched_bytes);
    int titles = bd_get_titles(s->bd, TITLES_RELEVANT, 180);
    if (titles <= 0) titles = bd_get_titles(s->bd, TITLES_RELEVANT, 0);
    LOGI("PLAYLIST_SCAN_END titles=%d ms=%" PRId64 " ranges=%" PRIu64 " fetched=%" PRIu64,
         titles, mono_ms() - scan_t0, s->input.range_requests, s->input.fetched_bytes);
    if (titles <= 0) {
        LOGE("No Blu-ray titles found");
        session_destroy(s);
        return NULL;
    }

    int main_title = bd_get_main_title(s->bd);
    if (main_title < 0 || main_title >= titles) {
        uint64_t best = 0;
        main_title = 0;
        for (int i = 0; i < titles; i++) {
            BLURAY_TITLE_INFO *ti = bd_get_title_info(s->bd, (uint32_t)i, 0);
            if (ti) {
                if (ti->duration > best) { best = ti->duration; main_title = i; }
                bd_free_title_info(ti);
            }
        }
    }

    if (!bd_select_title(s->bd, (uint32_t)main_title)) {
        LOGE("bd_select_title(%d) failed", main_title);
        session_destroy(s);
        return NULL;
    }

    s->title_size = bd_get_title_size(s->bd);
    BLURAY_TITLE_INFO *ti = bd_get_title_info(s->bd, (uint32_t)main_title, 0);
    if (ti) {
        LOGI("MAIN_TITLE title=%d playlist=%05u duration=%" PRIu64 "s clips=%u size=%" PRIu64,
             main_title, ti->playlist, ti->duration / 90000, ti->clip_count, s->title_size);
        bd_free_title_info(ti);
    }
    if (!s->title_size) {
        LOGE("Selected Blu-ray title has zero size");
        session_destroy(s);
        return NULL;
    }

    s->listen_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (s->listen_fd < 0) { session_destroy(s); return NULL; }
    int one = 1;
    setsockopt(s->listen_fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in sa;
    memset(&sa, 0, sizeof(sa));
    sa.sin_family = AF_INET;
    sa.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    sa.sin_port = 0;
    if (bind(s->listen_fd, (struct sockaddr *)&sa, sizeof(sa)) < 0 ||
        listen(s->listen_fd, 8) < 0) {
        session_destroy(s);
        return NULL;
    }
    socklen_t sl = sizeof(sa);
    if (getsockname(s->listen_fd, (struct sockaddr *)&sa, &sl) < 0) {
        session_destroy(s);
        return NULL;
    }
    s->port = ntohs(sa.sin_port);
    if (pthread_create(&s->thread, NULL, server_main, s) != 0) {
        session_destroy(s);
        return NULL;
    }
    s->thread_started = 1;
    LOGI("OPEN_READY port=%d titleSize=%" PRIu64 " totalMs=%" PRId64 " ranges=%" PRIu64 " fetched=%" PRIu64,
         s->port, s->title_size, mono_ms() - open_t0, s->input.range_requests, s->input.fetched_bytes);
    return s;
}

JNIEXPORT jstring JNICALL
Java_com_archos_mediacenter_video_player_BlurayIsoProxy_nativeOpen(
        JNIEnv *env, jclass cls, jstring input_url) {
    (void)cls;
    const char *url = (*env)->GetStringUTFChars(env, input_url, NULL);
    if (!url) return NULL;

    pthread_mutex_lock(&g_lock);
    session_destroy(g_session);
    g_session = session_create(url);
    (*env)->ReleaseStringUTFChars(env, input_url, url);

    jstring result = NULL;
    if (g_session) {
        char out[128];
        snprintf(out, sizeof(out), "http://127.0.0.1:%d/main.m2ts", g_session->port);
        result = (*env)->NewStringUTF(env, out);
    }
    pthread_mutex_unlock(&g_lock);
    return result;
}

JNIEXPORT void JNICALL
Java_com_archos_mediacenter_video_player_BlurayIsoProxy_nativeClose(
        JNIEnv *env, jclass cls) {
    (void)env;
    (void)cls;
    pthread_mutex_lock(&g_lock);
    iso_session *old = g_session;
    g_session = NULL;
    session_destroy(old);
    pthread_mutex_unlock(&g_lock);
}

JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *vm, void *reserved) {
    (void)vm;
    (void)reserved;
    signal(SIGPIPE, SIG_IGN);
    return JNI_VERSION_1_6;
}
