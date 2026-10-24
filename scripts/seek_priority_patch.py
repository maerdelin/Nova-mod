#!/usr/bin/env python3
"""NOVA Test: priority seek preemption across RAW128 and native WebDAV transport.

The seek request signals a cancellation token BEFORE waiting for source_mutex.
Old network reads honor the token and abandon obsolete retries. After the
producer has released source_mutex the seek proceeds with unchanged locks.
Abort/stop remains independent. All normal playback + PGS behavior unchanged.
"""
import argparse
from pathlib import Path

def rep(s,a,b,tag):
    n=s.count(a)
    if n!=1: raise RuntimeError(f"{tag}: expected one anchor, got {n}")
    return s.replace(a,b,1)

def patch_transport(p):
    s=p.read_text()
    s=rep(s,"    volatile int stopping;\n", "    volatile int stopping;\n    volatile int seek_preempt;\n","session token")
    s=rep(s,"    return !s || s->stopping;\n",
          "    return !s || s->stopping ||\n           __atomic_load_n(&s->seek_preempt, __ATOMIC_ACQUIRE);\n",
          "network read interruption")
    s=rep(s,"while (ms > 0 && !s->stopping) {",
          "while (ms > 0 && !s->stopping &&\n           !__atomic_load_n(&s->seek_preempt, __ATOMIC_ACQUIRE)) {",
          "abort transient backoff")
    # These are exclusively the three upstream retry functions.
    for fn,next_fn in (("nova_upstream_seek_retry","nova_upstream_read_exact_retry"),
                       ("nova_upstream_read_exact_retry","nova_upstream_read_some_retry"),
                       ("nova_upstream_read_some_retry","nova_iso_meta_release")):
        start=s.index("static int "+fn+"(")
        end=s.index(next_fn,start+len(fn))
        part=s[start:end]
        old="while (!s->stopping)"
        if part.count(old)!=1: raise RuntimeError(fn+" retry anchor")
        part=part.replace(old,"while (!s->stopping &&\n           !__atomic_load_n(&s->seek_preempt, __ATOMIC_ACQUIRE))",1)
        s=s[:start]+part+s[end:]

    exports=r'''
/* NOVA_SEEK_PREEMPT_V1: signal before waiting for the WebDAV I/O mutex.
 * No transport state or current source offset is modified by this signal.
 */
__attribute__((visibility("default")))
int nova_transport_preempt_read(uint64_t generation)
{
    nova_session *s=session_acquire(generation);
    if(!s) return -1;
    __atomic_store_n(&s->seek_preempt, 1, __ATOMIC_RELEASE);
    session_release(s);
    return 0;
}

__attribute__((visibility("default")))
int nova_transport_clear_preempt(uint64_t generation)
{
    nova_session *s=session_acquire(generation);
    if(!s) return -1;
    __atomic_store_n(&s->seek_preempt, 0, __ATOMIC_RELEASE);
    session_release(s);
    return 0;
}

'''
    marker='__attribute__((visibility("default")))\nint nova_transport_read(uint64_t generation, uint8_t *dst, int size)'
    s=rep(s,marker,exports+marker,"export signal")
    s=rep(s,"    if (s->stopping) {\n        ret = AVERROR_EXIT;\n    } else if (s->mode == NOVA_MODE_BLURAY_ISO) {",
          "    if (s->stopping || __atomic_load_n(&s->seek_preempt, __ATOMIC_ACQUIRE)) {\n        ret = AVERROR_EXIT;\n    } else if (s->mode == NOVA_MODE_BLURAY_ISO) {",
          "direct read cancel")
    # Once io_lock is owned, the old read is fully quiesced.
    anchor="    pthread_mutex_lock(&s->io_lock);\n    int64_t ret = AVERROR(EINVAL);\n"
    s=rep(s,anchor,"    pthread_mutex_lock(&s->io_lock);\n"
                   "    __atomic_store_n(&s->seek_preempt, 0, __ATOMIC_RELEASE);\n"
                   "    int64_t ret = AVERROR(EINVAL);\n","start new seek")
    assert s.count("NOVA_SEEK_PREEMPT_V1")==1
    p.write_text(s)

RAW_HELPERS=r'''
/* NOVA_SEEK_PREEMPT_V1: this is safe to call before RAW source_mutex.
 * Do not hold raw->mutex over network I/O or the transport signal.
 */
void nova_stream_seek_preempt(STREAM *s)
{
    if (!s || !s->parser || !s->parser_priv ||
        !s->parser->name || strcmp(s->parser->name,"FFMPEG")) return;
    FF_PRIV *p=(FF_PRIV*)s->parser_priv;
    NOVA_RAW_PREFETCH *raw=&p->raw;
    if (!raw->enabled) return;
    __atomic_store_n(&raw->seek_preempt, 1, __ATOMIC_RELEASE);
    if (raw->direct_transport && raw->direct_preempt_read)
        raw->direct_preempt_read(raw->transport_generation);
    pthread_mutex_lock(&raw->mutex);
    pthread_cond_broadcast(&raw->can_read);
    pthread_cond_broadcast(&raw->can_write);
    pthread_mutex_unlock(&raw->mutex);
    serprintf("NOVA_SEEK_PREEMPT_V1: request=1\n");
}

void nova_stream_seek_preempt_clear(STREAM *s)
{
    if (!s || !s->parser || !s->parser_priv ||
        !s->parser->name || strcmp(s->parser->name,"FFMPEG")) return;
    FF_PRIV *p=(FF_PRIV*)s->parser_priv;
    NOVA_RAW_PREFETCH *raw=&p->raw;
    if (!raw->enabled) return;
    if (raw->direct_transport && raw->direct_clear_preempt)
        raw->direct_clear_preempt(raw->transport_generation);
    __atomic_store_n(&raw->seek_preempt, 0, __ATOMIC_RELEASE);
    pthread_mutex_lock(&raw->mutex);
    pthread_cond_broadcast(&raw->can_read);
    pthread_cond_broadcast(&raw->can_write);
    pthread_mutex_unlock(&raw->mutex);
}
'''

def patch_parser(p):
    s=p.read_text()
    s=rep(s,"typedef struct NOVA_RAW_PREFETCH {",
          "typedef int (*nova_transport_seek_signal_fn)(uint64_t);\n"
          "typedef struct NOVA_RAW_PREFETCH {","preempt type")
    s=rep(s,"    nova_transport_abort_fn direct_abort;\n",
          "    nova_transport_abort_fn direct_abort;\n"
          "    nova_transport_seek_signal_fn direct_preempt_read;\n"
          "    nova_transport_seek_signal_fn direct_clear_preempt;\n"
          "    volatile int seek_preempt;\n","native fields")
    s=rep(s,'        raw->transport_handle, "nova_transport_abort");\n',
          '        raw->transport_handle, "nova_transport_abort");\n'
          '    raw->direct_preempt_read=(nova_transport_seek_signal_fn)dlsym(\n'
          '        raw->transport_handle,"nova_transport_preempt_read");\n'
          '    raw->direct_clear_preempt=(nova_transport_seek_signal_fn)dlsym(\n'
          '        raw->transport_handle,"nova_transport_clear_preempt");\n',
          "resolve signal")
    s=rep(s,"    if (!raw->direct_read || !raw->direct_seek ||\n        !raw->direct_size || !raw->direct_abort)\n",
          "    if (!raw->direct_read || !raw->direct_seek ||\n"
          "        !raw->direct_size || !raw->direct_abort ||\n"
          "        !raw->direct_preempt_read || !raw->direct_clear_preempt)\n",
          "mandatory symbol validation")
    # The generic HTTP AVIO callback can stop old reads as well. Keep the
    # transport's separate interrupt callback for direct URLs.
    s=rep(s,"    return raw->s && stream_abort(raw->s) ? 1 : 0;\n",
          "    return __atomic_load_n(&raw->seek_preempt, __ATOMIC_ACQUIRE) ||\n"
          "           (raw->s && stream_abort(raw->s)) ? 1 : 0;\n",
          "generic http interruption")
    # A parser parked in custom AVIO waits on can_read. Wake immediately on
    # seek preempt instead of waiting for the next (possibly very slow) read.
    old="while( __atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) &&\n           raw->used_bytes == 0 && !raw->eof ) {"
    new="while( __atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) &&\n" \
        "           raw->used_bytes == 0 && !raw->eof &&\n" \
        "           !__atomic_load_n(&raw->seek_preempt, __ATOMIC_ACQUIRE) &&\n" \
        "           !(raw->s && raw->s->parser_interrupt) ) {"
    s=rep(s,old,new,"parser wait cancel")
    anchor="    if( raw->used_bytes == 0 ) {\n        int ret = raw->eof ? AVERROR_EOF : AVERROR_EXIT;\n"
    s=rep(s,anchor,
          "    if( __atomic_load_n(&raw->seek_preempt, __ATOMIC_ACQUIRE) ||\n"
          "        (raw->s && raw->s->parser_interrupt) ) {\n"
          "        pthread_mutex_unlock(&raw->mutex);\n"
          "        return AVERROR_EXIT;\n"
          "    }\n"+anchor,
          "parser wake exit")
    # The producer must not acquire source_mutex for another obsolete read.
    anchor="        pthread_mutex_lock(&raw->source_mutex);\n        pthread_mutex_lock(&raw->mutex);\n"
    s=rep(s,anchor,
          "        pthread_mutex_lock(&raw->source_mutex);\n"
          "        if(__atomic_load_n(&raw->seek_preempt, __ATOMIC_ACQUIRE)) {\n"
          "            pthread_mutex_unlock(&raw->source_mutex);\n"
          "            av_usleep(1000);\n"
          "            continue;\n"
          "        }\n"
          "        pthread_mutex_lock(&raw->mutex);\n",
          "producer seek priority")
    # Recover normal production after a canceled read, without poisoning EOF.
    anchor="        int got = avio_read(raw->source, raw->ring + write_off, want);\n"
    s=rep(s,anchor,anchor+
          "        if(__atomic_load_n(&raw->seek_preempt, __ATOMIC_ACQUIRE))\n"
          "            got=AVERROR_EXIT; /* stale old-position network read */\n",
          "discard aborted old read")

    seek_anchor="    // Serialize the actual source protocol. The producer never holds the raw\n"
    s=rep(s,seek_anchor,
          "    /* Request preemption BEFORE source_mutex, not after it. */\n"
          "    __atomic_store_n(&raw->seek_preempt, 1, __ATOMIC_RELEASE);\n"
          "    if(raw->direct_transport && raw->direct_preempt_read)\n"
          "        raw->direct_preempt_read(raw->transport_generation);\n"
          "    // Serialize the actual source protocol. The producer never holds the raw\n",
          "seek start preemption")
    end_anchor="    pthread_mutex_unlock(&raw->source_mutex);\n    return result;\n}\n\nstatic void nova_raw_stats"
    s=rep(s,end_anchor,
          "    if(raw->direct_transport && raw->direct_clear_preempt)\n"
          "        raw->direct_clear_preempt(raw->transport_generation);\n"
          "    __atomic_store_n(&raw->seek_preempt, 0, __ATOMIC_RELEASE);\n"
          "    pthread_mutex_lock(&raw->mutex);\n"
          "    pthread_cond_broadcast(&raw->can_read);\n"
          "    pthread_cond_broadcast(&raw->can_write);\n"
          "    pthread_mutex_unlock(&raw->mutex);\n"
          "    pthread_mutex_unlock(&raw->source_mutex);\n"
          "    return result;\n}\n\n"+RAW_HELPERS+
          "\nstatic void nova_raw_stats","seek cleanup")
    assert s.count("NOVA_SEEK_PREEMPT_V1")>=1
    p.write_text(s)

def patch_stream(p):
    s=p.read_text()
    # These callbacks only touch FFmpeg/RAW streams; no-op for other parsers.
    anchor="static int _seek_pause( STREAM *s )\n{"
    s=rep(s,anchor,
          "extern void nova_stream_seek_preempt(STREAM *s);\n"
          "extern void nova_stream_seek_preempt_clear(STREAM *s);\n"
          +anchor,"seek helper declarations")
    s=rep(s,"    s->parser_interrupt = 1;", "    s->parser_interrupt = 1;\n    nova_stream_seek_preempt(s);",
          "early request") if "    s->parser_interrupt = 1;" in s else rep(s,
          "\ts->parser_interrupt = 1;",
          "\ts->parser_interrupt = 1;\n\tnova_stream_seek_preempt(s);",
          "early request")
    anchor="\tstream_un_pause( s, was_paused );\n\ts->seek_paused = 0;\n"
    s=rep(s,anchor,"\tnova_stream_seek_preempt_clear(s);\n"+anchor,"clear on end/failed seek")
    p.write_text(s)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--native",type=Path,required=True)
    ap.add_argument("--transport",type=Path,required=True)
    a=ap.parse_args()
    patch_transport(a.transport)
    patch_parser(a.native/"Source/stream_parser_ffmpeg.c")
    patch_stream(a.native/"Source/stream_video.c")
    print("NOVA_SEEK_PREEMPT_V1=PATCHED")

if __name__=="__main__": main()
