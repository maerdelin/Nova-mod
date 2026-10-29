#!/usr/bin/env python3
"""NOVA 939 Seek forensic checkpoints and bounded async-engine quiescence.

Preserve the established parser/decoder/transport seek path. Record both sides
of each synchronous pause and a separate 1Hz watchdog. For user-initiated
seeks only, don't allow engine-IDLE acknowledgement to block indefinitely.
"""
import argparse
from pathlib import Path

def once(s, old, new, label):
    n=s.count(old)
    if n!=1:
        raise RuntimeError(f"{label}: expected one anchor, got {n}")
    return s.replace(old,new,1)

FIELDS="""    /* NOVA_SEEK_FORENSICS_V2: lock-free heartbeat inspection. */
    int nova_seek_diag_phase;
    int nova_seek_diag_phase_wall;
    int nova_seek_diag_seq;
    int nova_seek_diag_target;
    int nova_seek_diag_timeout_count;
"""

HELPER=r'''
/* Only atomic telemetry. Never take an engine/transport/audio mutex here. */
static void nova_seek_diag_v2(STREAM *s, int phase)
{
    int wall=atime();
    __atomic_store_n(&s->nova_seek_diag_phase_wall,wall,__ATOMIC_RELAXED);
    __atomic_store_n(&s->nova_seek_diag_phase,phase,__ATOMIC_RELEASE);
    serprintf("NOVA_SEEK_STAGE_V2: seq=%d phase=%d wallMs=%d target=%d epoch=%d seek=%d seekPause=%d parser=%d/%d audio=%d/%d engine=%d/%d videoState=%d parserBusy=%d readBusy=%d\n",
        __atomic_load_n(&s->nova_seek_diag_seq,__ATOMIC_RELAXED),
        phase,wall,__atomic_load_n(&s->nova_seek_diag_target,__ATOMIC_RELAXED),
        s->seek_epoch,s->seek,s->seek_paused,
        thread_state_get(&s->parser_tstate),thread_state_asked(&s->parser_tstate),
        thread_state_get(&s->audio_tstate),thread_state_asked(&s->audio_tstate),
        thread_state_get(&s->engine_tstate),thread_state_asked(&s->engine_tstate),
        s->video_state,
        __atomic_load_n(&s->nova_final_parse_busy,__ATOMIC_RELAXED),
        __atomic_load_n(&s->nova_final_read_busy,__ATOMIC_RELAXED));
}
'''

WATCH=r'''
    if(s->seek_paused){
        int ph=__atomic_load_n(&s->nova_seek_diag_phase,__ATOMIC_ACQUIRE);
        int then=__atomic_load_n(&s->nova_seek_diag_phase_wall,__ATOMIC_RELAXED);
        int age=then && now>=then?now-then:-1;
        serprintf("NOVA_SEEK_WATCH_V2: seq=%d phase=%d phaseAgeMs=%d epoch=%d paused=%d seek=%d seekPause=%d parserAck=%d parserWanted=%d audioAck=%d audioWanted=%d engineAck=%d engineWanted=%d videoState=%d engineLoops=%d rawUsed=%d rawCap=%d parserBusy=%d readBusy=%d readCalls=%d\n",
            __atomic_load_n(&s->nova_seek_diag_seq,__ATOMIC_RELAXED),
            ph,age,s->seek_epoch,s->paused,s->seek,s->seek_paused,
            thread_state_get(&s->parser_tstate),thread_state_asked(&s->parser_tstate),
            thread_state_get(&s->audio_tstate),thread_state_asked(&s->audio_tstate),
            thread_state_get(&s->engine_tstate),thread_state_asked(&s->engine_tstate),
            s->video_state,
            __atomic_load_n(&s->nova_seek_engine_loops,__ATOMIC_RELAXED),
            raw_used,raw_capacity,
            __atomic_load_n(&s->nova_final_parse_busy,__ATOMIC_RELAXED),
            __atomic_load_n(&s->nova_final_read_busy,__ATOMIC_RELAXED),
            __atomic_load_n(&s->nova_final_read_calls,__ATOMIC_RELAXED));
    }
'''

def patch(root):
    hp=root/"Include/stream.h"
    h=hp.read_text()
    h=once(h,"    int nova_final_parser_reason;\n",
        "    int nova_final_parser_reason;\n"+FIELDS,"stream observer fields")
    vp=root/"Source/stream_video.c"
    v=vp.read_text()
    if "NOVA_SEEK_STAGE_V2" in v:
        raise RuntimeError("forensics already installed")
    anchor="static int _seek_pause( STREAM *s )\n"
    v=once(v,anchor,HELPER+"\n"+anchor,"diagnostic helper")
    v=once(v,"\ts->parser_interrupt = 1;\n\tthread_state_set( &s->parser_tstate,  THREAD_IDLE );\n\ts->parser_interrupt = 0;\n\tif( s->audio->valid )\n\t\tthread_state_set( &s->audio_tstate,  THREAD_IDLE );\n\n\treturn stream_pause( s );",
        """\ts->parser_interrupt = 1;
\tnova_seek_diag_v2(s,11); /* parser idle request */
\tthread_state_set( &s->parser_tstate,  THREAD_IDLE );
\tnova_seek_diag_v2(s,12); /* parser acknowledged */
\ts->parser_interrupt = 0;
\tif( s->audio->valid ){
\t\tnova_seek_diag_v2(s,13); /* audio idle request */
\t\tthread_state_set( &s->audio_tstate,  THREAD_IDLE );
\t\tnova_seek_diag_v2(s,14); /* audio acknowledged */
\t}
\tnova_seek_diag_v2(s,15); /* stream_pause() entry */
\tint was_paused=stream_pause( s );
\tnova_seek_diag_v2(s,16); /* stream_pause() returned */
\treturn was_paused;""","pause-stage checkpoints")
    start="static int _stream_seek_real( STREAM *s, int time, int pos, int dir, int flags, int force_reload )"
    stop="\nstatic int _stream_seek_abortable( STREAM *s, int time, int pos, int dir, int flags, int force_reload )"
    if v.count(start)!=1 or v.count(stop)!=1:
        raise RuntimeError("seek function delimiters")
    before,tail=v.split(start,1)
    region,after=tail.split(stop,1)
    region=once(region,"\t// pause the stream\n\twas_paused = _seek_pause( s );",
        """\t/* Begin before any blocking pause transaction. */
\t__atomic_add_fetch(&s->nova_seek_diag_seq,1,__ATOMIC_RELAXED);
\t__atomic_store_n(&s->nova_seek_diag_target,
\t    time>=0?time:pos,__ATOMIC_RELAXED);
\tnova_seek_diag_v2(s,10);
\twas_paused = _seek_pause( s );
\tnova_seek_diag_v2(s,17);""","seek enters pause")
    region=once(region,"\tif( _stream_wait_for_idle( s, 1000 ) ) {",
       "\tnova_seek_diag_v2(s,18); /* decoder safe-point wait */\n\tif( _stream_wait_for_idle( s, 1000 ) ) {","decoder wait")
    # Preserve the original engine-gate condition. Match the one C statement,
    # not its neighboring blank lines (later native patches can insert code).
    region=once(region,
        "\tint engine_state = idle_engine ? thread_state_set( &s->engine_tstate, THREAD_IDLE ) : THREAD_RUNNING;",
        """\tint engine_state = THREAD_RUNNING;
\tif(idle_engine){
\t\tnova_seek_diag_v2(s,20); /* engine idle request */
\t\tif(!first_start){
\t\t\t/* Only the async-engine IDLE acknowledgement is bounded:
\t\t\t * the upstream helper restores the old request on timeout.
\t\t\t * No parser seek or queue reset happens after failed ownership. */
\t\t\tif(thread_state_try_idle(&s->engine_tstate,2000,&engine_state)){
\t\t\t\t__atomic_add_fetch(&s->nova_seek_diag_timeout_count,1,__ATOMIC_RELAXED);
\t\t\t\tserprintf("NOVA_SEEK_ENGINE_IDLE_TIMEOUT_V2: seq=%d epoch=%d engineAck=%d engineWanted=%d videoState=%d\\n",
\t\t\t\t    s->nova_seek_diag_seq,s->seek_epoch,
\t\t\t\t    thread_state_get(&s->engine_tstate),
\t\t\t\t    thread_state_asked(&s->engine_tstate),s->video_state);
\t\t\t\tnova_seek_diag_v2(s,91);
\t\t\t\t_seek_un_pause(s,was_paused);
\t\t\t\tnova_seek_diag_v2(s,92);
\t\t\t\treturn 1;
\t\t\t}
\t\t}else engine_state=thread_state_set(&s->engine_tstate,THREAD_IDLE);
\t\tnova_seek_diag_v2(s,21); /* engine acknowledged */
\t}""","bounded engine gate")
    region=once(region,
        "\t_seek_init( s );",
        "\tnova_seek_diag_v2(s,22); /* _seek_init entry */\n"
        "\t_seek_init( s );\n"
        "\tnova_seek_diag_v2(s,23); /* _seek_init returned */",
        "seek init entry/exit")
    region=once(region,
        "\tif( time != -1 ) {\n\t\tchar hms_buf[32];",
        "\tnova_seek_diag_v2(s,24); /* parser seek entry */\n\tif( time != -1 ) {\n\t\tchar hms_buf[32];",
        "parser seek entry")
    region=once(region,
        "DBGS serprintf(\"\\nparser seeked to time %d\\n\", sc.time );",
        "nova_seek_diag_v2(s,25); /* parser seek returned */\nDBGS serprintf(\"\\nparser seeked to time %d\\n\", sc.time );",
        "parser seek return")
    # The early-error path also unpauses. Instrument the *final* matching
    # unpause call only; retain every failure cleanup path unchanged.
    final_call = "\t_seek_un_pause( s, was_paused );"
    tail_pos = region.rfind(final_call)
    if tail_pos < 0 or "return err;" not in region[tail_pos:tail_pos+120]:
        raise RuntimeError("final seek return anchor not found")
    region = (region[:tail_pos]
              + "\tnova_seek_diag_v2(s,29); /* return to playback */\n"
              + final_call
              + "\n\tnova_seek_diag_v2(s,30); /* completed */"
              + region[tail_pos+len(final_call):])
    v=before+start+region+stop+after
    v=once(v,'    serprintf("NOVA_FINAL_HEARTBEAT: wallMs=%d',
           WATCH+'    serprintf("NOVA_FINAL_HEARTBEAT: wallMs=%d',
           "independent seek watchdog")
    hp.write_text(h)
    vp.write_text(v)
    return {"header":str(hp),"video":str(vp)}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--native",required=True,type=Path)
    args=ap.parse_args()
    result=patch(args.native)
    print("NOVA_SEEK_FORENSICS_V2=PATCHED",result)

if __name__=="__main__":
    main()
