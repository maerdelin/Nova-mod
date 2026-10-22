#!/usr/bin/env python3
from pathlib import Path
import argparse, json

def once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected one anchor, got {n}")
    return text.replace(old, new, 1)

HELPERS = r'''
typedef int (*nova_transport_read_fn)(uint64_t, uint8_t *, int);
typedef int64_t (*nova_transport_seek_fn)(uint64_t, int64_t, int);
typedef int64_t (*nova_transport_size_fn)(uint64_t);
typedef int (*nova_transport_abort_fn)(uint64_t);

static uint64_t nova_direct_generation(const char *url)
{
    const char *prefix = "novatransport://";
    if (!url || strncmp(url, prefix, strlen(prefix)))
        return 0;
    const char *p = url + strlen(prefix);
    char *end = NULL;
    unsigned long long v = strtoull(p, &end, 10);
    return end != p ? (uint64_t)v : 0;
}

static int nova_direct_read(void *opaque, uint8_t *dst, int size)
{
    NOVA_RAW_PREFETCH *raw = (NOVA_RAW_PREFETCH *)opaque;
    if (!raw->direct_read || !raw->transport_generation)
        return AVERROR_EXIT;
    return raw->direct_read(raw->transport_generation, dst, size);
}

static int64_t nova_direct_seek(void *opaque, int64_t off, int whence)
{
    NOVA_RAW_PREFETCH *raw = (NOVA_RAW_PREFETCH *)opaque;
    if (!raw->direct_seek || !raw->transport_generation)
        return AVERROR_EXIT;
    return raw->direct_seek(raw->transport_generation, off, whence);
}

static int nova_direct_source_open(NOVA_RAW_PREFETCH *raw, const char *url)
{
    raw->transport_generation = nova_direct_generation(url);
    if (!raw->transport_generation)
        return AVERROR(EINVAL);

    raw->transport_handle = dlopen("libnova_transport.so", RTLD_NOW | RTLD_LOCAL);
    if (!raw->transport_handle)
        return AVERROR(ENOENT);

    raw->direct_read = (nova_transport_read_fn)dlsym(
        raw->transport_handle, "nova_transport_read");
    raw->direct_seek = (nova_transport_seek_fn)dlsym(
        raw->transport_handle, "nova_transport_seek");
    raw->direct_size = (nova_transport_size_fn)dlsym(
        raw->transport_handle, "nova_transport_size");
    raw->direct_abort = (nova_transport_abort_fn)dlsym(
        raw->transport_handle, "nova_transport_abort");
    if (!raw->direct_read || !raw->direct_seek ||
        !raw->direct_size || !raw->direct_abort)
        return AVERROR(ENOSYS);

    unsigned char *buffer = av_malloc(NOVA_RAW_IO_BYTES);
    if (!buffer)
        return AVERROR(ENOMEM);

    raw->source = avio_alloc_context(
        buffer, NOVA_RAW_IO_BYTES, 0, raw,
        nova_direct_read, NULL, nova_direct_seek);
    if (!raw->source) {
        av_free(buffer);
        return AVERROR(ENOMEM);
    }
    raw->source->seekable = AVIO_SEEKABLE_NORMAL;
    raw->source_size = raw->direct_size(raw->transport_generation);
    raw->direct_transport = 1;
    serprintf("NOVA_DIRECT_SOURCE_OPEN: generation=%llu size=%lld\n",
        (unsigned long long)raw->transport_generation,
        (long long)raw->source_size);
    return 0;
}

static void nova_direct_source_close(NOVA_RAW_PREFETCH *raw)
{
    if (raw->direct_transport) {
        if (raw->direct_abort && raw->transport_generation)
            raw->direct_abort(raw->transport_generation);
        if (raw->source) {
            av_freep(&raw->source->buffer);
            avio_context_free(&raw->source);
        }
        if (raw->transport_handle)
            dlclose(raw->transport_handle);
        raw->transport_handle = NULL;
        raw->direct_transport = 0;
        return;
    }
    if (raw->source)
        avio_closep(&raw->source);
}
'''

def apply(root: Path, report: Path|None=None):
    path = root / "Source" / "stream_parser_ffmpeg.c"
    text = path.read_text()
    if "NOVA_DIRECT_SOURCE_OPEN" in text:
        raise RuntimeError("direct transport patch already applied")

    if "#include <dlfcn.h>" not in text:
        text = once(text, "#include <sys/resource.h>\n",
                    "#include <sys/resource.h>\n#include <dlfcn.h>\n",
                    "dlfcn include")

    text = once(
        text,
        "    AVIOContext *consumer;\n",
        """    AVIOContext *consumer;
    void *transport_handle;
    uint64_t transport_generation;
    int direct_transport;
    nova_transport_read_fn direct_read;
    nova_transport_seek_fn direct_seek;
    nova_transport_size_fn direct_size;
    nova_transport_abort_fn direct_abort;
""",
        "direct fields",
    )

    type_anchor = "typedef struct NOVA_RAW_PREFETCH {"
    idx = text.index(type_anchor)
    pre = """typedef int (*nova_transport_read_fn)(uint64_t, uint8_t *, int);
typedef int64_t (*nova_transport_seek_fn)(uint64_t, int64_t, int);
typedef int64_t (*nova_transport_size_fn)(uint64_t);
typedef int (*nova_transport_abort_fn)(uint64_t);

"""
    text = text[:idx] + pre + text[idx:]

    marker = "static int nova_raw_interrupt(void *opaque)"
    text = once(text, marker, HELPERS + "\n" + marker, "direct helpers")

    old_guard = """    if( strncmp(url, "http://", 7) && strncmp(url, "https://", 8) )
        return 0;
"""
    new_guard = """    int nova_direct = !strncmp(url, "novatransport://", 16);
    if( !nova_direct && strncmp(url, "http://", 7) &&
        strncmp(url, "https://", 8) )
        return 0;
"""
    text = once(text, old_guard, new_guard, "protocol guard")

    old_open = """    ret = avio_open2(
        &raw->source, url, AVIO_FLAG_READ, &interrupt, &io_options );
    av_dict_free(&io_options);
    if( ret < 0 || !raw->source )
        goto fail;

    raw->source_size = avio_size(raw->source);
"""
    new_open = """    if( nova_direct ) {
        ret = nova_direct_source_open(raw, url);
    } else {
        ret = avio_open2(
            &raw->source, url, AVIO_FLAG_READ, &interrupt, &io_options );
    }
    av_dict_free(&io_options);
    if( ret < 0 || !raw->source )
        goto fail;

    if( !nova_direct )
        raw->source_size = avio_size(raw->source);
"""
    text = once(text, old_open, new_open, "source open")

    text = text.replace(
        "    if( raw->source )\n        avio_closep(&raw->source);",
        "    nova_direct_source_close(raw);",
    )

    stop_anchor = """    int was_running = __atomic_exchange_n(
        &raw->run, 0, __ATOMIC_ACQ_REL );
"""
    stop_new = stop_anchor + """
    if( raw->direct_transport && raw->direct_abort &&
        raw->transport_generation )
        raw->direct_abort(raw->transport_generation);
"""
    text = once(text, stop_anchor, stop_new, "abort direct source")

    required = (
        "novatransport://", "NOVA_DIRECT_SOURCE_OPEN",
        'dlsym(', '"nova_transport_read"', '"nova_transport_seek"',
        "raw->direct_abort(raw->transport_generation)",
    )
    missing = [x for x in required if x not in text]
    if missing:
        raise RuntimeError("postcondition missing: " + repr(missing))

    path.write_text(text)
    result = {
        "status":"PASS",
        "direct_scheme":"novatransport",
        "localhost_transport":False,
        "raw_capacity_bytes":128*1024*1024,
        "priority_policy_changed":False,
        "transport_symbols":["read","seek","size","abort"],
    }
    if report:
        report.write_text(json.dumps(result, indent=2)+"\n")
    return result

if __name__ == "__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--report", type=Path)
    a=ap.parse_args()
    print(json.dumps(apply(a.root,a.report),indent=2))
