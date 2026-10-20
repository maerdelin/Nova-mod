#!/usr/bin/env python3
"""Fail-closed P0 native/ISO binding and P2 optional resume-XML PUT isolation.

Apply --native after existing native patches; --iso before ISO compilation.
The smali entrypoint is called from webdav_parallel4_patch.apply before assembly.
No decoder, seek timeline, native 2X/5X/10X arithmetic or credential changes.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

CAP_HELPERS = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <limits.h>
#ifndef NOVA_RANGE4_CAP_ROOT
#define NOVA_RANGE4_CAP_ROOT "/data/user/0/org.courville.nova/cache/nova_range4_capacity"
#endif

static int nova_cap_decimal(const char **cursor, uint64_t limit, uint64_t *out) {
    const char *p = *cursor;
    uint64_t value = 0;
    if (*p < '0' || *p > '9') return 0;
    while (*p >= '0' && *p <= '9') {
        unsigned digit = (unsigned)(*p++ - '0');
        if (value > (limit - digit) / 10) return 0;
        value = value * 10 + digit;
    }
    *cursor = p; *out = value; return 1;
}
static int nova_cap_query(const char *query, const char *key, uint64_t limit, uint64_t *out) {
    if (!query) return 0;
    const char *arg = strstr(query, key);
    if (!arg || strstr(arg + strlen(key), key)) return 0;
    arg += strlen(key);
    return nova_cap_decimal(&arg, limit, out) && *out > 0 && (*arg == '\0' || *arg == '&');
}
static int nova_cap_identity(const char *url, const char *query, uint64_t media,
                             int *port, uint64_t *source_size) {
    const char *p = NULL;
    if (!url) return 0;
    if (!strncmp(url, "http://localhost:", 17)) p = url + 17;
    else if (!strncmp(url, "http://127.0.0.1:", 17)) p = url + 17;
    else return 0;
    uint64_t parsed_port = 0;
    if (!nova_cap_decimal(&p, 65535, &parsed_port) || !parsed_port || *p != '/') return 0;
    *port = (int)parsed_port; *source_size = media;
    const char *iso = query ? strstr(query, "&nova_iso=1") : NULL;
    if (iso && (iso[11] == '\0' || iso[11] == '&')) {
        uint64_t iso_port = 0, iso_size = 0;
        if (!nova_cap_query(query, "&nova_iso_source_port=", 65535, &iso_port) ||
            !nova_cap_query(query, "&nova_iso_source_size=", INT64_MAX, &iso_size)) return 0;
        *port = (int)iso_port; *source_size = iso_size;
    }
    return *source_size > 0 && *source_size <= INT64_MAX;
}
static int nova_cap_publish(const char *url, const char *query, uint64_t media, int capacity) {
    int port = 0; uint64_t source_size = 0;
    if (capacity <= 0 || capacity > INT_MAX / 2 ||
        !nova_cap_identity(url, query, media, &port, &source_size)) return 0;
    char dst[192], tmp[224];
    int n = snprintf(dst, sizeof(dst), "%s_%d", NOVA_RANGE4_CAP_ROOT, port);
    if (n <= 0 || (size_t)n >= sizeof(dst)) return 0;
    n = snprintf(tmp, sizeof(tmp), "%s.tmp.XXXXXX", dst);
    if (n <= 0 || (size_t)n >= sizeof(tmp)) return 0;
    int fd = mkstemp(tmp);
    if (fd < 0) return 0;
    FILE *fp = fdopen(fd, "w");
    if (!fp) { close(fd); unlink(tmp); return 0; }
    // A real LF, never the two-character backslash-n written by the old patch.
    int written = fprintf(fp, "%llu %d\n", (unsigned long long)source_size, capacity);
    int closed_ok = fclose(fp) == 0;
    if (written <= 0 || !closed_ok || rename(tmp, dst) != 0) { unlink(tmp); return 0; }
    return port;
}
'''

NATIVE_PUBLICATION = r'''    // P012: native title budget, bound to the underlying media proxy identity.
    {
        int nova_cap_port = nova_cap_publish(s->src.url, s->src_query,
                            (uint64_t)s->size, s->rebuffer_capacity_bytes);
        if (nova_cap_port)
            serprintf("NOVA_RANGE4_CAP_PUBLISH: mediaSize=%llu capacity=%d sourcePort=%d\n",
                      (unsigned long long)s->size, s->rebuffer_capacity_bytes, nova_cap_port);
        else
            serprintf("NOVA_RANGE4_CAP_PUBLISH_FAILED: invalid binding or file I/O\n");
    }
'''

ISO_HELPERS = r'''
// Extract only a valid, unique Content-Range total from an HTTP header block.
// Used for capacity identity, never for changing libbluray's title/seek timeline.
static int nova_iso_decimal(const char **cursor, uint64_t *out) {
    const char *p = *cursor; uint64_t value = 0;
    if (*p < '0' || *p > '9') return 0;
    while (*p >= '0' && *p <= '9') {
        unsigned digit = (unsigned)(*p++ - '0');
        if (value > ((uint64_t)INT64_MAX - digit) / 10) return 0;
        value = value * 10 + digit;
    }
    *cursor = p; *out = value; return 1;
}
static uint64_t nova_iso_range_total(const char *header) {
    uint64_t result = 0; int found = 0;
    const char *p = strstr(header, "\r\n");
    if (!p) return 0;
    p += 2;
    while (*p && *p != '\r' && *p != '\n') {
        const char *end = strstr(p, "\r\n");
        if (!end) return 0;
        if (end - p >= 14 && !strncasecmp(p, "Content-Range:", 14)) {
            if (++found > 1) return 0;
            char value[128]; size_t len = (size_t)(end - p - 14);
            if (len >= sizeof(value)) return 0;
            memcpy(value, p + 14, len); value[len] = 0;
            const char *q = value;
            while (*q == ' ' || *q == '\t') ++q;
            if (strncmp(q, "bytes ", 6)) return 0;
            q += 6;
            uint64_t first = 0, last = 0, total = 0;
            if (!nova_iso_decimal(&q, &first) || *q++ != '-' ||
                !nova_iso_decimal(&q, &last) || *q++ != '/' ||
                !nova_iso_decimal(&q, &total)) return 0;
            while (*q == ' ' || *q == '\t') ++q;
            if (*q || first > last || last >= total) return 0;
            result = total;
        }
        p = end + 2;
    }
    return result;
}
'''


def once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f'{label}: expected one anchor, found {text.count(old)}')
    return text.replace(old, new, 1)


def native_text(text: str) -> str:
    if 'static int nova_cap_publish(' in text:
        raise RuntimeError('P012 native publication already installed')
    begin = '    // Share the authoritative native 10X packet-queue capacity with the Java\n'
    start = text.find(begin)
    if start < 0 or text.count(begin) != 1:
        raise RuntimeError('Expected existing native publication block')
    # Stop only at the known final else branch of this publication block.
    end_anchor = r'''        } else {
            serprintf("NOVA_RANGE4_CAP_PUBLISH_FAILED: open\\n");
        }
    }
'''
    end = text.find(end_anchor, start)
    if end < 0:
        raise RuntimeError('Native publication end anchor missing')
    old = text[start:end + len(end_anchor)]
    for token in ('fprintf(fp, "%llu %d\\\\n"', 'rename(tmp, dst)', 's->rebuffer_capacity_bytes'):
        if token not in old:
            raise RuntimeError('Unexpected original publication: ' + token)
    text = once(text, old, NATIVE_PUBLICATION, 'native publisher')
    anchor = 'static int max_delay       = 100000;\n'
    return once(text, anchor, CAP_HELPERS + '\n' + anchor, 'native helper declarations')


def iso_text(text: str) -> str:
    if 'nova_iso_range_total(' in text:
        raise RuntimeError('P012 ISO identity already installed')
    text = once(text, '    char path[4096];\n',
                '    char path[4096];\n    uint64_t source_size; // underlying ISO, not selected title\n', 'ISO input identity')
    text = once(text, 'static ssize_t fetch_range(iso_input *in, int64_t start, size_t want, uint8_t *out) {',
                ISO_HELPERS + '\nstatic ssize_t fetch_range(iso_input *in, int64_t start, size_t want, uint8_t *out) {', 'ISO parser helper')
    capture = '''    if (status == 206) {
        uint64_t total = nova_iso_range_total((const char *)header);
        if (total) in->source_size = total;
    }
'''
    text = once(text, '    LOGI("RANGE_HEADERS id=%" PRIu64', capture + '    LOGI("RANGE_HEADERS id=%" PRIu64', 'ISO metadata total')
    text = once(text, '    size_t prefix = used - (size_t)body_at;\n',
                capture + '    size_t prefix = used - (size_t)body_at;\n', 'ISO playback total')
    text = once(text, '        char out[160];\n', '        char out[256];\n', 'ISO URL capacity')
    append = r'''        if (g_session->input.source_size) {
            size_t used = strlen(out);
            int added = snprintf(out + used, sizeof(out) - used,
                "&nova_iso_source_size=%" PRIu64 "&nova_iso_source_port=%d",
                g_session->input.source_size, g_session->input.port);
            if (added < 0 || (size_t)added >= sizeof(out) - used) out[used] = 0;
        }
'''
    return once(text, '        result = (*env)->NewStringUTF(env, out);\n',
                append + '        result = (*env)->NewStringUTF(env, out);\n', 'ISO source binding query')

SARDINE = 'Lcom/thegrizzlylabs/sardineandroid/impl/OkHttpSardine;'
POLICY = 'Lcom/archos/filecorelibrary/NovaWebdavSidecarPolicy;'
PUT_PROTO = '(Ljava/lang/String;Ljava/io/File;Ljava/lang/String;)V'
PUT_WRAPPER = f'''
.method public put{PUT_PROTO}
    .locals 1
    invoke-static {{p0, p1}}, {POLICY}->beforePut(Ljava/lang/Object;Ljava/lang/String;)V
    :nova_sidecar_put_start
    invoke-virtual {{p0, p1, p2, p3}}, {SARDINE}->novaPutOriginalFile{PUT_PROTO}
    :nova_sidecar_put_end
    .catch Ljava/io/IOException; {{:nova_sidecar_put_start .. :nova_sidecar_put_end}} :nova_sidecar_put_failed
    invoke-static {{p0, p1}}, {POLICY}->recordSuccess(Ljava/lang/Object;Ljava/lang/String;)V
    return-void
    :nova_sidecar_put_failed
    move-exception v0
    invoke-static {{p0, p1, v0}}, {POLICY}->recordFailure(Ljava/lang/Object;Ljava/lang/String;Ljava/lang/Throwable;)V
    throw v0
.end method
'''


def sidecar_text(text: str) -> str:
    if 'novaPutOriginalFile' in text or POLICY in text:
        raise RuntimeError('Sidecar policy already installed')
    pattern = r'(?m)^(\.method public )put' + re.escape(PUT_PROTO) + r'$'
    if len(re.findall(pattern, text)) != 1:
        raise RuntimeError('Expected exactly one public OkHttpSardine file PUT')
    return re.sub(pattern, lambda m: m.group(1) + 'novaPutOriginalFile' + PUT_PROTO,
                  text, count=1).rstrip() + '\n' + PUT_WRAPPER


def apply_sidecar(root: Path) -> dict:
    files = list(root.glob('smali*/com/thegrizzlylabs/sardineandroid/impl/OkHttpSardine.smali'))
    if len(files) != 1:
        raise RuntimeError(f'Expected one OkHttpSardine class, got {len(files)}')
    files[0].write_text(sidecar_text(files[0].read_text(encoding='utf-8')), encoding='utf-8')
    return {'scope': 'optional hidden resume XML file PUT only', 'backoff_seconds': 300,
            'media_get_unchanged': True, 'local_db_unchanged': True,
            'suppression_reports_remote_success': False}


def main() -> None:
    p = argparse.ArgumentParser()
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--native', type=Path)
    group.add_argument('--iso', type=Path)
    p.add_argument('--report', type=Path)
    a = p.parse_args()
    path = a.native / 'Source/stream_parser_ffmpeg.c' if a.native else a.iso
    old = path.read_text()
    changed = native_text(old) if a.native else iso_text(old)
    path.write_text(changed)
    result = {'status': 'PASS', 'scope': 'native capacity identity' if a.native else 'ISO source identity',
              'real_network_verified': False}
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
