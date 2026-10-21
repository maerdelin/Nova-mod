#!/usr/bin/env python3
"""Restore natural EOF completion for the sfdec player path only.

This patch is deliberately downstream of transport/readahead. It does not read
RAW occupancy, WebDAV state, bitrate X, rebuffer thresholds or producer state.
The existing AVOS player remains the sole owner of completion:
parser EOF -> decoder EOS -> presentation drained -> _check_end -> s->stop().
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)

def patch_sfdec(text: str) -> str:
    if "NOVA_SFDEC_EOF_DRAIN" in text:
        raise RuntimeError("sfdec EOF completion patch already installed")

    text = once(text,
        "\tint reorder_pts;\n\n\tstruct XDM_ctx XDM_ctx;",
        "\tint reorder_pts;\n\tint input_eos;\n\tint output_eos;\n\tINT64 presentation_end_ms;\n\n\tstruct XDM_ctx XDM_ctx;",
        "sfdec EOF state")

    text = once(text,
        "static int videosink_end(STREAM_SINK_VIDEO *sink)\n{\n\treturn 0;\n}\n\nstatic int videosink_syncable",
        """static int videosink_end(STREAM_SINK_VIDEO *sink)
{
\treturn 0;
}

static int videosink_drained(STREAM_SINK_VIDEO *sink)
{
\tpriv_t *p = (priv_t *)sink->priv;
\tpthread_mutex_lock(&p->locked.mtx);
\tint done = !frame_q_count(&p->locked.venc_q) &&
\t\t!has_state_l(p, THREAD_STATE_RENDERING, THREAD_STATE_RENDERING) &&
\t\tatime64() >= p->presentation_end_ms;
\tpthread_mutex_unlock(&p->locked.mtx);
\treturn done;
}

static int videosink_syncable""",
        "sfdec sink drain callback")

    text = once(text,
        "\tsink->end\t= videosink_end;\n\tsink->syncable",
        "\tsink->end\t= videosink_end;\n\tsink->drained = videosink_drained;\n\tsink->syncable",
        "install sfdec sink drain callback")

    text = once(text,
        "\tclock_gettime(CLOCK_REALTIME, &p->locked.venc_ref_time);\n\tpthread_mutex_unlock(&p->locked.mtx);",
        "\tclock_gettime(CLOCK_REALTIME, &p->locked.venc_ref_time);\n\tp->presentation_end_ms = 0;\n\tpthread_mutex_unlock(&p->locked.mtx);",
        "reset sink presentation deadline")

    text = once(text,
        "\t\tVIDEO_FRAME *f = NULL;\n\t\twhile (p->locked.run && !(f = frame_q_get(&p->locked.venc_q))) {",
        "\t\tVIDEO_FRAME *f = NULL;\n\t\tint presented = 0;\n\t\twhile (p->locked.run && !(f = frame_q_get(&p->locked.venc_q))) {",
        "sfdec render presentation flag")

    text = once(text,
        "\t\t\t\tsfdec_buf_render(p->sfdec, (sfbuf_t *)f->android_handle, 1, 1, 0);",
        "\t\t\t\tpresented = sfdec_buf_render(p->sfdec, (sfbuf_t *)f->android_handle, 1, 1, 0) == 0;",
        "track final rendered frame")

    text = once(text,
        "\t\tpthread_mutex_lock(&p->locked.mtx);\n\t\tif (f)\n\t\t\tframe_q_put(&p->locked.get_q, f);",
        """\t\tpthread_mutex_lock(&p->locked.mtx);
\t\tif (presented && f)
\t\t\tp->presentation_end_ms = MAX(p->presentation_end_ms,
\t\t\t\tatime64() + MAX(f->duration, 0));
\t\tif (f)
\t\t\tframe_q_put(&p->locked.get_q, f);""",
        "publish final presentation deadline")

    text = once(text,
        "\t\twhile (p->locked.run && !p->locked.error &&!(f = frame_q_get(&p->locked.dec_q))) {",
        "\t\twhile (p->locked.run && !p->locked.error &&\n\t\t       (p->output_eos || !(f = frame_q_get(&p->locked.dec_q)))) {",
        "stop sfdec reads after output EOS")

    text = once(text,
        "\t\tif (read_out.flag & SFDEC_READ_SIZE) {\n\t\t\tif (read_out.size.width >= 0 && read_out.size.height >= 0) {\n\t\t\t\tp->locked.width = read_out.size.width;\n\t\t\t\tp->locked.height = read_out.size.height;\n\t\t\t\tp->locked.interlaced = read_out.size.interlaced;\n\t\t\t}\nDBGCV3 CLOG(\"sfdec_read <- size %dx%d (%d)\", read_out.size.width, read_out.size.height, read_out.size.interlaced);\n\t\t}\n\n\t\tif (!sfbuf) {",
        """\t\tif (read_out.flag & SFDEC_READ_SIZE) {
\t\t\tif (read_out.size.width >= 0 && read_out.size.height >= 0) {
\t\t\t\tp->locked.width = read_out.size.width;
\t\t\t\tp->locked.height = read_out.size.height;
\t\t\t\tp->locked.interlaced = read_out.size.interlaced;
\t\t\t}
DBGCV3 CLOG("sfdec_read <- size %dx%d (%d)", read_out.size.width, read_out.size.height, read_out.size.interlaced);
\t\t}
\t\tif (read_out.flag & SFDEC_READ_EOS) {
\t\t\tp->output_eos = 1;
\t\t\tpthread_cond_broadcast(&p->locked.cond);
\t\t}

\t\tif (!sfbuf) {""",
        "consume MediaCodec output EOS")

    text = once(text,
        "\tp->reorder_pts = video->reorder_pts;\n",
        "\tp->reorder_pts = video->reorder_pts;\n\tp->input_eos = 0;\n\tp->output_eos = 0;\n\tp->presentation_end_ms = 0;\n",
        "reset EOS on decoder open")

    drain = """static int videodec_drain(STREAM_DEC_VIDEO *dec, VIDEO_FRAME **in,
\tVIDEO_FRAME **out, int *done)
{
\tpriv_t *p = (priv_t *)dec->priv;
\tpthread_mutex_lock(&p->locked.mtx);
\tif (!p->input_eos && !p->locked.error && p->locked.run) {
\t\tpthread_mutex_unlock(&p->locked.mtx);
\t\tint submit = sfdec_send_eos(p->sfdec);
\t\tpthread_mutex_lock(&p->locked.mtx);
\t\tif (submit < 0)
\t\t\tp->locked.error = 1;
\t\telse if (submit > 0) {
\t\t\tp->input_eos = 1;
\t\t\tserprintf("NOVA_SFDEC_EOF_DRAIN: input_eos=1\\n");
\t\t}
\t}
\tif (done)
\t\t*done = p->output_eos && !frame_q_count(&p->locked.out_q);
\tint error = p->locked.error;
\tpthread_mutex_unlock(&p->locked.mtx);
\treturn error;
}

"""
    text = once(text,
        "static int videodec_seek(STREAM_DEC_VIDEO *dec, int time)\n{",
        drain + "static int videodec_seek(STREAM_DEC_VIDEO *dec, int time)\n{",
        "install sfdec decoder drain callback")

    text = once(text,
        "\tp->locked.seek_watch_restarts = 0;\n\tpthread_mutex_unlock(&p->locked.mtx);",
        "\tp->locked.seek_watch_restarts = 0;\n\tp->input_eos = 0;\n\tp->output_eos = 0;\n\tp->presentation_end_ms = 0;\n\tpthread_cond_broadcast(&p->locked.cond);\n\tpthread_mutex_unlock(&p->locked.mtx);",
        "reset EOS on seek")

    text = once(text,
        "static int videodec_flush(STREAM_DEC_VIDEO *dec)\n{\n\tCLOG();\n\n\treturn 0;\n}",
        """static int videodec_flush(STREAM_DEC_VIDEO *dec)
{
\tpriv_t *p = (priv_t*)dec->priv;
\tCLOG();
\tpthread_mutex_lock(&p->locked.mtx);
\tp->input_eos = 0;
\tp->output_eos = 0;
\tp->presentation_end_ms = 0;
\tpthread_cond_broadcast(&p->locked.cond);
\tpthread_mutex_unlock(&p->locked.mtx);
\treturn 0;
}""",
        "reset EOS on flush")

    text = once(text,
        "\tdec->flush\t= videodec_flush;\n\tdec->get_rc",
        "\tdec->flush\t= videodec_flush;\n\tdec->drain     = videodec_drain;\n\tdec->get_rc",
        "register sfdec decoder drain")
    return text

def patch_stream_video(text: str) -> str:
    if "NOVA_PLAYBACK_COMPLETE" in text:
        raise RuntimeError("player completion trace already installed")
    return once(text,
        """\t\t\t} else {
\t\t\t\tif( s->stop ) {
\t\t\t\t\ts->stop( s );
\t\t\t\t}""",
        """\t\t\t} else {
\t\t\t\tserprintf("NOVA_PLAYBACK_COMPLETE: player_drained video=%d audio=%d\\n", video_end, audio_end);
\t\t\t\tif( s->stop ) {
\t\t\t\t\ts->stop( s );
\t\t\t\t}""",
        "existing player stop/completion path")

def apply(root: Path, report: Path | None = None) -> dict:
    sfdec = root / "Source/codec_sfdec.c"
    stream = root / "Source/stream_video.c"
    if not sfdec.is_file() or not stream.is_file():
        raise RuntimeError("expected pinned AVOS source tree")
    sfdec.write_text(patch_sfdec(sfdec.read_text()))
    stream.write_text(patch_stream_video(stream.read_text()))
    result = {
        "status":"PASS",
        "scope":"player-owned natural EOF completion only",
        "uses_existing_stream_stop":True,
        "sfdec_decoder_eos":True,
        "sfdec_sink_drain":True,
        "download_pipeline_changed":False,
        "webdav_transport_changed":False,
        "rebuffer_thresholds_changed":False,
        "device_playback_verified":False
    }
    if report:
        report.write_text(json.dumps(result, indent=2) + "\n")
    return result

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("avos",type=Path)
    p.add_argument("--report",type=Path)
    a=p.parse_args()
    print(json.dumps(apply(a.avos,a.report),indent=2))
