#!/usr/bin/env python3
"""NOVA 1199: source-level OFF collection gates for all 13 audited families.

Apply AFTER global_logs_native_patch.py, global_logs_native_coverage_patch.py,
global_logs_sampling_1197_patch.py, and all business source patches.

Never gate genuine playback timeouts, render readiness, buffer progress,
live RAW/ISO byte cursors, W2 scheduling, curl_multi_perform, FFmpeg packet
decoding, or stream/codec operations. Every mutation is source anchored.
"""
from __future__ import annotations

import argparse
from pathlib import Path

MARK = "NOVA_1199_THIRTEEN_COLLECTION_PATHS"


def replace(source: str, old: str, new: str, what: str, count: int = 1) -> str:
    got = source.count(old)
    if got != count:
        raise RuntimeError(f"{what}: expected {count} exact anchors, got {got}")
    return source.replace(old, new)


def edit(path: Path, operation) -> None:
    if not path.is_file():
        raise RuntimeError(f"required compiled source absent: {path}")
    before = path.read_text()
    after = operation(before)
    if after == before:
        raise RuntimeError(f"empty 1199 gate: {path}")
    path.write_text(after)


def parser_source(s: str) -> str:
    # (3) RAW Seek-only lock+I/O timing; retain actual mutex/avio_seek.
    for name in ("nova_boot_seek_lock_begin", "nova_boot_seek_io_begin"):
        old = f"int64_t {name}=av_gettime_relative();"
        s = replace(s, old,
            f"int64_t {name}=nova_diag_on()?av_gettime_relative():0;",
            name)
    for name, origin in (("nova_boot_seek_lock_ms","nova_boot_seek_lock_begin"),
                         ("nova_boot_seek_io_ms","nova_boot_seek_io_begin")):
        old = f"int64_t {name}=(av_gettime_relative()-{origin})/1000;"
        s = replace(s, old,
            f"int64_t {name}=({origin} && nova_diag_on())?"
            f"(av_gettime_relative()-{origin})/1000:0;", name)

    # (4) First-frame staged decoder uses this start only for a diagnostic
    # elapsedMs line. Staged packet/frame work must remain byte-identical.
    s = replace(s,
        "int64_t total=0, level=64*1024LL, start=av_gettime_relative();",
        "int64_t total=0, level=64*1024LL, start=nova_diag_on()?av_gettime_relative():0;",
        "staged decoder diagnostic start")

    # (10) These are raw printf paths retained in the production AVOS .so,
    # not guarded by the macro that already covers serprintf(). Only these
    # two literal *log messages* are rerouted, not libc printf itself.
    s = replace(s, 'printf("FFMPEG: cannot find stream info\\r\\n");',
                'serprintf("FFMPEG: cannot find stream info\\r\\n");',
                "FFmpeg error direct printf", count=2)

    # (12) av_log records can be generated internally even when the AVOS
    # callback discards them. Restrict generation via libavutil's own
    # process-global log level and restore ON levels on the controller tick.
    # The callback is also guarded before any AVOS-side format work.
    marker = "void av_log_cb(void* ptr, int level, const char* fmt, va_list vl)\n{\n"
    helper = """/* NOVA_1199_FFMPEG_CAPTURE_GATE: logging only; never decode policy. */
static pthread_mutex_t nova_ffmpeg_log_gate_mutex=PTHREAD_MUTEX_INITIALIZER;
void nova_ffmpeg_log_sync(void)
{
    /* AVOS can call av_log_set_level() again during FFmpeg open.
     * Always reconcile the real libavutil level, not a cached toggle. */
    int enabled=nova_diag_on()?1:0;
    int wanted=enabled?(log_debug?AV_LOG_DEBUG:AV_LOG_INFO):AV_LOG_QUIET;
    if(av_log_get_level()==wanted)return;
    pthread_mutex_lock(&nova_ffmpeg_log_gate_mutex);
    enabled=nova_diag_on()?1:0;
    wanted=enabled?(log_debug?AV_LOG_DEBUG:AV_LOG_INFO):AV_LOG_QUIET;
    if(av_log_get_level()!=wanted)
        av_log_set_level(wanted);
    pthread_mutex_unlock(&nova_ffmpeg_log_gate_mutex);
}
"""
    s = replace(s, marker, helper+marker+"    if(!nova_diag_on())return;\n",
                "FFmpeg callback and source logging gate")
    s = replace(s,
        "\tav_log_set_callback(av_log_cb);\n",
        "\tav_log_set_callback(av_log_cb);\n",
        "FFmpeg callback anchor")
    s = replace(s,
        "\tav_log_set_level( AV_LOG_DEBUG );\n \t}\n",
        "\tav_log_set_level( AV_LOG_DEBUG );\n \t}\n"
        "\tnova_ffmpeg_log_sync();\n",
        "FFmpeg initial level before opening network")

    # (13) Direct blackbox bridge should not even calculate avio_tell()
    # arguments after OFF. This follows the 1196 early bridge guard.
    for label in (
        "40,(int64_t)(fmt->pb?avio_tell(fmt->pb):-1),0",
        "41,(int64_t)(fmt->pb?avio_tell(fmt->pb):-1),result",
    ):
        anchor="if(nova_diag_on()) nova_1073_external("+label+");"
        if anchor not in s:
            raise RuntimeError("AVOS blackbox argument guard lost: "+label)
    return s


def player_source(s: str) -> str:
    # (5) This clock throttles ONLY NOVA_REBUFFER_WAIT log emission.
    # now_percent_ms / last_percent_report_ms are LIVE UI progress and
    # explicitly not touched.
    s = replace(s,"last_wait_log = atime();",
                "if(nova_diag_on()) last_wait_log = atime();",
                "rebuffer diagnostic enter",count=1)
    s = replace(s,
        "int now = atime();\n                        if( now - last_wait_log >= 1000 ) {",
        "int now = nova_diag_on()?atime():0;\n"
        "                        if( nova_diag_on() && now - last_wait_log >= 1000 ) {",
        "rebuffer diagnostic wait timer")

    # (13) The optional system monitor is already started only while ON
    # and exits on OFF. Stop an in-progress snapshot at each I/O boundary.
    s = replace(s,
        'static long nova_diag_value(const char *path,const char *key)\n{\n',
        'static long nova_diag_value(const char *path,const char *key)\n{\n'
        '    if(!nova_diag_on())return -1;\n',
        "system /proc reader")
    s = replace(s,
        'static long nova_diag_psi(const char *path)\n{\n',
        'static long nova_diag_psi(const char *path)\n{\n'
        '    if(!nova_diag_on())return -1;\n',
        "system pressure reader")
    s = replace(s,
        "getrusage(RUSAGE_SELF,&ru);",
        "if(!nova_diag_on())break;\n        getrusage(RUSAGE_SELF,&ru);",
        "system worker before resource sampling")
    # OFF toggled during the snapshot must not format eight sysfs paths.
    # A partial ON snapshot is harmless: FFmpeg/AVOS output is gated.
    s = replace(s,
        "long freqs[8];\n        for(int i=0;i<8;i++){",
        "long freqs[8]={-1,-1,-1,-1,-1,-1,-1,-1};\n"
        "        for(int i=0;i<8 && nova_diag_on();i++){",
        "system worker CPU frequency sysfs scan cancellation")
    s = replace(s,
        'DIR *dir=opendir("/proc/self/task");',
        'if(!nova_diag_on())break;\n        DIR *dir=opendir("/proc/self/task");',
        "system worker before task traversal")
    s = replace(s,
        'while((ent=readdir(dir))!=NULL && threads<256){',
        'while(nova_diag_on() && (ent=readdir(dir))!=NULL && threads<256){',
        "task traversal stop gate")
    s = replace(s,
        'for(int i=0;i<24;i++){\n            char path[128];',
        'for(int i=0;i<24 && nova_diag_on();i++){\n            char path[128];',
        "thermal scan cancellation")
    s = replace(s,
        'unsigned seq=__atomic_load_n(&nova_60fps_late_seq,__ATOMIC_RELAXED);',
        'if(!nova_diag_on())break;\n'
        '        unsigned seq=__atomic_load_n(&nova_60fps_late_seq,__ATOMIC_RELAXED);',
        "system worker stop before final sample")
    # (12) Restore AV_LOG_INFO/DEBUG when ON and AV_LOG_QUIET when OFF.
    s = replace(s,
        '        if(nova_diag_on()) nova_60fps_start_sampler();\n        nova_avdiag_tick(s);',
        '        extern void nova_ffmpeg_log_sync(void);\n'
        '        nova_ffmpeg_log_sync();\n'
        '        if(nova_diag_on()) nova_60fps_start_sampler();\n'
        '        nova_avdiag_tick(s);',
        "independent live FFmpeg logging level sync")
    return s


def codec_source(s: str) -> str:
    # (6) All copies below are used only by NOVA_SYNC_* diagnostics. Leave
    # render_offset_ns and live AV synchronization untouched.
    for field, value in (
        ("nova_trace_old_offset","p->render_offset_ns"),
        ("nova_trace_old_from_audio","p->render_offset_from_audio"),
        ("nova_trace_pending","p->pending_reanchor"),
        ("nova_trace_seek_pending","p->pending_seek_reanchor"),
        ("nova_trace_slew","p->slew_active"),
        ("nova_trace_pcm_slew","p->pcm_startup_slew"),
        ("nova_trace_clock_generation","(int)p->render_generation"),
        ("diag_ref_ms","p->venc_ref_time"),
    ):
        typ="INT64" if field in ("nova_trace_old_offset","diag_ref_ms") else "int"
        old=f"{typ} {field} = {value};"
        new=f"{typ} {field} = nova_diag_on()?{value}:0;"
        s=replace(s,old,new,"AV sync diagnostic snapshot "+field)
    return s


def avos_open_source(s: str) -> str:
    # (2) Only observational startup-latency anchor; leave starttime,
    # player initialization and stream_start exactly as 1198.
    return replace(s, "int nova_trace_t0 = atime();",
        "int nova_trace_t0 = nova_diag_on()?atime():0;",
        "AVOS startup diagnostic start")


def subtitle_output_source(s: str, label: str) -> str:
    # (10) The production libavos.so contains legacy subtitle DBG print
    # strings. Retain the upstream Debug[] conditional but route the
    # diagnostic-only output through the already gated AVOS logger.
    old=f'DBG printf( "{label}: not {label}\\n" );'
    new=f'DBG serprintf( "{label}: not {label}\\n" );'
    return replace(s,old,new,label+" raw stdout log")


def transport_source(s: str) -> str:
    # (9) The warehouse diagnostics scanner is expensive: lock + all
    # physical pages. Bail out BEFORE failure counter or warehouse lock.
    return replace(s,
        "static void nova_wh_diag_v2(nova_shared_warehouse *w,const char *reason)\n{\n",
        "static void nova_wh_diag_v2(nova_shared_warehouse *w,const char *reason)\n{\n"
        "    if(!nova_global_log_enabled())return;\n",
        "Shared42 diagnostic-only warehouse scan")


def literange_source(s: str) -> str:
    # (7) The 1064 curl timing and pause serial are used only for LOGI.
    # Curl multi perform / stall timeout / liveness unchanged.
    s = replace(s,
        "uint64_t pause_before=e->pause_serial;",
        "uint64_t pause_before=nova_global_log_enabled()?e->pause_serial:0;",
        "CURL diagnostic pause snapshot")
    s = replace(s,
        "int64_t call_start=nova_iso_uptime_ms();",
        "int64_t call_start=nova_global_log_enabled()?nova_iso_uptime_ms():0;",
        "CURL diagnostic start")
    s = replace(s,
        "int64_t call_elapsed=nova_iso_uptime_ms()-call_start;",
        "int64_t call_elapsed=(call_start && nova_global_log_enabled())?"
        "nova_iso_uptime_ms()-call_start:0;",
        "CURL diagnostic duration")
    s = replace(s,
        "if(s->mode==NOVA_MODE_BLURAY_ISO &&\n"
        "           (pause_before!=e->pause_serial || call_elapsed>=250))",
        "if(nova_global_log_enabled() && s->mode==NOVA_MODE_BLURAY_ISO &&\n"
        "           (pause_before!=e->pause_serial || call_elapsed>=250))",
        "CURL diagnostic log predicate")
    # Warehouse free-page snapshot ONLY feeds HEAD_STALL LOGE. The
    # NOVA_MULTI_ISO_STALL decision must still happen under OFF.
    s = replace(s,
        "int free_pages=-1;\n            if(w){",
        "int free_pages=-1;\n            if(w && nova_global_log_enabled()){",
        "ISO stall log-only pool lock")
    # (8) 1197 stopped accumulating sample bytes; also stop residual
    # periodic resets and the read-success wait measurement. Keep
    # last_sample_ms: it is the W2 scheduler interval, NOT log sampling.
    s = replace(s,
        "s->lite->committed_sample_bytes=0;\n"
        "    s->lite->received_sample_bytes=0;\n"
        "    s->lite->starvation_count=0;",
        "if(nova_global_log_enabled()){\n"
        "        s->lite->committed_sample_bytes=0;\n"
        "        s->lite->received_sample_bytes=0;\n"
        "        s->lite->starvation_count=0;\n"
        "    }",
        "LiteRange initial diagnostics reset")
    s = replace(s,
        "e->committed_sample_bytes=0;\n"
        "    e->received_sample_bytes=0;\n"
        "    e->starvation_count=0;",
        "if(nova_global_log_enabled()){\n"
        "        e->committed_sample_bytes=0;\n"
        "        e->received_sample_bytes=0;\n"
        "        e->starvation_count=0;\n"
        "    }",
        "LiteRange periodic diagnostics reset")
    s = replace(s,
        "int64_t waited=nova_iso_uptime_ms()-began;",
        "int64_t waited=nova_global_log_enabled()?nova_iso_uptime_ms()-began:0;",
        "LiteRange diagnostic-only starvation read time")
    # Preserve business scheduler irrespective of user Logs choice.
    for must in ("s->multi_active_lanes=2;","nova_lite_schedule(s);",
                 "e->last_sample_ms=now;","CURLMcode rc=curl_multi_perform(e->multi,&running);",
                 "nova_iso_1064_stalled(tick,last_progress)",
                 "s->multi_committed_cursor+=take;"):
        if must not in s:
            raise RuntimeError("NOVA player business invariant missing: "+must)
    return s


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--native",type=Path,required=True)
    ap.add_argument("--transport",type=Path,required=True)
    ap.add_argument("--lite",type=Path,required=True)
    a=ap.parse_args()
    root=a.native/"Source"
    edit(root/"stream_parser_ffmpeg.c",parser_source)
    edit(root/"stream_video.c",player_source)
    edit(root/"codec_sfdec2.c",codec_source)
    edit(root/"avos_mp_video.c",avos_open_source)
    for name,label in (("subtitle_idx.c","IDX"),("subtitle_mpl2.c","MPL"),
                       ("subtitle_sub.c","SUB")):
        edit(root/name,lambda src,tag=label:subtitle_output_source(src,tag))
    edit(a.transport,transport_source)
    edit(a.lite,literange_source)
    print(MARK+"=PASS diagnostic source gates; playback control preserved")


if __name__=="__main__":
    main()
