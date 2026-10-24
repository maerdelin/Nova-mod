#!/usr/bin/env python3
"""Run startup-freeze root-cause tracing on top of existing AVOS AV diagnostics.

Observation ONLY: no changed codec control flow, stream timing, rendering
thresholds, RAW128 buffer, seek, retry, or audio pipeline. Targets the first
three minutes of playback and the first late-frame transition, not generic
high-volume debug output. Fails closed if pinned AVOS source anchors drift.
"""
import argparse
import json
from pathlib import Path


def once(src, old, new, label):
    count = src.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source anchor, found {count}")
    return src.replace(old, new, 1)


def change(path, edits):
    before = path.read_text()
    after = before
    for label, old, new in edits:
        after = once(after, old, new, label)
    if after == before:
        raise RuntimeError("no changed diagnostic source: " + str(path))
    path.write_text(after)
    return {"source": str(path), "added_bytes": len(after) - len(before)}


PRIVATE = r'''
    /* NOVA_SYNC_TRACE_V2: per-decoder, observational state only. */
    INT64 nova_trace_start_ms;
    INT64 nova_trace_last_put_ms;
    INT64 nova_trace_last_renderer_ms;
    INT64 nova_trace_last_late_ms;
    int nova_trace_boot_logged;
    int nova_trace_consecutive_late;
    int nova_trace_late_epoch;
    int nova_trace_correction_logs;
'''

PUT_SNAPSHOT = r'''
	/* Capture the pre-publication wall anchor; never alter its calculation. */
	INT64 nova_trace_old_offset = p->render_offset_ns;
	int nova_trace_old_from_audio = p->render_offset_from_audio;
	if (!p->nova_trace_start_ms)
		p->nova_trace_start_ms = atime64();
'''

PUT_LOG = r'''
    /* First 180 seconds, 1 Hz plus actual clock reanchors. Pinpoint the
     * first audio clock publication that moves the render wall anchor. */
    if (s && p->nova_trace_start_ms > 0 &&
        now_ms - p->nova_trace_start_ms <= 180000 &&
        (p->nova_trace_last_put_ms == 0 ||
         now_ms - p->nova_trace_last_put_ms >= 1000 ||
         (nova_trace_old_offset != p->render_offset_ns &&
          (p->render_offset_ns == -1 ||
           llabs(p->render_offset_ns - nova_trace_old_offset) >= 25000000LL)))) {
        p->nova_trace_last_put_ms = now_ms;
        serprintf("NOVA_SYNC_PUT: wallMs=%lld elapsedMs=%lld epoch=%d putMs=%d audioMs=%d videoMs=%d diffMs=%lld threshMs=%d grace=%d disc=%d hard=%d reanchor=%d speedChanged=%d passthrough=%d oldOffNs=%lld newOffNs=%lld targetOffNs=%lld oldFromAudio=%d fromAudio=%d pending=%d seekPending=%d slew=%d pcmStartupSlew=%d pcmSeekSlew=%d pcmResumeSlew=%d pcmLatencyUs=%d startupCorrectionPending=%d lastDelayMs=%d lastDelayValid=%d speed=%.3f renderGen=%u\n",
            (long long)now_ms, (long long)(now_ms - p->nova_trace_start_ms),
            s->seek_epoch, time, s->audio_time, s->video_time, (long long)diff,
            drift_threshold_ms, in_grace, discontinuity, reanchor_discontinuity,
            allow_reanchor, speed_changed, passthrough_mode,
            (long long)nova_trace_old_offset, (long long)p->render_offset_ns,
            (long long)p->target_offset_ns,
            nova_trace_old_from_audio, p->render_offset_from_audio,
            p->pending_reanchor, p->pending_seek_reanchor, p->slew_active,
            p->pcm_startup_slew, p->pcm_seek_startup_slew, p->pcm_resume_slew,
            pcm_latency_us, s->pcm_startup_correction_pending,
            s->last_good_delay_ms, s->last_good_delay_valid,
            (double)p->video_timeline.speed, p->render_generation);
    }
'''

BOOT_LOG = r'''
            if (f && !p->nova_trace_boot_logged) {
                p->nova_trace_boot_logged = 1;
                if (!p->nova_trace_start_ms)
                    p->nova_trace_start_ms = atime64();
                serprintf("NOVA_SYNC_BOOT: wallMs=%lld epoch=%d firstFrameMs=%d audioMs=%d videoMs=%d putMs=%d offsetNs=%lld\n",
                    (long long)p->nova_trace_start_ms, s ? s->seek_epoch : -1,
                    f->time, s ? s->audio_time : -1,
                    s ? s->video_time : -1, p->venc_put_time,
                    (long long)p->render_offset_ns);
            }
'''

RENDER_CLOCK_LOG = r'''
            /* Observe finalized video deadline inputs, without querying
             * AudioTrack, shifting anchors, or waiting on another mutex. */
            INT64 nova_trace_now_ms = now_ns / NSEC_PER_MSEC;
            if (s && p->nova_trace_start_ms > 0 &&
                (int)atime64() - p->nova_trace_start_ms <= 180000 &&
                (p->nova_trace_last_renderer_ms == 0 ||
                 (int)atime64() - p->nova_trace_last_renderer_ms >= 1000)) {
                p->nova_trace_last_renderer_ms = atime64();
                serprintf("NOVA_SYNC_RENDER_CLOCK: wallMs=%lld epoch=%d frameMs=%d audioMs=%d videoMs=%d putMs=%d putRefMs=%lld nowMonoMs=%lld offsetNs=%lld targetNs=%lld offsetFromAudio=%d pending=%d seekPending=%d slew=%d pcmSlew=%d pcmSeekSlew=%d mode2Active=%d passthrough=%d lastDelayMs=%d lastDelayValid=%d startupCorrectionPending=%d renderSeq=%llu lateStreak=%d\n",
                    (long long)p->nova_trace_last_renderer_ms, s->seek_epoch, f->time,
                    s->audio_time, s->video_time, p->venc_put_time,
                    (long long)p->venc_ref_time, (long long)nova_trace_now_ms,
                    (long long)p->render_offset_ns,
                    (long long)p->target_offset_ns,
                    p->render_offset_from_audio,
                    p->pending_reanchor, p->pending_seek_reanchor,
                    p->slew_active, p->pcm_startup_slew, p->pcm_seek_startup_slew,
                    mode2_dynamic_active, passthrough,
                    s->last_good_delay_ms, s->last_good_delay_valid,
                    s->pcm_startup_correction_pending,
                    (unsigned long long)p->render_submit_seq,
                    p->nova_trace_consecutive_late);
            }
'''

MODE2_TRANSITION = r'''
                if (s) {
                    serprintf("NOVA_SYNC_MODE2_TRANSITION: wallMs=%lld epoch=%d active=%d smooth=%d hardReanchor=%d entryDeltaUs=%lld audioMs=%d videoMs=%d frameMs=%d offsetNs=%lld targetNs=%lld pendingSeek=%d\n",
                        (long long)atime64(), s->seek_epoch,
                        mode2_dynamic_active, smooth_entry, hard_reanchor,
                        (long long)(entry_delta_ns / 1000),
                        s->audio_time, s->video_time, f->time,
                        (long long)p->render_offset_ns,
                        (long long)p->target_offset_ns,
                        p->pending_seek_reanchor);
                }
'''

CAPTURE_RENDER_ANCHORS = r'''
        INT64 nova_trace_offset_ns = p->render_offset_ns;
        INT64 nova_trace_target_ns = p->target_offset_ns;
        int nova_trace_from_audio = p->render_offset_from_audio;
        int nova_trace_pending = p->pending_reanchor;
        int nova_trace_seek_pending = p->pending_seek_reanchor;
        int nova_trace_slew = p->slew_active;
        int nova_trace_pcm_slew = p->pcm_startup_slew;
        int nova_trace_clock_generation = (int)p->render_generation;
'''

LATE_LOG = r'''
                /* The first failed deadline is the crucial causal event.
                 * These are lock-snapshotted anchors; no AudioTrack calls. */
                if (s) {
                    if (p->nova_trace_late_epoch != f->epoch) {
                        p->nova_trace_late_epoch = f->epoch;
                        p->nova_trace_consecutive_late = 0;
                        p->nova_trace_last_late_ms = 0;
                    }
                    ++p->nova_trace_consecutive_late;
                    INT64 trace_wall_ms = atime64();
                    if (p->nova_trace_consecutive_late <= 3 ||
                        p->nova_trace_last_late_ms == 0 ||
                        trace_wall_ms - p->nova_trace_last_late_ms >= 1000) {
                        p->nova_trace_last_late_ms = trace_wall_ms;
                        serprintf("NOVA_SYNC_LATE: wallMs=%lld epoch=%d streak=%d frameMs=%d audioMs=%d videoMs=%d latenessMs=%lld nowNs=%lld deadlineNs=%lld offsetNs=%lld targetNs=%lld fromAudio=%d pending=%d seekPending=%d slew=%d pcmSlew=%d renderGen=%d putMs=%d putRefMs=%lld cadenceUs=%lld lastRenderSeq=%llu\n",
                            (long long)trace_wall_ms, f->epoch, p->nova_trace_consecutive_late,
                            f->time, s->audio_time, s->video_time,
                            (long long)(lateness_ns / NSEC_PER_MSEC),
                            (long long)now_ns, (long long)render_ts_ns,
                            (long long)nova_trace_offset_ns,
                            (long long)nova_trace_target_ns,
                            nova_trace_from_audio, nova_trace_pending,
                            nova_trace_seek_pending, nova_trace_slew,
                            nova_trace_pcm_slew, nova_trace_clock_generation,
                            diag_heard, (long long)diag_ref_ms,
                            (long long)(speed_correction_ns / 1000),
                            (unsigned long long)p->render_submit_seq);
                    }
                }
'''

RECOVER_LOG = r'''
                    if (p->nova_trace_consecutive_late >= 3 && s) {
                        serprintf("NOVA_SYNC_LATE_END: epoch=%d recoveredFrameMs=%d previousStreak=%d renderSeq=%llu\n",
                            f->epoch, f->time, p->nova_trace_consecutive_late,
                            (unsigned long long)p->render_submit_seq);
                    }
                    p->nova_trace_consecutive_late = 0;
'''

SEEK_LOG = r'''
    serprintf("NOVA_SYNC_SEEK_RESET: epoch=%d audioMs=%d videoMs=%d oldOffsetNs=%lld oldTargetNs=%lld oldFromAudio=%d oldPending=%d oldSeekPending=%d oldSlew=%d oldPCMStartupSlew=%d oldPCMSeekSlew=%d lastPutMs=%d lastPutRefMs=%lld renderSeq=%llu\n",
        s->seek_epoch, s->audio_time, s->video_time,
        (long long)p->render_offset_ns, (long long)p->target_offset_ns,
        p->render_offset_from_audio, p->pending_reanchor,
        p->pending_seek_reanchor, p->slew_active, p->pcm_startup_slew,
        p->pcm_seek_startup_slew, p->venc_put_time,
        (long long)p->venc_ref_time,
        (unsigned long long)p->render_submit_seq);
'''

CORRECTION_LOG = r'''
    if (s && p->nova_trace_correction_logs < 48) {
        ++p->nova_trace_correction_logs;
        serprintf("NOVA_SYNC_PCM_CORRECTION: epoch=%d sampleValid=%d sampleNs=%lld heardMs=%d audioMs=%d videoMs=%d pending=%d fromAudio=%d oldOffsetNs=%lld oldTargetNs=%lld speedEpoch=%d correctionEpoch=%d codecSpeed=%.3f\n",
            s->seek_epoch, sample_ns != 0, (long long)sample_ns,
            heard_ts, s->audio_time, s->video_time,
            s->pcm_startup_correction_pending, p->render_offset_from_audio,
            (long long)p->render_offset_ns, (long long)p->target_offset_ns,
            s->audio_speed_diag_epoch, s->pcm_startup_correction_seek_epoch,
            s->video_speed_den ? (double)s->video_speed_num / s->video_speed_den : 0.0);
    }
'''

AUDIO_START_LOG = r'''
                        serprintf("NOVA_SYNC_AUDIO_START: epoch=%d firstAudioPts=%d videoMs=%d anchorDelayMs=%d staticLatencyMs=%d committedStartMs=%d putTimeMode=%d passthroughMode=%d pcmCorrectionPendingBefore=%d\n",
                            s->seek_epoch, s->audio_start_pts, s->video_time,
                            anchor_delay, static_latency, start_time,
                            s->put_time_mode, passthrough,
                            s->pcm_startup_correction_pending);
'''

PCM_EVIDENCE_LOG = r'''
                serprintf("NOVA_SYNC_PCM_EVIDENCE: epoch=%d seedMs=%d dynamicMs=%d diffMs=%d streak=%d samplesClock=%d passthrough=%d audioMs=%d videoMs=%d\n",
                    s->seek_epoch, s->pcm_startup_seed_delay_ms,
                    delay_status.dynamic_evidence_ms, delta,
                    delay_status.dynamic_evidence_streak, pcm_startup_ledger_clock,
                    passthrough_mode, s->audio_time, s->video_time);
'''


def patch_codec(path):
    edits = [
        ("private trace counters",
         "\tUINT64 render_submit_seq; // render-thread owned; persists across pause/seek/flush\n",
         "\tUINT64 render_submit_seq; // render-thread owned; persists across pause/seek/flush\n" + PRIVATE),
        ("capture audio publisher prior offset",
         "\tpthread_mutex_lock(&p->locked.mtx);\n\tif (!p->s && s)\n",
         "\tpthread_mutex_lock(&p->locked.mtx);\n" + PUT_SNAPSHOT + "\tif (!p->s && s)\n"),
        ("publisher sampler",
         'DBGSI2 serprintf("[[put %8d|%4d|%4lld]]", time, dt, (long long)dr );',
         PUT_LOG + 'DBGSI2 serprintf("[[put %8d|%4d|%4lld]]", time, dt, (long long)dr );'),
        ("mode2 clock transition event",
         "\t\t\t\tint hard_reanchor = mode2_dynamic_active && !smooth_entry;\n",
         "\t\t\t\tint hard_reanchor = mode2_dynamic_active && !smooth_entry;\n" + MODE2_TRANSITION),
        ("video first-frame marker",
         "\t\t\tf = frame_q_peek(&p->locked.venc_q);\n",
         "\t\t\tf = frame_q_peek(&p->locked.venc_q);\n" + BOOT_LOG),
        ("renderer clock once-per-second timeline",
         "\t\t\tINT64 av_delay_ns = (INT64)(int)(p->effective_av_delay_ms * p->video_timeline.inv_speed) * 1000000LL;\n",
         RENDER_CLOCK_LOG + "\t\t\tINT64 av_delay_ns = (INT64)(int)(p->effective_av_delay_ms * p->video_timeline.inv_speed) * 1000000LL;\n"),
        ("capture anchors before renderer drops private lock",
         "\t\tINT64 diag_ref_ms = p->venc_ref_time;\n",
         "\t\tINT64 diag_ref_ms = p->venc_ref_time;\n" + CAPTURE_RENDER_ANCHORS),
        ("first late frame and sustained late deadline",
         '\t\t\t\tDBGSI serprintf("android_sync: late frame drop f_time=%d lateness=%lldms dropped=%d\\n",\n',
         LATE_LOG + '\t\t\t\tDBGSI serprintf("android_sync: late frame drop f_time=%d lateness=%lldms dropped=%d\\n",\n'),
        ("late episode recovery",
         "\t\t\t\tif (presented) {\n\t\t\t\t\t// Count successful submissions independently of logging.",
         "\t\t\t\tif (presented) {\n" + RECOVER_LOG +
         "\t\t\t\t\t// Count successful submissions independently of logging."),
        ("record exact manual seek reset",
         "\tp->render_generation++;\n\tp->at_clock_active = 0;\n\tp->at_clock_handoff_pending = 0;\n",
         SEEK_LOG + "\tp->render_generation++;\n\tp->at_clock_active = 0;\n\tp->at_clock_handoff_pending = 0;\n"),
        ("log PCM correction attempt before guard",
         "\tpthread_mutex_lock(&p->locked.mtx);\n\tif( sample_ns ) {\n",
         "\tpthread_mutex_lock(&p->locked.mtx);\n" + CORRECTION_LOG + "\tif( sample_ns ) {\n"),
    ]
    return change(path, edits)


def patch_audio(path):
    anchor = "\t\t\t\t\t\t_set_audio_time( s, start_time );\n"
    return change(path, [("audio startup anchor commit", anchor, AUDIO_START_LOG + anchor)])


def patch_sync(path):
    anchor = "\t\t\t\tpcm_startup_request_correction = 1;\n"
    return change(path, [("trusted PCM evidence triggers correction",
                          anchor, anchor + PCM_EVIDENCE_LOG)])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    root = args.native
    targets = [
        root / "Source/codec_sfdec2.c",
        root / "Source/stream_audio.c",
        root / "Source/stream_sync.c",
    ]
    for target in targets:
        if not target.exists():
            raise SystemExit("missing pinned AVOS native source: " + str(target))
    changed = [patch_codec(targets[0]), patch_audio(targets[1]), patch_sync(targets[2])]
    result = {
        "version": "NOVA_SYNC_TRACE_V2",
        "mode": "observational only",
        "startup_trace_ms": 180000,
        "put_interval_ms": 1000,
        "render_interval_ms": 1000,
        "late_episode_interval_ms": 1000,
        "events": ["NOVA_SYNC_BOOT", "NOVA_SYNC_PUT", "NOVA_SYNC_RENDER_CLOCK",
                   "NOVA_SYNC_LATE", "NOVA_SYNC_LATE_END", "NOVA_SYNC_SEEK_RESET",
                   "NOVA_SYNC_PCM_CORRECTION", "NOVA_SYNC_PCM_EVIDENCE", "NOVA_SYNC_MODE2_TRANSITION",
                   "NOVA_SYNC_AUDIO_START"],
        "raw128_logic_changed": False,
        "video_drop_threshold_changed": False,
        "clock_algorithm_changed": False,
        "codec_control_flow_changed": False,
        "modified_source_files": changed,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n")
    print("NOVA_SYNC_TRACE_V2=PATCHED", json.dumps(result))


if __name__ == "__main__":
    main()
