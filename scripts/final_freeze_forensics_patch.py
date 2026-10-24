#!/usr/bin/env python3
"""NOVA FINAL FREEZE FORENSICS: one-shot, observation-only diagnostics.

Run AFTER native_rebuffer_patch, av_diag_patch, and startup_freeze_trace_patch.
No changes to timing, decoder control flow, buffering, seek, drops, or delivery.
Every edited source anchor must match exactly once or the build fails closed.

Captures an independent 1Hz heartbeat, parser scheduling/loop execution,
demux queue occupancy including subtitles, read waits, codec slow calls,
decoder frame queue depths and complete existing AV/sync observations.
"""
import argparse
import json
from pathlib import Path


def once(source, anchor, replacement, label):
    found = source.count(anchor)
    if found != 1:
        raise RuntimeError("%s: expected 1 anchor, found %d" % (label, found))
    return source.replace(anchor, replacement, 1)


FIELDS = r'''
    /* NOVA_FINAL_FORENSICS_V1: independent atomic observer fields only. */
    int nova_final_parser_loop_wall;
    int nova_final_parser_loop_count;
    int nova_final_parse_begin_wall;
    int nova_final_parse_end_wall;
    int nova_final_parse_busy;
    int nova_final_parse_calls;
    int nova_final_parse_duration;
    int nova_final_read_begin_wall;
    int nova_final_read_end_wall;
    int nova_final_read_busy;
    int nova_final_read_calls;
    int nova_final_read_duration;
    int nova_final_read_errors;
    int nova_final_wait_packets;
    int nova_final_wait_bytes;
    int nova_final_wait_sleep;
    int nova_final_wait_interrupt;
    int nova_final_read_retry;
    int nova_final_parser_reason;
'''

HEARTBEAT = r'''
    /* Lives in the independent 50ms rebuffer-controller thread: even when
     * the FFmpeg parser is blocked, this heartbeat keeps reporting its age. */
    int nova_final_aq_n = -1, nova_final_vq_n = -1;
    if (s->parser && s->parser->get_stats) {
        STREAM_PARSER_STATS nova_final_stats;
        STREAM_PARSER_STATS *nova_final_ps =
            s->parser->get_stats(s, &nova_final_stats);
        if (nova_final_ps) {
            nova_final_aq_n = nova_final_ps->audio_chunks;
            nova_final_vq_n = nova_final_ps->video_chunks;
        }
    }
    serprintf("NOVA_FINAL_HEARTBEAT: wallMs=%d epoch=%d play=%d paused=%d internalPause=%d seek=%d seekPause=%d rebuffer=%d parserState=%d parserInterrupt=%d loopWall=%d loopCount=%d parseBusy=%d parseBegin=%d parseEnd=%d parseCalls=%d parseDurationMs=%d readBusy=%d readBegin=%d readEnd=%d readCalls=%d readDurationMs=%d readErrors=%d waitPackets=%d waitBytes=%d waitSleep=%d waitInterrupt=%d readRetry=%d lastReason=%d rawUsed=%d rawCap=%d postDemuxBytes=%d aqPackets=%d vqPackets=%d audioPts=%d videoPts=%d demuxV=%d demuxA=%d hwInput=%d hwOutput=%d sink=%d rendered=%d lateDrops=%d\n",
        now, epoch, playing, s->paused, s->paused_internal,
        s->seek, s->seek_paused, buffering,
        thread_state_get(&s->parser_tstate), s->parser_interrupt,
        __atomic_load_n(&s->nova_final_parser_loop_wall, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_parser_loop_count, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_parse_busy, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_parse_begin_wall, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_parse_end_wall, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_parse_calls, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_parse_duration, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_read_busy, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_read_begin_wall, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_read_end_wall, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_read_calls, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_read_duration, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_read_errors, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_wait_packets, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_wait_bytes, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_wait_sleep, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_wait_interrupt, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_read_retry, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_parser_reason, __ATOMIC_RELAXED),
        raw_used, raw_capacity, packet_used, nova_final_aq_n, nova_final_vq_n,
        audio_pts, video_pts,
        __atomic_load_n(&s->nova_diag_demux_v, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_demux_a, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_codec_input, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_codec_output, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_sink_submitted, __ATOMIC_RELAXED),
        render_count,
        __atomic_load_n(&s->nova_diag_drop_late, __ATOMIC_RELAXED));
'''

PARSE_CALL = r'''                    /* Observe parser call wall time, without changing yield or
                     * parser return handling. */
                    int nova_final_begin = atime();
                    __atomic_store_n(&s->nova_final_parse_busy, 1, __ATOMIC_RELAXED);
                    __atomic_store_n(&s->nova_final_parse_begin_wall,
                        nova_final_begin, __ATOMIC_RELAXED);
                    __atomic_fetch_add(&s->nova_final_parse_calls, 1, __ATOMIC_RELAXED);
                    s->parser->parse( s );
                    int nova_final_duration = atime() - nova_final_begin;
                    __atomic_store_n(&s->nova_final_parse_duration,
                        nova_final_duration, __ATOMIC_RELAXED);
                    __atomic_store_n(&s->nova_final_parse_end_wall,
                        atime(), __ATOMIC_RELAXED);
                    __atomic_store_n(&s->nova_final_parse_busy, 0, __ATOMIC_RELAXED);
                    if (nova_final_duration >= 75 &&
                        atime() - nova_final_last_slow_log_ms >= 500) {
                        nova_final_last_slow_log_ms = atime();
                        serprintf("NOVA_FINAL_PARSE_SLOW: wallMs=%d durationMs=%d loop=%d parseCalls=%d paused=%d seek=%d reason=%d\n",
                            atime(), nova_final_duration,
                            __atomic_load_n(&s->nova_final_parser_loop_count, __ATOMIC_RELAXED),
                            __atomic_load_n(&s->nova_final_parse_calls, __ATOMIC_RELAXED),
                            s->paused, s->seek,
                            __atomic_load_n(&s->nova_final_parser_reason, __ATOMIC_RELAXED));
                    }
'''

PARSER_QUEUE = r'''
    /* Before every early WAIT branch: emit a 1Hz breakdown of actual FFmpeg
     * packet queues, not just the pre-demux 128 MiB raw warehouse.
     * Captures subtitle queues omitted from the legacy packetsUsed metric. */
    static int nova_final_last_queue_log_ms;
    int nova_final_now = atime();
    if (!nova_final_last_queue_log_ms ||
        nova_final_now - nova_final_last_queue_log_ms >= 1000) {
        nova_final_last_queue_log_ms = nova_final_now;
        int nova_final_raw_used = 0, nova_final_raw_cap = 0;
        nova_raw_stats(&ff_p->raw, &nova_final_raw_used, &nova_final_raw_cap);
        serprintf("NOVA_FINAL_PARSER_QUEUE: wallMs=%d epoch=%d rawUsed=%d rawCap=%d packetBudget=%d aqN=%d vqN=%d sqN=%d subCacheN=%d aqBytes=%d vqBytes=%d sqBytes=%d subCacheBytes=%d maxPacketCount=%d audioValid=%d videoValid=%d audioParsedMs=%d videoParsedMs=%d parsedSpanMs=%d audioPts=%d videoPts=%d demuxVpts=%d demuxApts=%d reason=%d seek=%d interrupt=%d audioEnd=%d videoEnd=%d\n",
            nova_final_now, s->seek_epoch,
            nova_final_raw_used, nova_final_raw_cap, ff_p->buffer_size,
            queue_packets(&ff_p->aq), queue_packets(&ff_p->vq),
            queue_packets(&ff_p->sq), queue_packets(&ff_p->sub_cache),
            queue_bytes(&ff_p->aq), queue_bytes(&ff_p->vq),
            queue_bytes(&ff_p->sq), queue_bytes(&ff_p->sub_cache),
            FF_QUEUE_MAX_PACKETS, s->audio->valid, s->video->valid,
            s->atime_parsed, s->vtime_parsed, s->time_parsed,
            s->audio_time, s->video_time,
            __atomic_load_n(&s->nova_diag_demux_video_pts, __ATOMIC_RELAXED),
            __atomic_load_n(&s->nova_diag_demux_audio_pts, __ATOMIC_RELAXED),
            __atomic_load_n(&s->nova_final_parser_reason, __ATOMIC_RELAXED),
            s->seek, s->parser_interrupt, s->audio_parse_end,
            s->video_parse_end);
    }
'''

READ_TRACE = r'''    int nova_final_read_t0 = atime();
    __atomic_store_n(&s->nova_final_parser_reason, 4, __ATOMIC_RELAXED);
    __atomic_store_n(&s->nova_final_read_busy, 1, __ATOMIC_RELAXED);
    __atomic_store_n(&s->nova_final_read_begin_wall,
        nova_final_read_t0, __ATOMIC_RELAXED);
    __atomic_fetch_add(&s->nova_final_read_calls, 1, __ATOMIC_RELAXED);
    int result = av_read_frame(fmt, &packet);
    int nova_final_read_ms = atime() - nova_final_read_t0;
    __atomic_store_n(&s->nova_final_read_busy, 0, __ATOMIC_RELAXED);
    __atomic_store_n(&s->nova_final_read_end_wall, atime(), __ATOMIC_RELAXED);
    __atomic_store_n(&s->nova_final_read_duration,
        nova_final_read_ms, __ATOMIC_RELAXED);
    __atomic_store_n(&s->nova_final_parser_reason,
        result < 0 ? 5 : 0, __ATOMIC_RELAXED);
    if (result < 0)
        __atomic_fetch_add(&s->nova_final_read_errors, 1, __ATOMIC_RELAXED);
    if (nova_final_read_ms >= 75) {
        static int nova_final_last_slow_read_log_ms;
        if (atime() - nova_final_last_slow_read_log_ms >= 500) {
            nova_final_last_slow_read_log_ms = atime();
            serprintf("NOVA_FINAL_READ_SLOW: wallMs=%d elapsedMs=%d result=%d eof=%d ioError=%d position=%lld packetBudget=%d aqN=%d vqN=%d sqN=%d rawReadActive=%d\n",
                atime(), nova_final_read_ms, result,
                fmt->pb ? fmt->pb->eof_reached : -1,
                fmt->pb ? fmt->pb->error : 0,
                (long long)(fmt->pb ? avio_tell(fmt->pb) : -1),
                ff_p->buffer_size,
                queue_packets(&ff_p->aq), queue_packets(&ff_p->vq),
                queue_packets(&ff_p->sq), ff_p->raw.enabled);
        }
    }
'''

RENDER_QUEUE = r'''
            /* Render queue depths and exact anchor remain available even
             * when all presented frames become late-drop decisions. */
            INT64 nova_final_render_now = atime64();
            if (s && (!p->nova_final_render_log_ms ||
                      nova_final_render_now - p->nova_final_render_log_ms >= 1000)) {
                p->nova_final_render_log_ms = nova_final_render_now;
                serprintf("NOVA_FINAL_RENDER_Q: wallMs=%lld epoch=%d frameMs=%d audioMs=%d videoMs=%d getQ=%d decQ=%d outQ=%d vencQ=%d renderSeq=%llu droppedRun=%d renderOffsetNs=%lld targetOffsetNs=%lld renderFromAudio=%d reanchor=%d seekReanchor=%d renderGen=%u frameRateNum=%d frameRateDen=%d hwInput=%d hwOutput=%d sinkSubmit=%d rendered=%d lateDrops=%d\n",
                    (long long)nova_final_render_now,
                    s->seek_epoch, f->time, s->audio_time, s->video_time,
                    frame_q_count(&p->locked.get_q),
                    frame_q_count(&p->locked.dec_q),
                    frame_q_count(&p->locked.out_q),
                    frame_q_count(&p->locked.venc_q),
                    (unsigned long long)p->render_submit_seq, p->dropped,
                    (long long)p->render_offset_ns,
                    (long long)p->target_offset_ns,
                    p->render_offset_from_audio, p->pending_reanchor,
                    p->pending_seek_reanchor, p->render_generation,
                    p->video_frame_rate_num, p->video_frame_rate_den,
                    __atomic_load_n(&s->nova_diag_codec_input, __ATOMIC_RELAXED),
                    __atomic_load_n(&s->nova_diag_codec_output, __ATOMIC_RELAXED),
                    __atomic_load_n(&s->nova_diag_sink_submitted, __ATOMIC_RELAXED),
                    __atomic_load_n(&s->nova_diag_render_submitted, __ATOMIC_RELAXED),
                    __atomic_load_n(&s->nova_diag_drop_late, __ATOMIC_RELAXED));
            }
'''

CODEC_SEND = r'''    int nova_final_codec_send_t0 = atime();
    ret = sfdec_send_input(p->sfdec, d->data[0], d->size, (int64_t)media_time * 1000, d->type == I_VOP ? 1 : 0, 0);
    int nova_final_codec_send_ms = atime() - nova_final_codec_send_t0;
    if (nova_final_codec_send_ms >= 75)
        serprintf("NOVA_FINAL_CODEC_INPUT_SLOW: wallMs=%d durationMs=%d mediaMs=%d bytes=%d result=%lld\n",
            atime(), nova_final_codec_send_ms, media_time, d->size, (long long)ret);
'''

CODEC_READ = r'''        int ret = sfdec_read(p->sfdec, -1, &read_out);
        int took = time_update_time() - start;
        /* time_update_time is in 100-microsecond ticks, not milliseconds. */
        if (took >= 750)
            serprintf("NOVA_FINAL_CODEC_OUTPUT_SLOW: wallMs=%d durationMs=%d ret=%d\n",
                atime(), took / 10, ret);
'''


def change(path, edits):
    original = path.read_text()
    changed = original
    for label, anchor, replacement in edits:
        changed = once(changed, anchor, replacement, label)
    if changed == original:
        raise RuntimeError("no modifications: " + str(path))
    path.write_text(changed)
    return {"path": str(path), "added_bytes": len(changed) - len(original)}


def patch_header(root):
    return change(root / "Include/stream.h", [
        ("append observer fields to existing STREAM",
         "\tint\t\trebuffer_capacity_bytes;\n",
         "\tint\t\trebuffer_capacity_bytes;\n" + FIELDS),
    ])


def patch_video(root):
    path = root / "Source/stream_video.c"
    src = path.read_text()
    src = once(src,
        '    serprintf("NOVA_AVDIAG_SAMPLE: wallMs=%d',
        HEARTBEAT + '    serprintf("NOVA_AVDIAG_SAMPLE: wallMs=%d',
        "independent heartbeat before AV sample")
    start = "static void *_parser_thread( void *data )"
    stop = "static void *_player_thread( void *data )"
    if src.count(start) != 1 or src.count(stop) != 1:
        raise RuntimeError("parser thread function delimiters changed")
    before, region = src.split(start, 1)
    body, after = region.split(stop, 1)
    body = once(body, "\tint last_time = 0;\n",
                "\tint last_time = 0;\n\tint nova_final_last_slow_log_ms = 0;\n",
                "parser thread local slow timer")
    body = once(body, "\t\tthread_state_ack( &s->parser_tstate );\n",
                "\t\tthread_state_ack( &s->parser_tstate );\n"
                "\t\t__atomic_store_n(&s->nova_final_parser_loop_wall,\n"
                "\t\t\tatime(), __ATOMIC_RELAXED);\n"
                "\t\t__atomic_fetch_add(&s->nova_final_parser_loop_count,\n"
                "\t\t\t1, __ATOMIC_RELAXED);\n",
                "parser worker actual execution heartbeat")
    body = once(body, "\t\t\t\t\ts->parser->parse( s );\n",
                PARSE_CALL, "parser call latency")
    src = before + start + body + stop + after
    path.write_text(src)
    return {"path": str(path), "added_bytes": len(src) - len(path.read_text())}


def patch_ffmpeg(root):
    path = root / "Source/stream_parser_ffmpeg.c"
    src = path.read_text()
    start = "static int _parse_once( STREAM *s, int *timestamp)"
    stop = "\nstatic int _parse( STREAM *s)"
    if src.count(start) != 1 or src.count(stop) != 1:
        raise RuntimeError("FFmpeg parser function delimiters changed")
    before, region = src.split(start, 1)
    body, after = region.split(stop, 1)
    body = once(body, "\tAVFormatContext *fmt = ff_p->fmt;\n",
                "\tAVFormatContext *fmt = ff_p->fmt;\n" + PARSER_QUEUE,
                "full FFmpeg packet queue sample")
    body = once(body, "\tif( ff_p->sleeping ) {\n",
                "\tif( ff_p->sleeping ) {\n"
                "\t\t__atomic_fetch_add(&s->nova_final_wait_sleep, 1, __ATOMIC_RELAXED);\n"
                "\t\t__atomic_store_n(&s->nova_final_parser_reason, 1, __ATOMIC_RELAXED);\n",
                "FFmpeg sleep early return")
    body = once(body, '\tif (!ff_p->seeking && !audio_starved &&\n',
                '\tif (!ff_p->seeking && !audio_starved &&\n',
                "unique queue backpressure anchor check")
    anchor_packets = "DBGP2\t\tserprintf(\"FFMPEG: packet queue full, waiting for consumption (audio=%d)\\n\", audio_packets);\n\t\treturn FF_PARSE_WAIT;"
    body = once(body, anchor_packets,
                "__atomic_fetch_add(&s->nova_final_wait_packets, 1, __ATOMIC_RELAXED);\n"
                "\t\t__atomic_store_n(&s->nova_final_parser_reason, 2, __ATOMIC_RELAXED);\n"
                + anchor_packets, "queue packet-count backpressure")
    body = once(body,
                "\tif( mem_used > ff_p->buffer_size && !audio_starved && !ff_p->seeking ) {\n",
                "\tif( mem_used > ff_p->buffer_size && !audio_starved && !ff_p->seeking ) {\n"
                "\t\t__atomic_fetch_add(&s->nova_final_wait_bytes, 1, __ATOMIC_RELAXED);\n"
                "\t\t__atomic_store_n(&s->nova_final_parser_reason, 3, __ATOMIC_RELAXED);\n",
                "queue byte-budget backpressure")
    body = once(body, "\tint result = av_read_frame(fmt, &packet);\n",
                READ_TRACE, "timed FFmpeg av_read_frame")
    body = once(body,
                "\t\tif (result == AVERROR(EAGAIN) || result == AVERROR(EINTR)) {\n",
                "\t\tif (result == AVERROR(EAGAIN) || result == AVERROR(EINTR)) {\n"
                "\t\t\t__atomic_fetch_add(&s->nova_final_read_retry, 1, __ATOMIC_RELAXED);\n"
                "\t\t\t__atomic_store_n(&s->nova_final_parser_reason, 6, __ATOMIC_RELAXED);\n",
                "recoverable FFmpeg read waits")
    src = before + start + body + stop + after
    path.write_text(src)
    return {"path": str(path), "added_bytes": len(src) - len(path.read_text())}


def patch_codec(root):
    path = root / "Source/codec_sfdec2.c"
    src = path.read_text()
    src = once(src, "    INT64 nova_trace_start_ms;\n",
               "    INT64 nova_trace_start_ms;\n"
               "    INT64 nova_final_render_log_ms;\n",
               "extend per-decoder final trace state")
    src = once(src,
        "\t\t\tINT64 av_delay_ns = (INT64)(int)(p->effective_av_delay_ms * p->video_timeline.inv_speed) * 1000000LL;\n",
        RENDER_QUEUE +
        "\t\t\tINT64 av_delay_ns = (INT64)(int)(p->effective_av_delay_ms * p->video_timeline.inv_speed) * 1000000LL;\n",
        "bounded render queue trace")
    src = once(src,
        "\tret = sfdec_send_input(p->sfdec, d->data[0], d->size, (int64_t)media_time * 1000, d->type == I_VOP ? 1 : 0, 0);\n",
        CODEC_SEND, "timed MediaCodec input")
    src = once(src,
        "\t\tint ret = sfdec_read(p->sfdec, -1, &read_out);\n\n\t\tint took = time_update_time() - start;\n",
        CODEC_READ, "timed MediaCodec output (correct units)")
    path.write_text(src)
    return {"path": str(path), "added_bytes": len(src) - len(path.read_text())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--native", type=Path, required=True)
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()
    root = args.native
    changed = [
        patch_header(root),
        patch_video(root),
        patch_ffmpeg(root),
        patch_codec(root),
    ]
    report = {
        "version": "NOVA_FINAL_FORENSICS_V1",
        "mode": "observation only; no playback control changed",
        "sampling": "1 Hz independent heartbeat, queue and renderer; slow calls on threshold",
        "scope": [
            "parser_thread_running_and_busy",
            "parser_call_duration",
            "av_read_frame_blocking_duration_and_errors",
            "audio_video_subtitle_packet_queues_and_limits",
            "raw_128mib_vs_postdemux_packet_pressure",
            "decoder_input_output_slow_call_signals",
            "decoder_surface_queue_depths",
            "existing_video_deadline_audio_anchor_and_late_drops",
            "existing_audio_timestamp_and_rebuffer_state",
        ],
        "sources": changed,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print("NOVA_FINAL_FORENSICS_V1=PATCHED", json.dumps(report))


if __name__ == "__main__":
    main()
