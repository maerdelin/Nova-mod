#!/usr/bin/env python3
"""Observational sfdec2 frame-owner accounting for repeated Seek starvation.

Invoked at 1Hz from existing independent heartbeat thread. Uses trylock,
never blocks the decoder or renderer and never mutates ownership/queues.
"""
import argparse
from pathlib import Path

def one(src,old,new,label):
    n=src.count(old)
    if n!=1: raise RuntimeError(label+': expected once, got '+str(n))
    return src.replace(old,new,1)

DUMP=r'''
/* NOVA_SEEK_POOL_OWNERS_V1: renderer/decoder packet-frame ownership snapshot.
 * Keep sample observation-only. Skip while renderer holds its own lock. */
void nova_sfdec2_pool_owners_report(STREAM *s)
{
    if (!s || !s->video_dec || !s->video_dec->name ||
        strcmp(s->video_dec->name, "sfdec2") || !s->video_dec->priv)
        return;
    priv_t *p=(priv_t*)s->video_dec->priv;
    if (pthread_mutex_trylock(&p->locked.mtx)) {
        serprintf("NOVA_SEEK_POOL_OWNERS_V1: busy=1 epoch=%d\n", s->seek_epoch);
        return;
    }
    serprintf("NOVA_SEEK_POOL_OWNERS_V1: epoch=%d frames=%d engineFrames=%d sinkOutstanding=%d pGet=%d pDec=%d pOut=%d pVenc=%d pState=%d pRun=%d pError=%d inputEOS=%d outputEOS=%d renderGen=%u engineDec=%d engineDisp=%d engineCodec=%d engineLocked=%d engineHasFrame=%d currentFrame=%d currentOutFrame=%d audioReconfig=%d audioReaders=%d\n",
      s->seek_epoch, p->num_frames, s->num_frames, s->video_sink_count,
      frame_q_count(&p->locked.get_q), frame_q_count(&p->locked.dec_q),
      frame_q_count(&p->locked.out_q), frame_q_count(&p->locked.venc_q),
      p->locked.state,p->locked.run,p->locked.error,p->input_eos,
      p->output_eos,p->render_generation,
      frame_q_count(&s->decode_q),frame_q_count(&s->disp_q),
      frame_q_count(&s->codec_q),frame_q_count(&s->locked_q),
      !!s->decode_frame,!!s->current_frame,!!s->current_out_frame,
      s->audio_reconfiguring,s->audio_readers);
    pthread_mutex_unlock(&p->locked.mtx);
}

'''

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--native',required=True,type=Path)
    a=ap.parse_args()
    codec=a.native/'Source/codec_sfdec2.c'
    s=codec.read_text()
    marker="static int videodec_flush(STREAM_DEC_VIDEO *dec)"
    s=one(s,marker,DUMP+marker,"insert decoder snapshot")
    assert s.count('serprintf("NOVA_SEEK_POOL_OWNERS_V1: epoch=')==1
    codec.write_text(s)
    engine=a.native/'Source/stream_video.c'
    s=engine.read_text()
    marker='    serprintf("NOVA_SEEK_ENGINE_DIAG_V1:'
    s=one(s,marker,
       '    extern void nova_sfdec2_pool_owners_report(STREAM *s);\n'
       '    nova_sfdec2_pool_owners_report(s);\n'+marker,
       "invoke decoder snapshot")
    assert s.count('nova_sfdec2_pool_owners_report(s);')==1
    engine.write_text(s)
    print('NOVA_SEEK_POOL_OWNERS_V1=INSTRUMENTED')
if __name__=='__main__':main()
