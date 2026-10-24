#!/usr/bin/env python3
"""Restore ownership of sfdec2 frame wrappers after no-output MediaCodec poll.

RUN662 and RUN664 prove a repeated-Seek starvation: parser and engine stay
RUNNING, cNow/cNext contain packets, but sfdec2 has no wrapper available to
feed input (engine decQ=0) and no rendered frames. Merely increasing wrapper
count from 2 to 4 delays the failure by one more seek.

In videodec_thread an sfdec_read() returning without an output buffer places
the empty wrapper back onto the *decoder-internal* dec_q. That monopolizes
all wrappers while MediaCodec waits for more input from the same starved engine.
Return the wrapper to get_q instead, so videosink_get() can hand it back to
the engine. No change to full/valid output flow or FLUSHING ownership.
Preserve sfdec2 wrapper count=2, buffer sizes, audio/video sync, 2X/5X and
subtitle history policies.
"""
import argparse
from pathlib import Path

FIND = '''\t\tif (!sfbuf || has_state_l(p, THREAD_STATE_FLUSHING)) {
\t\t\tif( sfbuf ) {
\t\t\t\tsfdec_buf_discard(p->sfdec, sfbuf);
\t\t\t}
\t\t\tframe_q_put_head(&p->locked.dec_q, f);
\t\t\tcontinue;
\t\t}
'''

NEW = '''\t\tif (!sfbuf || has_state_l(p, THREAD_STATE_FLUSHING)) {
\t\t\tif( sfbuf ) {
\t\t\t\tsfdec_buf_discard(p->sfdec, sfbuf);
\t\t\t}
\t\t\tif (!sfbuf && !has_state_l(p, THREAD_STATE_FLUSHING) &&
\t\t\t    p->locked.run && !p->locked.error) {
\t\t\t\t/* NOVA_SFDEC2_NO_OUTPUT_RETURN_V1: A non-output read
\t\t\t\t * holds NO MediaCodec output buffer. The container belongs
\t\t\t\t * back to the engine, not on dec_q. Keeping it here can
\t\t\t\t * exhaust the entire two-frame pool after rapid seeks:
\t\t\t\t * decoder waits for output -> engine has no container
\t\t\t\t * to send new input -> decoder can never produce output.
\t\t\t\t * Return it via the existing sink get queue. */
\t\t\t\tframe_q_put(&p->locked.get_q, f);
\t\t\t\tpthread_cond_broadcast(&p->locked.cond);
\t\t\t} else {
\t\t\t\t/* While flushing retain original decoder queue ownership.
\t\t\t\t * flush() waits for THREAD_STATE_READING to clear. */
\t\t\t\tframe_q_put_head(&p->locked.dec_q, f);
\t\t\t}
\t\t\tcontinue;
\t\t}
'''

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--native',type=Path,required=True)
    a=p.parse_args()
    file=a.native/'Source/codec_sfdec2.c'
    text=file.read_text()
    assert text.count(FIND)==1, 'No-output return anchor must be unique'
    assert text.count('static int sfdec_max_frames = 2;')==1, 'Wrapper count must remain original two'
    assert 'NOVA_SFDEC2_NO_OUTPUT_RETURN_V1' not in text
    text=text.replace(FIND,NEW,1)
    # Track synthetic empty-wrapper returns. The normal engine sink counter
    # is decremented for rendered frames; a no-output return did NOT pass
    # through videosink_put and must not decrement that counter.
    from_='''\tint num_frames;
\tint reorder_pts;'''
    into='''\tint num_frames;
\tuint32_t nova_no_output_return_mask; /* V1 ownership bookkeeping */
\tint reorder_pts;'''
    assert text.count(from_)==1
    text=text.replace(from_,into,1)
    from_='''\t\t\t\tframe_q_put(&p->locked.get_q, f);
\t\t\t\tpthread_cond_broadcast(&p->locked.cond);'''
    into='''\t\t\t\tif (f->index >= 0 && f->index < 32)
\t\t\t\t\tp->nova_no_output_return_mask |= 1U << f->index;
\t\t\t\tframe_q_put(&p->locked.get_q, f);
\t\t\t\tpthread_cond_broadcast(&p->locked.cond);'''
    assert text.count(from_)==1
    text=text.replace(from_,into,1)
    hook='''static int videodec_flush(STREAM_DEC_VIDEO *dec)'''
    helper='''/* NOVA_SFDEC2_NO_OUTPUT_LEASE_V1: the normal _queue_sink_frames()
 * decrements sinkOutstanding for a *rendered* frame. These no-output
 * wrappers went from dec_q directly to get_q, never through sink.put,
 * so claim them explicitly to avoid making sinkOutstanding negative. */
int nova_sfdec2_claim_no_output_return(STREAM *s, VIDEO_FRAME *f)
{
    if (!s || !s->video_dec || !s->video_dec->name ||
        strcmp(s->video_dec->name, "sfdec2") || !s->video_dec->priv ||
        !f || f->index < 0 || f->index >= 32)
        return 0;
    priv_t *p=(priv_t*)s->video_dec->priv;
    pthread_mutex_lock(&p->locked.mtx);
    unsigned mask=1U << f->index;
    int claimed = !!(p->nova_no_output_return_mask & mask);
    p->nova_no_output_return_mask &= ~mask;
    pthread_mutex_unlock(&p->locked.mtx);
    return claimed;
}

'''
    assert text.count(hook)==1
    text=text.replace(hook,helper+hook,1)
    assert text.count('frame_q_put(&p->locked.get_q, f);')>=2
    assert text.count('NOVA_SFDEC2_NO_OUTPUT_RETURN_V1')==1
    file.write_text(text)
    engine=a.native/'Source/stream_video.c'
    text=engine.read_text()
    before='''\t\ts->video_sink_count--;'''
    after='''\t\t/* Do not debit the displayed-frame count for a codec no-output
\t\t * wrapper returned to the engine without ever entering the sink. */
\t\textern int nova_sfdec2_claim_no_output_return(STREAM *, VIDEO_FRAME *);
\t\tif (!nova_sfdec2_claim_no_output_return(s, frame))
\t\t\ts->video_sink_count--;'''
    assert text.count(before)>=1
    # Precisely modify _queue_sink_frames(), NOT any other counter use.
    begin=text.index('static void _queue_sink_frames( STREAM *s )\n{')
    end=text.index('static void _free_all_frames( STREAM *s )', begin)
    region=text[begin:end]
    assert region.count(before)==1
    text=text[:begin]+region.replace(before,after,1)+text[end:]
    engine.write_text(text)
    print('NOVA_SFDEC2_NO_OUTPUT_RETURN_V1=PATCHED wrapper_count=2 sink_accounting=SAFE')

if __name__=='__main__':main()
