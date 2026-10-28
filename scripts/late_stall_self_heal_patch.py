#!/usr/bin/env python3
"""Restore a genuinely stalled video renderer without changing normal timing.

The observed RUN649 failure had >1,600 consecutive frames rejected solely for
being >200ms late, despite a full video queue and active audio/decode. Repair
only AFTER 12 consecutive late drops (~200ms at 60fps), while video/audio PTS
are near each other and the player is at stable speed 1.0, not seeking/paused.
The next frame is then scheduled using an updated audio-relative offset.
All successful rendering, startup, speed changes and seek handling unchanged.
"""
import argparse
import json
from pathlib import Path

TAG="NOVA_LATE_STALL_SELF_HEAL_V1"

def rep(s,old,new,what):
    count=s.count(old)
    if count!=1: raise RuntimeError("%s: expected one anchor, got %d"%(what,count))
    return s.replace(old,new,1)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--native",type=Path,required=True)
    ap.add_argument("--report",type=Path)
    a=ap.parse_args()
    f=a.native/"Source/codec_sfdec2.c"
    original=f.read_text(encoding="utf-8")
    assert TAG not in original
    assert original.count("const INT64 k_late_drop_threshold_ns = 200 * 1000000LL;")==1

    # Count rejected frames on the already-established do_render branch.
    # Reanchor while the existing renderer mutex is held, after releasing
    # the old decoder buffer and before scheduling the NEXT frame.
    s=rep(original,
        "\t\tint presented = 0;\n",
        "\t\tint presented = 0;\n"
        "\t\tINT64 nova_late_stall_ns = 0;\n",
        "drop sample local")
    s=rep(s,
        "\t\t\t} else if (lateness_ns > k_late_drop_threshold_ns) {\n",
        "\t\t\t} else if (lateness_ns > k_late_drop_threshold_ns) {\n"
        "\t\t\t\tnova_late_stall_ns = lateness_ns;\n",
        "record late timing")

    anchor="\t\tpthread_mutex_lock(&p->locked.mtx);\n\t\tif (render_error) {\n"
    code=r'''        /* NOVA_LATE_STALL_SELF_HEAL_V1: protect against an infinite
         * feedback loop where the 200ms late-drop rule permanently rejects
         * every decoded frame, while audio and the video stream continue.
         *
         * Do not recover from real missing input, an audio/video discontinuity,
         * a seek, paused video, trickplay, or a normal isolated late frame.
         * This runs on the single renderer thread with its mutex held.
         */
        if (nova_late_stall_ns > 0 && p->dropped >= 12 && s &&
            f->epoch == s->seek_epoch &&
            !s->seek && !s->seek_paused && !s->paused &&
            !s->paused_internal && !s->video_hold_for_resume_audio &&
            s->audio_time >= 0 && s->video_time >= 0 &&
            llabs((INT64)f->time - (INT64)s->audio_time) < 500 &&
            p->video_timeline.speed > 0.999 &&
            p->video_timeline.speed < 1.001 &&
            p->render_offset_ns != -1 &&
            p->render_offset_from_audio &&
            !p->pending_seek_reanchor &&
            !p->pending_reanchor &&
            !has_state_l(p, THREAD_STATE_FLUSHING) &&
            nova_late_stall_ns < 2000000000LL) {
            /* Shift only the renderer's clock back into the display window.
             * Keep PTS continuity: no demux seek, decoder flush, or audio
             * restart. +30ms ensures the next decoded frame is renderable. */
            INT64 correction = nova_late_stall_ns + 30000000LL;
            p->render_offset_ns += correction;
            p->target_offset_ns = p->render_offset_ns;
            p->slew_active = 0;
            speed_cadence_reset(&p->speed_cadence);
            serprintf("NOVA_LATE_STALL_SELF_HEAL_V1: recoveryNs=%lld frameMs=%d audioMs=%d oldStreak=%d epoch=%d\n",
                      (long long)correction, f->time, s->audio_time,
                      p->dropped, f->epoch);
            p->dropped = 0;
        }
'''
    s=rep(s,anchor,"\t\tpthread_mutex_lock(&p->locked.mtx);\n"+code+"\t\tif (render_error) {\n","post-drop recovery")
    assert s.count(TAG)==2
    assert s.count("const INT64 k_late_drop_threshold_ns = 200 * 1000000LL;")==1
    f.write_text(s,encoding="utf-8")
    report={
        "tag":TAG,
        "scope":"persistent late-drop video freeze only",
        "trigger":"12+ consecutive >200ms late frames, stable 1x, valid current epoch and near-sync audio PTS",
        "method":"renderer-only offset correction, no seek/flush/audio restart",
        "normal_200ms_late_drop":"unchanged",
        "audio_video_demux":"unchanged",
        "subtitle_history":"handled by separate strict full-disable patch",
        "source":str(f)
    }
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(TAG+"=PATCHED")
if __name__=="__main__":
    main()
