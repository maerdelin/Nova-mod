#!/usr/bin/env python3
"""Frame-accurate completion for established direct non-ISO sfdec2 seeks.

Use the existing parser, decoder, frame queues and async command worker. Decode
from the indexed keyframe, but finish only after the first target frame is
accepted by the renderer and its scheduled presentation time has arrived.
"""
import argparse
import json
from pathlib import Path


def once(src, before, after, label):
    n = src.count(before)
    if n != 1:
        raise RuntimeError(f"{label}: expected one anchor, got {n}")
    return src.replace(before, after, 1)


FIELDS = '''
    /* NOVA_PRECISE_SEEK_V1: worker -> renderer -> worker handoff. */
    int nova_precise_state; /* 0 off, 1 preroll, 2 submitted, 3 done, 4 cancel,
                              5 timeout, 6 timestamp gap, 7 stream error */
    int nova_precise_epoch;
    int nova_precise_target_ts;
    int nova_precise_target_rst;
    int nova_precise_presented_ts;
    unsigned nova_precise_due_ms; /* monotonic modulo 2^32, <=30s interval */
'''

HELPERS = r'''
/* NOVA_PRECISE_SEEK_V1: no playback queue, transport, or clock replacement. */
static int nova_precise_scope(STREAM *s, int time)
{
    if (!s || time <= 0 || s->no_duration || !s->video || !s->video->valid ||
        !s->video_dec || !s->video_dec->async || !s->video_dec->name ||
        strcmp(s->video_dec->name,"sfdec2") || s->seek_use_target_sync ||
        strncmp(s->src.url,"novatransport://",16)) return 0;
    const char *path=strstr(s->src.url,"/stream");
    return path && (path[7]==0 || path[7]=='?');
}

static unsigned nova_precise_clock_ms(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC,&t);
    return (unsigned)((uint64_t)t.tv_sec*1000ULL+t.tv_nsec/1000000ULL);
}

static int nova_precise_tolerance(STREAM *s)
{
    int ms=s->video && s->video->msPerFrame>0 ? s->video->msPerFrame+2 : 50;
    return RST_TO_TS_DELTA(ms,int);
}

static void nova_precise_begin(STREAM *s,int rst,int ts)
{
    __atomic_store_n(&s->nova_precise_epoch,s->seek_epoch,__ATOMIC_RELAXED);
    __atomic_store_n(&s->nova_precise_target_rst,rst,__ATOMIC_RELAXED);
    __atomic_store_n(&s->nova_precise_target_ts,ts,__ATOMIC_RELAXED);
    __atomic_store_n(&s->nova_precise_presented_ts,-1,__ATOMIC_RELAXED);
    __atomic_store_n(&s->nova_precise_due_ms,0,__ATOMIC_RELAXED);
    __atomic_store_n(&s->nova_precise_state,1,__ATOMIC_RELEASE);
    serprintf("NOVA_PRECISE_SEEK_BEGIN_V1: epoch=%d targetMs=%d targetTs=%d toleranceTs=%d\n",
              s->seek_epoch,rst,ts,nova_precise_tolerance(s));
}

/* Protect the one-frame preview and the async renderer. The actual engine
 * timestamps must remain truthful while decoding/discarding preroll. */
int nova_precise_seek_admit(STREAM *s,int pts,int epoch)
{
    if (!s) return 1;
    int state=__atomic_load_n(&s->nova_precise_state,__ATOMIC_ACQUIRE);
    if (state!=1 && state!=2) return 1;
    if (epoch!=__atomic_load_n(&s->nova_precise_epoch,__ATOMIC_ACQUIRE) ||
        epoch!=s->seek_epoch ||
        __atomic_load_n(&s->seek_preview_superseded,__ATOMIC_ACQUIRE)) return 0;
    int target=__atomic_load_n(&s->nova_precise_target_ts,__ATOMIC_RELAXED);
    if (pts<target) return 0;
    if ((int64_t)pts-target>nova_precise_tolerance(s)) {
        int pending=1;
        if (__atomic_compare_exchange_n(&s->nova_precise_state,&pending,6,0,
                                        __ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))
            serprintf("NOVA_PRECISE_SEEK_GAP_V1: epoch=%d targetTs=%d actualTs=%d\n",
                      epoch,target,pts);
        return 0;
    }
    return 1;
}

void nova_precise_seek_submitted(STREAM *s,int pts,int epoch,INT64 due_ns)
{
    if (!s || !nova_precise_seek_admit(s,pts,epoch) ||
        __atomic_load_n(&s->nova_precise_state,__ATOMIC_ACQUIRE)!=1) return;
    __atomic_store_n(&s->nova_precise_presented_ts,pts,__ATOMIC_RELAXED);
    __atomic_store_n(&s->nova_precise_due_ms,(unsigned)(due_ns/1000000LL),__ATOMIC_RELAXED);
    int pending=1;
    if (__atomic_compare_exchange_n(&s->nova_precise_state,&pending,2,0,
                                    __ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))
        serprintf("NOVA_PRECISE_SEEK_SUBMITTED_V1: epoch=%d targetTs=%d actualTs=%d\n",
                  epoch,s->nova_precise_target_ts,pts);
}

static int nova_precise_wait(STREAM *s,int64_t deadline)
{
    for (;;) {
        if (__atomic_load_n(&s->seek_preview_superseded,__ATOMIC_ACQUIRE) || stream_abort(s)) {
            __atomic_store_n(&s->nova_precise_state,4,__ATOMIC_RELEASE);
            serprintf("NOVA_PRECISE_SEEK_CANCEL_V1: epoch=%d\n",s->seek_epoch);
            return 0;
        }
        if (s->video_error || s->error) {
            __atomic_store_n(&s->nova_precise_state,7,__ATOMIC_RELEASE);
            return 0;
        }
        int state=__atomic_load_n(&s->nova_precise_state,__ATOMIC_ACQUIRE);
        if (state==2) {
            unsigned due=__atomic_load_n(&s->nova_precise_due_ms,__ATOMIC_RELAXED);
            if ((int32_t)(nova_precise_clock_ms()-due)>=0) {
                __atomic_store_n(&s->nova_precise_state,3,__ATOMIC_RELEASE);
                serprintf("NOVA_PRECISE_SEEK_DONE_V1: epoch=%d targetMs=%d targetTs=%d actualTs=%d toleranceTs=%d\n",
                          s->seek_epoch,s->nova_precise_target_rst,s->nova_precise_target_ts,
                          s->nova_precise_presented_ts,nova_precise_tolerance(s));
                return 1;
            }
        }
        if (state>=4) return 0;
        if (atime64()>=deadline) {
            __atomic_store_n(&s->nova_precise_state,5,__ATOMIC_RELEASE);
            serprintf("NOVA_PRECISE_SEEK_TIMEOUT_V1: epoch=%d targetTs=%d\n",
                      s->seek_epoch,s->nova_precise_target_ts);
            return 0;
        }
        stream_yield();
    }
}

static int nova_precise_ui_time(STREAM *s,int real_rst)
{
    int state=__atomic_load_n(&s->nova_precise_state,__ATOMIC_ACQUIRE);
    if (state>=1 && state<=3 && s->seek_epoch==
        __atomic_load_n(&s->nova_precise_epoch,__ATOMIC_ACQUIRE)) {
        int floor=__atomic_load_n(&s->nova_precise_target_rst,__ATOMIC_RELAXED);
        if (real_rst<floor) return floor;
    }
    return real_rst;
}
'''


def header_text(src):
    src=once(src,"\tint \t\tseek_epoch;\n","\tint \t\tseek_epoch;\n"+FIELDS,"precise per-stream state")
    anchor="void\tstream_seek_preview_supersede( STREAM *s );"
    return once(src,anchor,anchor+"\nint nova_precise_seek_admit(STREAM *,int,int);\n"
                "void nova_precise_seek_submitted(STREAM *,int,int,INT64);","precise render hooks")


def engine_text(src):
    if "NOVA_PRECISE_SEEK_V1" in src: raise RuntimeError("precise patch already installed")
    src=once(src,"static void _video_init( STREAM *s, int time )",HELPERS+"\nstatic void _video_init( STREAM *s, int time )","precise helpers")
    # Verified #890/#891: forward parser seeks skip 7.3s target and jump to
    # 8.021s GOP. Exact seeks must decode forward FROM prior keyframe.
    src=once(src,"\tint first_start = (old_time < 0 && s->seek_epoch == 0);",
             "\tint first_start = (old_time < 0 && s->seek_epoch == 0);\n"
             "    int nova_precise_backseek = !first_start && nova_precise_scope(s,time);",
             "exact seek preceding keyframe")
    src=once(src,"s->parser->seek_time( s, time, dir, flags, force_reload, &sc )",
             "s->parser->seek_time( s, nova_precise_backseek ? MAX(0,time-2600) : time, nova_precise_backseek ? STREAM_SEEK_BACKWARD : dir, flags, force_reload, &sc )",
             "exact seek FFmpeg keyframe direction")
    src=once(src,"int final_ts = sc.time;  // Parser returns TS position",
             r'''/* NOVA_PRECISE_SEEK_PREROLL_V2: Some unindexed streams return
                 * a keyframe AFTER the requested timestamp even when seek
                 * direction is BACKWARD. Before opening the decoder, retry
                 * from progressively earlier positions so real preroll can
                 * reach the requested frame. */
                if (nova_precise_backseek && sc.time > RST_TO_TS_TIME(time,int)) {
                    const int backoffs_ms[] = { 5200, 9000, 15000 };
                    for (int attempt=0; attempt<3; ++attempt) {
                        int anchor=MAX(0,time-backoffs_ms[attempt]);
                        serprintf("NOVA_PRECISE_SEEK_BACKTRACK_V2: want=%d anchor=%d previous=%d attempt=%d\n",
                                  time,anchor,sc.time,attempt+1);
                        if (s->parser->seek_time(s,anchor,STREAM_SEEK_BACKWARD,
                                                 flags,force_reload,&sc)) {
                            err=1;
                            break;
                        }
                        if (sc.time<=RST_TO_TS_TIME(time,int)) break;
                    }
                    if (!err && sc.time > RST_TO_TS_TIME(time,int)) {
                        serprintf("NOVA_PRECISE_SEEK_NO_PRIOR_GOP_V2: target=%d achieved=%d\n",
                                  time,sc.time);
                        err=1;
                    }
                }
                int final_ts = sc.time;  // Parser returns TS position''',
             "retry earlier keyframe when parser still overshoots desired time")
    src=once(src,"\t__atomic_store_n( &s->seek_preview_superseded, 0, __ATOMIC_RELEASE );",
             "\t__atomic_store_n(&s->nova_precise_state,0,__ATOMIC_RELEASE);\n"
             "\t__atomic_store_n( &s->seek_preview_superseded, 0, __ATOMIC_RELEASE );","new seek clears old position floor")
    src=once(src,"\tint target_ts = (time >= 0) ? RST_TO_TS_TIME( time, int ) : sc.time;",
             "\tint target_ts = (time >= 0) ? RST_TO_TS_TIME( time, int ) : sc.time;\n"
             "    int nova_exact_seek=nova_precise_backseek;\n"
             "    int64_t nova_exact_deadline=atime64()+30000;\n"
             "    if (nova_exact_seek) nova_precise_begin(s,time,target_ts);","established direct non-ISO scope")
    src=once(src,"    int64_t nova_exact_deadline=atime64()+30000;",
             r'''    int64_t nova_exact_deadline=atime64()+30000;
    int nova_exact_preview_frames=10;
    if (nova_exact_seek) {
        int step=MAX(1,RST_TO_TS_DELTA(MAX(1,s->video->msPerFrame),int));
        int distance=MAX(0,target_ts-sc.time);
        nova_exact_preview_frames=MIN(640,MAX(48,distance/step+48));
        serprintf("NOVA_PRECISE_SEEK_PREROLL_V2: epoch=%d target=%d key=%d frames=%d\n",
                  s->seek_epoch,target_ts,sc.time,nova_exact_preview_frames);
    }''',
             "allow enough decode frames to traverse the pre-target GOP")
    anchor="\t\tif( !s->seek_skip_initial_play ) {\n\t\t\tint preview_shown = _stream_play_n_frames( s, 10, sc.time, old_time );"
    src=once(src,anchor,r'''
        if (nova_exact_seek) {
            /* The command worker stays asynchronous to the UI. A newer seek,
             * BACK/stop or cancellation interrupts the preroll; a deadline
             * never turns an earlier preview into a successful exact seek. */
            sfdec2_reset_sync_state_on_seek(s);
            s->seek_force_video_drop=1;
            __atomic_store_n(&s->seek_preview_refining,1,__ATOMIC_RELEASE);
            _stream_play_n_frames(s,nova_exact_preview_frames,target_ts,0);
            __atomic_store_n(&s->seek_preview_refining,0,__ATOMIC_RELEASE);
            s->seek_force_video_drop=0;
            if (!nova_precise_wait(s,nova_exact_deadline)) {
                int cancelled=__atomic_load_n(&s->nova_precise_state,__ATOMIC_ACQUIRE)==4;
                s->seek_skip_initial_play=0;
                s->seek_frame=0;
                if (!cancelled && !stream_abort(s)) stream_set_error(s,VE_FILE_ERROR);
                if (idle_engine) thread_state_set(&s->engine_tstate,engine_state);
                _seek_un_pause(s,was_paused);
                return cancelled ? 0 : 1;
            }
        } else if( !s->seek_skip_initial_play ) {
			int preview_shown = _stream_play_n_frames( s, 10, sc.time, old_time );''',"preroll and first-render completion")
    src=once(src,"\t\t\ts->seek_video_target_pending = s->seek_video_target_ts > 0;",
             "\t\t\ts->seek_video_target_pending = nova_exact_seek ? 0 : s->seek_video_target_ts > 0;\n"
             "            if (nova_exact_seek) s->seek_video_ready_ts=s->nova_precise_presented_ts;","already rendered target releases audio hold")
    src=once(src,"\tint64_t timeout = atime64() + 1000; // 1 second of preview work",
             "    int nova_exact_preview=__atomic_load_n(&s->nova_precise_state,__ATOMIC_ACQUIRE)==1;\n"
             "\tint64_t timeout = atime64() + (nova_exact_preview ? 30000 : 1000); // bounded cancelable exact preroll","long-GOP precise preview budget")
    src=once(src,"\twhile( s->play_n_video_frames && atime64() < timeout ) {",
             "\twhile( s->play_n_video_frames && atime64() < timeout ) {\n"
             "        if (nova_exact_preview && __atomic_load_n(&s->nova_precise_state,__ATOMIC_ACQUIRE)==2) {\n"
              "            s->play_n_video_frames=0; break;\n"
              "        }\n"
              "        if (nova_exact_preview && (stream_abort(s) || s->video_error || s->error ||\n"
             "            __atomic_load_n(&s->nova_precise_state,__ATOMIC_ACQUIRE)>=4)) break;","abort precise preview promptly")
    src=once(src,"\t\t\t\t\tint accept_partial = below_target && deadline_ms > 0 &&",
             "                    int nova_partial_allowed=__atomic_load_n(&s->nova_precise_state,__ATOMIC_ACQUIRE)!=1;\n"
             "\t\t\t\t\tint accept_partial = nova_partial_allowed && below_target && deadline_ms > 0 &&","never accept partial exact target")
    src=once(src,"\tif( s->seek_video_drop && s->seek_video_target_ts > 0 ) {",
             "    if (!nova_precise_seek_admit(s,frame->time,frame->epoch)) goto Discard;\n"
             "\tif( s->seek_video_drop && s->seek_video_target_ts > 0 ) {","target floor before sink ownership transfer")
    # An empty wrapper did not pass through a display submission. Its old PTS
    # must not overwrite the presentation clock when ownership is returned.
    src=once(src,"\t\tif (!nova_sfdec2_claim_no_output_return(s, frame))\n\t\t\ts->video_sink_count--;",
             "        int nova_empty_return=nova_sfdec2_claim_no_output_return(s,frame);\n"
             "\t\tif (!nova_empty_return)\n\t\t\ts->video_sink_count--;","preserve empty-wrapper ownership and presentation time")
    src=once(src,"\t\tif( s->vtime_post_sink && frame->time != -1 ) {",
             "\t\tif( !nova_empty_return && s->vtime_post_sink && frame->time != -1 ) {","empty wrappers cannot publish time")
    src=once(src,"\treturn time_rst;\n}\n\n// *****************************************************************************\n//\n//\tstream_get_current_time",
             "\treturn nova_precise_ui_time(s,time_rst);\n}\n\n// *****************************************************************************\n//\n//\tstream_get_current_time","public progress floor belongs to this seek only")
    return src


def codec_text(src):
    # Reuse the existing stale-generation discard path. Never release a stale
    # or pre-target output to the display just because it reached the renderer.
    anchor="\t\t\tif( s && f->epoch != s->seek_epoch ) {"
    src=once(src,anchor,"\t\t\tif( s && (f->epoch != s->seek_epoch ||\n"
             "                !nova_precise_seek_admit(s,f->time,f->epoch)) ) {","renderer target and epoch validation")
    anchor="\t\tif (presented) {\n\t\t\tif (mode2_preroll_interval_ns > 0 &&"
    return once(src,anchor,"\t\tif (presented) {\n"
                "            nova_precise_seek_submitted(s,f->time,f->epoch,render_ts_ns);\n"
                "\t\t\tif (mode2_preroll_interval_ns > 0 &&","only successful renderer submission acknowledges exact seek")


def apply(root,report=None):
    paths=[root/"Include/stream.h",root/"Source/stream_video.c",root/"Source/codec_sfdec2.c"]
    outputs=[fn(p.read_text()) for fn,p in zip([header_text,engine_text,codec_text],paths)]
    for p,text in zip(paths,outputs):p.write_text(text)
    result={"status":"PASS","version":"NOVA_PRECISE_SEEK_V1",
            "scope":"established nonzero direct non-ISO sfdec2 time seeks",
            "completion":"first frame at/after target submitted and its due time reached",
            "tolerance":"one source frame plus 2ms; unknown frame rate 50ms",
            "deadline_ms":30000,"supersedable":True,"partial_success":False,
            "raw128_changed":False,"transport_changed":False,"iso_seek_changed":False}
    if report:
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps(result,indent=2)+"\n")
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--native",type=Path,required=True);p.add_argument("--report",type=Path)
    a=p.parse_args();print(json.dumps(apply(a.native,a.report)))
