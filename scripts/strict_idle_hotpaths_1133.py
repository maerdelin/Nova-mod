#!/usr/bin/env python3
"""After NOVA 1133 original patch: gate residual hot-path diagnostic work.

Modify ONLY diagnostics-owned measurements, counters, and branches. Preserve
every avio/sfdec/RAW read/seek, mutex, queue and rendering business operation.
Fail closed on changed anchors.
"""
from pathlib import Path
import argparse

def once(s,a,b,label):
    n=s.count(a)
    if n!=1: raise RuntimeError(f"1133 hotpath {label}: expected 1, found {n}")
    return s.replace(a,b,1)

def patch(root):
    v=root/"Source/stream_video.c"
    s=v.read_text()
    s=once(s,
        "if(s->video_drop) __atomic_fetch_add(&s->nova_diag_drop_sink, 1, __ATOMIC_RELAXED);",
        "if(s->video_drop && nova_diag_on()) __atomic_fetch_add(&s->nova_diag_drop_sink, 1, __ATOMIC_RELAXED);",
        "sink diagnostic write")
    s=once(s,"int nova_final_begin = atime();",
           "int nova_final_begin = nova_diag_on()?atime():0;",
           "parser start time")
    s=once(s,"int nova_final_duration = atime() - nova_final_begin;",
           "int nova_final_duration = nova_final_begin && nova_diag_on()?atime()-nova_final_begin:0;",
           "parser duration")
    s=once(s,"if (nova_final_duration >= 75 &&",
           "if (nova_diag_on() && nova_final_duration >= 75 &&",
           "parser slow gate")
    v.write_text(s)

    p=root/"Source/stream_parser_ffmpeg.c"
    s=p.read_text()
    s=once(s,"int64_t nova_boot_io_begin=av_gettime_relative();",
           "int64_t nova_boot_io_begin=nova_diag_on()?av_gettime_relative():0;",
           "RAW producer start")
    s=once(s,"int64_t nova_boot_io_ms=(av_gettime_relative()-nova_boot_io_begin)/1000;",
           "int64_t nova_boot_io_ms=nova_boot_io_begin && nova_diag_on()?(av_gettime_relative()-nova_boot_io_begin)/1000:0;",
           "RAW producer duration")
    s=once(s,"if(nova_boot_io_ms>=100 || raw->nova_boot_producer_calls++<12)",
           "if(nova_diag_on() && (nova_boot_io_ms>=100 || raw->nova_boot_producer_calls++<12))",
           "RAW producer sample counter")
    s=once(s,"int64_t nova_boot_read_begin=av_gettime_relative();",
           "int64_t nova_boot_read_begin=nova_diag_on()?av_gettime_relative():0;",
           "RAW consumer start")
    s=once(s,"int64_t nova_boot_consumer_wait_ms=(av_gettime_relative()-nova_boot_read_begin)/1000;",
           "int64_t nova_boot_consumer_wait_ms=nova_boot_read_begin && nova_diag_on()?(av_gettime_relative()-nova_boot_read_begin)/1000:0;",
           "RAW consumer duration")
    s=once(s,"if(nova_boot_consumer_wait_ms>=100 || raw->nova_boot_consumer_calls++<12)",
           "if(nova_diag_on() && (nova_boot_consumer_wait_ms>=100 || raw->nova_boot_consumer_calls++<12))",
           "RAW consumer counter")
    s=once(s,"int nova_final_now = atime();",
           "int nova_final_now = nova_diag_on()?atime():0;",
           "FFmpeg queue timestamp")
    s=once(s,"if (!nova_final_last_queue_log_ms ||\n        nova_final_now - nova_final_last_queue_log_ms >= 1000) {",
           "if (nova_diag_on() && (!nova_final_last_queue_log_ms ||\n        nova_final_now - nova_final_last_queue_log_ms >= 1000)) {",
           "FFmpeg expensive queue sampling")
    s=once(s,"int nova_final_read_t0 = atime();",
           "int nova_final_read_t0 = nova_diag_on()?atime():0;",
           "FFmpeg read sample start")
    s=once(s,"int nova_final_read_ms = atime() - nova_final_read_t0;",
           "int nova_final_read_ms = nova_final_read_t0 && nova_diag_on()?atime()-nova_final_read_t0:0;",
           "FFmpeg read duration")
    s=once(s,"if (nova_final_read_ms >= 75) {",
           "if (nova_diag_on() && nova_final_read_ms >= 75) {",
           "FFmpeg slow read condition")
    s=once(s,"if (packet.flags & AV_PKT_FLAG_CORRUPT) {\n        int n = __atomic_add_fetch(&s->nova_diag_demux_corrupt,",
           "if (nova_diag_on() && (packet.flags & AV_PKT_FLAG_CORRUPT)) {\n        int n = __atomic_add_fetch(&s->nova_diag_demux_corrupt,",
           "FFmpeg corrupt counter")
    p.write_text(s)

    p=root/"Source/stream_sink_audio.c"
    s=p.read_text()
    s=once(s,"} else if (ret < 0 && ret != AUDIO_WRITE_RETRY && ret != AUDIO_WRITE_RESTARTED) {",
           "} else if (nova_diag_on() && ret < 0 && ret != AUDIO_WRITE_RETRY && ret != AUDIO_WRITE_RESTARTED) {",
           "audio error diagnostic")
    p.write_text(s)

    p=root/"Source/codec_sfdec2.c"
    s=p.read_text()
    s=once(s,"if (!p->nova_trace_start_ms)\n\t\tp->nova_trace_start_ms = atime64();",
           "if (nova_diag_on() && !p->nova_trace_start_ms)\n\t\tp->nova_trace_start_ms = atime64();",
           "trace start")
    s=once(s,"if (s && p->nova_trace_start_ms > 0 &&\n        now_ms - p->nova_trace_start_ms <= 1200000",
           "if (nova_diag_on() && s && p->nova_trace_start_ms > 0 &&\n        now_ms - p->nova_trace_start_ms <= 1200000",
           "put sample")
    s=once(s,"if (s && p->nova_trace_correction_logs < 48) {",
           "if (nova_diag_on() && s && p->nova_trace_correction_logs < 48) {",
           "PCM correction")
    s=once(s,"if (f && !p->nova_trace_boot_logged) {",
           "if (nova_diag_on() && f && !p->nova_trace_boot_logged) {",
           "first frame diagnostics")
    s=once(s,"INT64 nova_trace_now_ms = now_ns / NSEC_PER_MSEC;",
           "INT64 nova_trace_now_ms = nova_diag_on()?now_ns/NSEC_PER_MSEC:0;",
           "render trace local")
    s=once(s,"if (s && p->nova_trace_start_ms > 0 &&\n                (int)atime64() - p->nova_trace_start_ms <= 1200000",
           "if (nova_diag_on() && s && p->nova_trace_start_ms > 0 &&\n                (int)atime64() - p->nova_trace_start_ms <= 1200000",
           "render trace sample")
    s=once(s,"INT64 nova_final_render_now = atime64();",
           "INT64 nova_final_render_now = nova_diag_on()?atime64():0;",
           "render queue timestamp")
    s=once(s,"if (s && (!p->nova_final_render_log_ms ||",
           "if (nova_diag_on() && s && (!p->nova_final_render_log_ms ||",
           "render queue sample")
    s=once(s,"int nova_final_codec_send_t0 = atime();",
           "int nova_final_codec_send_t0 = nova_diag_on()?atime():0;",
           "codec send sample start")
    s=once(s,"int nova_final_codec_send_ms = atime() - nova_final_codec_send_t0;",
           "int nova_final_codec_send_ms = nova_final_codec_send_t0 && nova_diag_on()?atime()-nova_final_codec_send_t0:0;",
           "codec send duration")
    s=once(s,"if (nova_final_codec_send_ms >= 75)",
           "if (nova_diag_on() && nova_final_codec_send_ms >= 75)",
           "codec send sample")
    s=once(s,"if (s) {\n                    int n = __atomic_add_fetch(&s->nova_diag_drop_startup,",
           "if (s && nova_diag_on()) {\n                    int n = __atomic_add_fetch(&s->nova_diag_drop_startup,",
           "startup drop count")
    s=once(s,"if (s) {\n                    if (p->nova_trace_late_epoch != f->epoch) {",
           "if (s && nova_diag_on()) {\n                    if (p->nova_trace_late_epoch != f->epoch) {",
           "late episode diagnostic-only counter")
    s=once(s,"if (p->nova_trace_consecutive_late >= 3 && s) {",
           "if (nova_diag_on() && p->nova_trace_consecutive_late >= 3 && s) {",
           "late recovery diagnostics")
    s=once(s,"                    p->nova_trace_consecutive_late = 0;\n\t\t\t\t\t// Count successful submissions independently of logging.",
           "                    if(nova_diag_on()) p->nova_trace_consecutive_late = 0;\n\t\t\t\t\t// Count successful submissions independently of logging.",
           "late episode reset")
    # render_submit_seq is read only by NOVA trace messages, never playback
    # control. Keep its value frozen while capture is inactive.
    s=once(s,"\t\t\t\t\tp->render_submit_seq++;",
           "\t\t\t\t\tif(nova_diag_on()) p->render_submit_seq++;",
           "render per-frame diagnostics-only sequence")
    s=once(s,"INT64 nova_trace_offset_ns = p->render_offset_ns;",
           "INT64 nova_trace_offset_ns = nova_diag_on()?p->render_offset_ns:0;",
           "trace snapshot offset")
    s=once(s,"INT64 nova_trace_target_ns = p->target_offset_ns;",
           "INT64 nova_trace_target_ns = nova_diag_on()?p->target_offset_ns:0;",
           "trace snapshot target")
    s=once(s,"int nova_trace_from_audio = p->render_offset_from_audio;",
           "int nova_trace_from_audio = nova_diag_on()?p->render_offset_from_audio:0;",
           "trace snapshot clock source")
    s=once(s,"if (s) {\n                     extern void nova_60fps_note_late(void);",
           "if (s && nova_diag_on()) {\n                     extern void nova_60fps_note_late(void);",
           "late drop count")
    p.write_text(s)
    return ["stream_video.c","stream_parser_ffmpeg.c","stream_sink_audio.c","codec_sfdec2.c"]

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--native",required=True,type=Path)
    args=parser.parse_args()
    print("NOVA1133_STRICT_IDLE_HOTPATH=PASS", patch(args.native))
