#!/usr/bin/env python3
"""Run594: observational A/V pipeline diagnostics on pinned AVOS native sources.

No network/RAW128 producer, ring allocation, threshold, scheduling, decoder
decision, codec input, audio output, packet routing or timestamp math is changed.
Emits 1 Hz summaries and bounded anomaly events. Counts "render submitted"
separately from actual display (Amlogic frame-present callback unavailable).
"""
import argparse
import json
from pathlib import Path

FIELDS = (
    "demux_v", "demux_a", "demux_corrupt", "demux_errors",
    "demux_video_pts", "demux_audio_pts", "demux_last_v_wall", "demux_last_a_wall",
    "codec_input", "codec_input_pts", "codec_input_wall",
    "codec_output", "codec_output_pts", "codec_output_wall", "codec_error",
    "render_submitted", "render_pts", "render_wall", "render_errors",
    "drop_late", "drop_startup", "drop_sink",
    "sink_submitted", "sink_pts", "sink_wall",
    "audio_writes", "audio_write_wall", "audio_write_pts", "audio_write_errors",
)
WATCH = (
    "tick_ms", "log_ms", "last_render_count", "last_render_wall",
    "last_render_pts", "audio_at_last_render", "stall_begin_wall",
    "stall_last_render_pts", "last_epoch", "stall_active",
)

def once(src, needle, replacement, label):
    found = src.count(needle)
    if found != 1:
        raise RuntimeError(f"{label}: expected one anchor, got {found}: {needle[:110]!r}")
    return src.replace(needle, replacement, 1)

def patch(path, edits):
    original = path.read_text()
    src = original
    for label, needle, replacement in edits:
        src = once(src, needle, replacement, label)
    if src == original:
        raise RuntimeError(f"No modifications applied to {path}")
    path.write_text(src)
    return (path.name, len(src) - len(original))

def struct_fields():
    return (
        "\n\t/* NOVA_AVDIAG_V1: observational counters; kept outside RAW128. */\n"
        + "".join(f"\tvolatile int nova_diag_{name};\n" for name in FIELDS)
        + "".join(f"\tint nova_diag_{name};\n" for name in WATCH)
    )

def diag_incr(field, p="s"):
    return f"__atomic_fetch_add(&{p}->nova_diag_{field}, 1, __ATOMIC_RELAXED);"

def diag_set(field, val, p="s"):
    return f"__atomic_store_n(&{p}->nova_diag_{field}, {val}, __ATOMIC_RELAXED);"

def patch_header(root):
    path = root / "Include/stream.h"
    target = "\tint\t\trebuffer_capacity_bytes;\n"
    edits = [("STREAM diagnostic tail fields", target, target + struct_fields())]
    return patch(path, edits)

MONITOR = r'''
/* NOVA_AVDIAG_V1: a diagnostic-only sampler on the existing 50ms controller.
 * No extra workers, timer interrupts, frame holds, codec resets or IO reads.
 * All counters are atomic int snapshots. AudioTrack is sampled at most 1 Hz.
 */
static void nova_avdiag_tick(STREAM *s)
{
    if (!s) return;
    int now = atime();
    if (s->nova_diag_tick_ms && now - s->nova_diag_tick_ms < 250)
        return;
    s->nova_diag_tick_ms = now;
    int epoch = s->seek_epoch;
    int render_count = __atomic_load_n(&s->nova_diag_render_submitted, __ATOMIC_RELAXED);
    int render_pts = __atomic_load_n(&s->nova_diag_render_pts, __ATOMIC_RELAXED);
    int audio_pts = s->audio_time;
    int video_pts = s->video_time;
    int buffering = __atomic_load_n(&s->rebuffering, __ATOMIC_ACQUIRE);
    int playing = s->video && s->audio && s->video->valid && s->audio->valid &&
        !s->paused && !s->paused_internal && !s->seek && !s->seek_paused &&
        !s->stream_end && !buffering && s->video_error == VE_NO_ERROR;

    if (s->nova_diag_last_epoch != epoch) {
        if (s->nova_diag_stall_active) {
            serprintf("NOVA_AVDIAG_STALL_INTERRUPTED: reason=seek epoch=%d heldWallMs=%d\n",
                epoch, now - s->nova_diag_stall_begin_wall);
        }
        s->nova_diag_last_epoch = epoch;
        s->nova_diag_last_render_count = render_count;
        s->nova_diag_last_render_wall = now;
        s->nova_diag_last_render_pts = render_pts;
        s->nova_diag_audio_at_last_render = audio_pts;
        s->nova_diag_stall_active = 0;
    } else if (!playing) {
        if (s->nova_diag_stall_active) {
            serprintf("NOVA_AVDIAG_STALL_INTERRUPTED: reason=not_playing paused=%d rebuffer=%d seek=%d\n",
                s->paused, buffering, s->seek);
        }
        s->nova_diag_stall_active = 0;
        s->nova_diag_last_render_count = render_count;
        s->nova_diag_last_render_wall = now;
        s->nova_diag_audio_at_last_render = audio_pts;
    } else if (render_count != s->nova_diag_last_render_count) {
        if (s->nova_diag_stall_active) {
            serprintf("NOVA_AVDIAG_STALL_END: wallMs=%d audioAdvanceMs=%d renderPtsBefore=%d renderPtsNow=%d skippedVideoPtsMs=%d audioPts=%d videoPts=%d dropLate=%d codecOutput=%d\n",
                now - s->nova_diag_stall_begin_wall,
                audio_pts - s->nova_diag_audio_at_last_render,
                s->nova_diag_stall_last_render_pts, render_pts,
                render_pts - s->nova_diag_stall_last_render_pts,
                audio_pts, video_pts,
                __atomic_load_n(&s->nova_diag_drop_late, __ATOMIC_RELAXED),
                __atomic_load_n(&s->nova_diag_codec_output, __ATOMIC_RELAXED));
        }
        s->nova_diag_stall_active = 0;
        s->nova_diag_last_render_count = render_count;
        s->nova_diag_last_render_wall = now;
        s->nova_diag_last_render_pts = render_pts;
        s->nova_diag_audio_at_last_render = audio_pts;
    } else if (render_count > 0 && !s->nova_diag_stall_active &&
               now - s->nova_diag_last_render_wall >= 2000 &&
               audio_pts >= s->nova_diag_audio_at_last_render + 1000) {
        s->nova_diag_stall_active = 1;
        s->nova_diag_stall_begin_wall = now;
        s->nova_diag_stall_last_render_pts = render_pts;
        serprintf("NOVA_AVDIAG_STALL_BEGIN: noRenderSubmitMs=%d audioAdvanceMs=%d audioPts=%d videoPts=%d lastRenderPts=%d hwInput=%d hwOutput=%d sinkSubmit=%d demuxVideo=%d demuxAudio=%d rebuffer=%d epoch=%d\n",
            now - s->nova_diag_last_render_wall,
            audio_pts - s->nova_diag_audio_at_last_render,
            audio_pts, video_pts, render_pts,
            __atomic_load_n(&s->nova_diag_codec_input, __ATOMIC_RELAXED),
            __atomic_load_n(&s->nova_diag_codec_output, __ATOMIC_RELAXED),
            __atomic_load_n(&s->nova_diag_sink_submitted, __ATOMIC_RELAXED),
            __atomic_load_n(&s->nova_diag_demux_v, __ATOMIC_RELAXED),
            __atomic_load_n(&s->nova_diag_demux_a, __ATOMIC_RELAXED),
            buffering, epoch);
    }

    /* 1 Hz state snapshot, even while video is stuck. Existing RAW128
     * producerBps/consumerBps remain in the untouched NOVA_RAW128 logger. */
    if (s->nova_diag_log_ms && now - s->nova_diag_log_ms < 1000)
        return;
    s->nova_diag_log_ms = now;
    int raw_used = -1, packet_used = -1, raw_capacity = -1;
    if (s->parser && s->parser->get_stats) {
        STREAM_PARSER_STATS stats;
        STREAM_PARSER_STATS *ps = s->parser->get_stats(s, &stats);
        if (ps) {
            raw_used = ps->buffer2_used;
            packet_used = ps->buffer_used;
            raw_capacity = ps->buffer2_size;
        }
    }
    AUDIO_PRESENTATION_SNAPSHOT ap = {0};
    int audio_hw_valid = 0;
    if (s->audio_ctx && stream_audio_read_acquire(s)) {
        if (s->audio_ctx)
            audio_hw_valid = audio_interface_get_presentation_snapshot(s->audio_ctx, &ap);
        stream_audio_read_release(s);
    }
    serprintf("NOVA_AVDIAG_SAMPLE: wallMs=%d epoch=%d playing=%d paused=%d seek=%d rebuffer=%d rawUsed=%d rawCap=%d packetsUsed=%d demuxV=%d demuxA=%d demuxCorrupt=%d demuxErr=%d demuxVpts=%d demuxApts=%d demuxVlastWall=%d demuxAlastWall=%d hwIn=%d hwOut=%d hwErr=%d hwInPts=%d hwOutPts=%d hwInWall=%d hwOutWall=%d sinkSubmit=%d sinkPts=%d renderSubmit=%d renderPts=%d renderWall=%d renderErr=%d dropLate=%d dropStartup=%d dropSink=%d audioWrite=%d audioWriteErr=%d audioPts=%d videoPts=%d ptsGapMs=%d hwAudioValid=%d hwAudioState=%d hwAudioTimestampFrames=%llu hwAudioPlayheadFrames=%llu hwAudioRate=%d hwAudioUnderruns=%d hwAudioAdvanceWallMs=%lld hardwareDisplayConfirmed=0\n",
        now, epoch, playing, s->paused, s->seek, buffering,
        raw_used, raw_capacity, packet_used,
        __atomic_load_n(&s->nova_diag_demux_v, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_demux_a, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_demux_corrupt, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_demux_errors, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_demux_video_pts, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_demux_audio_pts, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_demux_last_v_wall, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_demux_last_a_wall, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_codec_input, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_codec_output, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_codec_error, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_codec_input_pts, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_codec_output_pts, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_codec_input_wall, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_codec_output_wall, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_sink_submitted, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_sink_pts, __ATOMIC_RELAXED),
        render_count, render_pts,
        __atomic_load_n(&s->nova_diag_render_wall, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_render_errors, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_drop_late, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_drop_startup, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_drop_sink, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_audio_writes, __ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_diag_audio_write_errors, __ATOMIC_RELAXED),
        audio_pts, video_pts,
        (audio_pts >= 0 && render_pts >= 0) ? audio_pts - render_pts : 0,
        audio_hw_valid, audio_hw_valid ? ap.state : -1,
        (unsigned long long)(audio_hw_valid ? ap.timestamp_frames : 0),
        (unsigned long long)(audio_hw_valid ? ap.playback_head_frames : 0),
        audio_hw_valid ? ap.rate : 0, audio_hw_valid ? ap.underrun_count : -1,
        (long long)(audio_hw_valid ? ap.last_advance_wall_ms : -1));
}
'''

def patch_video(root):
    path = root / "Source/stream_video.c"
    rebuffer_insert = "static int _nova_rebuffer_eof( STREAM *s )"
    sleep = "\n        msec_sleep( NOVA_REBUFFER_POLL_MS );"
    sink_count = "\ts->sink_delay = frame->blit_time - s->video_sink->put( s->video_sink, frame ); \t\n\ts->video_sink_count ++;\n"
    sink_drop = "\t\ts->video_drop   = (frame->blit_time == -1);\n"
    pause_anchor = "\twas_paused = s->paused;\n"
    unpause_anchor = "void stream_un_pause( STREAM *s, int was_paused )\n{\n"
    edits = [
        ("sample helper before RAW rebuffer controller", rebuffer_insert,
         MONITOR + "\n" + rebuffer_insert),
        ("nonblocking observation in existing 50ms loop", sleep,
         "\n        nova_avdiag_tick(s);" + sleep),
        ("video sink submitted counter", sink_count,
         sink_count + f"\t{diag_incr('sink_submitted')}\n"
         + f"\t{diag_set('sink_pts','frame->time')}\n"
         + f"\t{diag_set('sink_wall','atime()')}\n"),
        ("sink return drop accounting", sink_drop,
         sink_drop + f"\t\tif(s->video_drop) {diag_incr('drop_sink')}\n"),
        ("pause diagnostic", pause_anchor,
         pause_anchor + '\tserprintf("NOVA_AVDIAG_PAUSE: stream=%p epoch=%d userPaused=%d audioPts=%d videoPts=%d rebuffer=%d\\n",\n'
         '\t\t(void *)s, s->seek_epoch, was_paused, s->audio_time, s->video_time,\n'
         '\t\t__atomic_load_n(&s->rebuffering, __ATOMIC_ACQUIRE));\n'),
        ("unpause diagnostic", unpause_anchor,
         unpause_anchor + '\tif(s) serprintf("NOVA_AVDIAG_UNPAUSE: stream=%p epoch=%d wasPaused=%d audioPts=%d videoPts=%d rebuffer=%d\\n",\n'
         '\t\t(void *)s, s->seek_epoch, was_paused, s->audio_time, s->video_time,\n'
         '\t\t__atomic_load_n(&s->rebuffering, __ATOMIC_ACQUIRE));\n'),
    ]
    return patch(path, edits)

def patch_demux(root):
    path = root / "Source/stream_parser_ffmpeg.c"
    pkt = "\tint stream = packet.stream_index;\n"
    snippet = r'''
    /* Packet routing evidence: no packet forwarding/queue behavior changed. */
    if (s->video->valid && stream == s->video->stream) {
        __atomic_fetch_add(&s->nova_diag_demux_v, 1, __ATOMIC_RELAXED);
        __atomic_store_n(&s->nova_diag_demux_video_pts,
            packet.pts == AV_NOPTS_VALUE ? -1 : (int)GET_VIDEO_TS(packet.pts),
            __ATOMIC_RELAXED);
        __atomic_store_n(&s->nova_diag_demux_last_v_wall, atime(), __ATOMIC_RELAXED);
    } else if (s->audio->valid && stream == s->audio->stream) {
        __atomic_fetch_add(&s->nova_diag_demux_a, 1, __ATOMIC_RELAXED);
        __atomic_store_n(&s->nova_diag_demux_audio_pts,
            packet.pts == AV_NOPTS_VALUE ? -1 : (int)GET_AUDIO_TS(packet.pts),
            __ATOMIC_RELAXED);
        __atomic_store_n(&s->nova_diag_demux_last_a_wall, atime(), __ATOMIC_RELAXED);
    }
    if (packet.flags & AV_PKT_FLAG_CORRUPT) {
        int n = __atomic_add_fetch(&s->nova_diag_demux_corrupt, 1, __ATOMIC_RELAXED);
        if (n <= 3 || n % 30 == 0)
            serprintf("NOVA_AVDIAG_DEMUX_CORRUPT: stream=%d pts=%lld size=%d corruptCount=%d\n",
                stream, (long long)packet.pts, packet.size, n);
    }
'''
    err="if (result != AVERROR_EOF) return parser_input_error(s, result, demux_result);"
    err_repl="""if (result != AVERROR_EOF) {
            __atomic_fetch_add(&s->nova_diag_demux_errors, 1, __ATOMIC_RELAXED);
            serprintf("NOVA_AVDIAG_DEMUX_ERROR: rc=%d avioError=%d seek=%d epoch=%d\\n",
                result, fmt->pb ? fmt->pb->error : 0, s->seek, s->seek_epoch);
            return parser_input_error(s, result, demux_result);
        }"""
    return patch(path, [
        ("post demux media counter",pkt,pkt+snippet),
        ("av_read_frame hard failures",err,err_repl),
    ])

def patch_audio(root):
    path = root / "Source/stream_sink_audio.c"
    needle = "\tint ret = audio_interface_write( s->audio_ctx, frame->data, frame->size );\n"
    snippet = r'''    if (ret > 0) {
        __atomic_fetch_add(&s->nova_diag_audio_writes, 1, __ATOMIC_RELAXED);
        __atomic_store_n(&s->nova_diag_audio_write_wall, atime(), __ATOMIC_RELAXED);
        __atomic_store_n(&s->nova_diag_audio_write_pts, s->audio_time, __ATOMIC_RELAXED);
    } else if (ret < 0 && ret != AUDIO_WRITE_RETRY && ret != AUDIO_WRITE_RESTARTED) {
        int n = __atomic_add_fetch(&s->nova_diag_audio_write_errors, 1, __ATOMIC_RELAXED);
        if (n <= 3 || n % 30 == 0)
            serprintf("NOVA_AVDIAG_AUDIO_WRITE_ERROR: rc=%d mediaPts=%d errorCount=%d\n",
                ret, s->audio_time, n);
    }
'''
    # note: interrupted output (-EAGAIN/-ESTALE) is a normal retry, not corruption.
    return patch(path,[("audio output accepted writes",needle,needle+snippet)])

def patch_hw(root):
    path = root / "Source/codec_sfdec2.c"
    anchor = "\tret = sfdec_send_input(p->sfdec, d->data[0], d->size, (int64_t)media_time * 1000, d->type == I_VOP ? 1 : 0, 0);\n"
    add = r'''    STREAM *nova_diag_s = (STREAM *)dec->ctx;
    if (nova_diag_s) {
        if (ret == d->size && ret > 0) {
            __atomic_fetch_add(&nova_diag_s->nova_diag_codec_input, 1, __ATOMIC_RELAXED);
            __atomic_store_n(&nova_diag_s->nova_diag_codec_input_pts, media_time, __ATOMIC_RELAXED);
            __atomic_store_n(&nova_diag_s->nova_diag_codec_input_wall, time_update_time(), __ATOMIC_RELAXED);
        } else if (ret < 0 || (ret > 0 && ret != d->size)) {
            __atomic_fetch_add(&nova_diag_s->nova_diag_codec_error, 1, __ATOMIC_RELAXED);
            serprintf("NOVA_AVDIAG_CODEC_INPUT_ERROR: rc=%lld requested=%d mediaPts=%d epoch=%d\n",
                (long long)ret, d->size, media_time, nova_diag_s->seek_epoch);
        }
    }
'''
    anchor2 = "\t\tint took = time_update_time() - start;\n\n\t\tpthread_mutex_lock(&p->locked.mtx);\n"
    add2 = r'''        STREAM *nova_diag_s = p->dec ? (STREAM *)p->dec->ctx : NULL;
        if (nova_diag_s) {
            if (ret >= 0 && (read_out.flag & SFDEC_READ_BUF)) {
                __atomic_fetch_add(&nova_diag_s->nova_diag_codec_output, 1, __ATOMIC_RELAXED);
                __atomic_store_n(&nova_diag_s->nova_diag_codec_output_pts,
                    (int)(read_out.buf.time_us / 1000), __ATOMIC_RELAXED);
                __atomic_store_n(&nova_diag_s->nova_diag_codec_output_wall,
                    time_update_time(), __ATOMIC_RELAXED);
            }
            if (ret < 0 || (ret >= 0 && (read_out.flag & SFDEC_READ_INVALID))) {
                __atomic_fetch_add(&nova_diag_s->nova_diag_codec_error, 1, __ATOMIC_RELAXED);
                serprintf("NOVA_AVDIAG_CODEC_OUTPUT_ERROR: rc=%d flags=%d waitMs=%d tookMs=%d epoch=%d\n",
                    ret, ret < 0 ? -1 : read_out.flag, wait, took, nova_diag_s->seek_epoch);
            } else if (took > 750 && !nova_diag_s->paused && !nova_diag_s->seek) {
                serprintf("NOVA_AVDIAG_CODEC_OUTPUT_WAIT: waitMs=%d tookMs=%d epoch=%d audioPts=%d videoPts=%d\n",
                    wait, took, nova_diag_s->seek_epoch, nova_diag_s->audio_time, nova_diag_s->video_time);
            }
        }
'''
    render = "\t\t\t\t\tp->render_submit_seq++;\n"
    render_add = r'''                    if (s) {
                        __atomic_fetch_add(&s->nova_diag_render_submitted, 1, __ATOMIC_RELAXED);
                        __atomic_store_n(&s->nova_diag_render_pts, f->time, __ATOMIC_RELAXED);
                        __atomic_store_n(&s->nova_diag_render_wall, time_update_time(), __ATOMIC_RELAXED);
                    }
'''
    late = '\t\t\t\tp->dropped++;\n\t\t\t\tDBGSI serprintf("android_sync: late frame drop'
    late_add = r'''                if (s) {
                    int n = __atomic_add_fetch(&s->nova_diag_drop_late, 1, __ATOMIC_RELAXED);
                    if (n <= 3 || n % 120 == 0)
                        serprintf("NOVA_AVDIAG_DROP: reason=late fPts=%d latenessMs=%lld totalLate=%d audioPts=%d epoch=%d\n",
                            f->time, (long long)(lateness_ns / NSEC_PER_MSEC), n,
                            s->audio_time, s->seek_epoch);
                }
'''
    startup='\t\t\t\tp->dropped++;\n\t\t\t\t// Keep flush from invalidating'
    startup_add=r'''                if (s) {
                    int n = __atomic_add_fetch(&s->nova_diag_drop_startup, 1, __ATOMIC_RELAXED);
                    if (n <= 3 || n % 120 == 0)
                        serprintf("NOVA_AVDIAG_DROP: reason=startup_passthrough_hold fPts=%d total=%d epoch=%d\n",
                            f->time, n, s->seek_epoch);
                }
'''
    render_error="\t\tif (render_error) {\n\t\t\tp->locked.error = 1;\n"
    render_err_add=r'''            if (s) {
                __atomic_fetch_add(&s->nova_diag_render_errors, 1, __ATOMIC_RELAXED);
                serprintf("NOVA_AVDIAG_RENDER_ERROR: rc=%d framePts=%d epoch=%d\n",
                    render_error, f ? f->time : -1, s->seek_epoch);
            }
'''
    flush="static int videodec_flush(STREAM_DEC_VIDEO *dec)\n{\n"
    flush_log=r'''    STREAM *nova_diag_s = (STREAM *)dec->ctx;
    if (nova_diag_s)
        serprintf("NOVA_AVDIAG_CODEC_FLUSH: epoch=%d hwInput=%d hwOutput=%d renderSubmit=%d lateDrops=%d\n",
            nova_diag_s->seek_epoch,
            __atomic_load_n(&nova_diag_s->nova_diag_codec_input, __ATOMIC_RELAXED),
            __atomic_load_n(&nova_diag_s->nova_diag_codec_output, __ATOMIC_RELAXED),
            __atomic_load_n(&nova_diag_s->nova_diag_render_submitted, __ATOMIC_RELAXED),
            __atomic_load_n(&nova_diag_s->nova_diag_drop_late, __ATOMIC_RELAXED));
'''
    return patch(path,[
        ("codec input accepted/error",anchor,anchor+add),
        ("codec output result and latency",anchor2,anchor2.replace("\t\tpthread_mutex_lock",add2+"\t\tpthread_mutex_lock")),
        ("timed surface render submission",render,render+render_add),
        ("late frame drop reason",late,"\t\t\t\tp->dropped++;\n"+late_add+'\t\t\t\tDBGSI serprintf("android_sync: late frame drop'),
        ("startup hold drop reason",startup,"\t\t\t\tp->dropped++;\n"+startup_add+"\t\t\t\t// Keep flush from invalidating"),
        ("hardware render failure",render_error,"\t\tif (render_error) {\n"+render_err_add+"\t\t\tp->locked.error = 1;\n"),
        ("codec flush reason correlation",flush,flush+flush_log),
    ])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--native",required=True,type=Path)
    ap.add_argument("--report",type=Path)
    args=ap.parse_args()
    root=args.native
    for path in ["Include/stream.h","Source/stream_video.c","Source/stream_parser_ffmpeg.c",
                 "Source/stream_sink_audio.c","Source/codec_sfdec2.c"]:
        if not (root/path).is_file():
            raise SystemExit(f"missing pinned AVOS source: {root/path}")
    result=[]
    result.append(patch_header(root))
    result.append(patch_video(root))
    result.append(patch_demux(root))
    result.append(patch_audio(root))
    result.append(patch_hw(root))
    data={"version":"NOVA_AVDIAG_V1","mode":"observational","sample_interval_ms":1000,
          "stall_detector_interval_ms":250,"stall_begin_no_submit_ms":2000,
          "stall_audio_advance_ms":1000,
          "observed":["raw_plus_packet_stats","packet_pts","decoder_input","decoder_output",
                      "surface_submission","drop_reason","audio_playhead","audio_underrun","sync"],
          "unavailable":["physical_hardware_display_confirmation","pixel_corruption_without_visual_probe"],
          "touches":result,"network_buffer_logic_changed":False}
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(data,indent=2)+"\n")
    print("NOVA_AVDIAG_V1=PATCHED",json.dumps(data))
if __name__=="__main__":
    main()
