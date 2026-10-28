#!/usr/bin/env python3
"""Two scoped AVOS fixes: prepared zero re-seek and MKV seek false success.

Apply after mkv_bbc_cue_seek_patch.py. Do not change the transport, buffering
policy, ISO seek mapping, user resume positions, or the APK's Java callbacks.
"""
import argparse
import json
from pathlib import Path


def once(text, before, after, label):
    count = text.count(before)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, got {count}")
    return text.replace(before, after, 1)


ZERO_GUARD = r'''
        /* NOVA_STARTUP_NATIVE_ZERO_SKIP_V2: PlayerService can enqueue 0
         * while initial native preparation is still busy. Its Java snapshot
         * is then -1, although the command worker reaches frame 0 before it
         * executes this request. Decide here, with actual stream state.
         * Returning OK keeps the existing MEDIA_SEEK_COMPLETE notification.
         * An established audio timeline, nonzero resume, unknown position,
         * and every ISO/local source keep their original seek behavior. */
        const char *nova_path = strstr(video->s->src.url, "/stream");
        if (pos == 0 && wind_start == 0 &&
            video->s->seek_epoch > 0 && video->s->video_time == 0 &&
            video->s->audio_time < 0 && !video->s->no_duration &&
            !strncmp(video->s->src.url, "novatransport://", 16) &&
            nova_path && (nova_path[7] == 0 || nova_path[7] == '?')) {
            serprintf("NOVA_STARTUP_NATIVE_ZERO_SKIP_V2: epoch=%d current=0 target=0 preserve=prepared-frame-and-raw\n",
                      video->s->seek_epoch);
            return AVOS_ERR_OK;
        }
'''


def patch_video(text):
    if "NOVA_STARTUP_NATIVE_ZERO_SKIP_V2" in text:
        raise RuntimeError("startup native zero guard already installed")
    anchor = "\t\tdir = pos >= wind_start ? STREAM_SEEK_FORWARD : STREAM_SEEK_BACKWARD;"
    return once(text, anchor, ZERO_GUARD + "\n" + anchor, "native command-time zero guard")


def patch_initial_ffmpeg_audio_selection(text):
    """Only pre-first-frame selection must not generate a video timeline Seek.

    A fresh stream has both time clocks at -1. A first track choice then
    calls generic stream_parser_set_audio_stream -> stream_seek_time(-2)
    which clamps to zero and re-seeks MKV/ISO/MP4 in the AVOS player.
    On a running stream -- including playback at exactly timestamp zero --
    invoke the ORIGINAL parser switch, preserving the AV decoder, demux
    reseek, video synchronization and user seeking behavior.
    """
    marker="NOVA_STARTUP_AUDIO_NO_TIMELINE_SEEK_V1"
    if marker in text:
        raise RuntimeError("initial audio selection already patched")
    old=("static int _set_audio_stream( STREAM *s, int audio_stream )\n"
         "{\n"
         "\treturn stream_parser_set_audio_stream( s, audio_stream);\n"
         "}")
    new=r'''static int _set_audio_stream( STREAM *s, int audio_stream )
{
    /* NOVA_STARTUP_AUDIO_NO_TIMELINE_SEEK_V1:
     * Only an untouched, pre-first-frame stream has both clocks negative.
     * Keep the demux VIDEO cursor at the natural beginning. */
    if (s->video->valid && s->seek_epoch == 0 &&
        s->video_time < 0 && s->audio_time < 0 &&
        s->start_time == 0 && s->start_pos == 0) {
        _flush_packets( &ff_p->aq, "START_AUDIO_ONLY" );
        stream_parser_clear_audio_chunks( s );
        ff_p->last_audio_time = 0;
        s->audio_parse_end = 0;
        serprintf("NOVA_STARTUP_AUDIO_NO_TIMELINE_SEEK_V1: audio=%d epoch=%d video=%d no-video-seek\n",
                  audio_stream, s->seek_epoch, s->video_time);
        return 0;
    }
    return stream_parser_set_audio_stream( s, audio_stream);
}'''
    return once(text, old, new, "initial FFmpeg track selection at source")


def patch_parser(text):
    if "NOVA_MKV_SEEK_PHASE_V3" in text:
        raise RuntimeError("MKV phase budget already installed")
    text = once(text,
        "    int64_t mkv_seek_started_us;\n",
        "    int64_t mkv_seek_started_us;\n"
        "    int64_t mkv_seek_deadline_us; /* absolute bound across relocations */\n",
        "MKV absolute operation bound")
    text = once(text,
        "    if( av_gettime_relative() - raw->mkv_seek_started_us > 12000000 )\n",
        "    if( raw->mkv_seek_deadline_us > 0 &&\n"
        "        av_gettime_relative() >= raw->mkv_seek_deadline_us )\n"
        "        return 1;\n"
        "    if( av_gettime_relative() - raw->mkv_seek_started_us > 12000000 )\n",
        "preserve a finite total MKV deadline")
    # The source mutex excludes the producer; raw mutex excludes a RAW read.
    # Start packet-read time after waiting for the old HTTP read and opening
    # the new Range. Keep the aggregate byte/absolute bounds across all seeks
    # FFmpeg makes while resolving its index. Never clear a prior I/O failure.
    text = once(text,
        "        if( raw->mkv_single_get )\n"
        "            __atomic_store_n(&raw->mkv_seek_failed, 0, __ATOMIC_RELEASE);\n"
        "        pthread_mutex_lock(&raw->mutex);\n",
        "        pthread_mutex_lock(&raw->mutex);\n"
        "        if( raw->mkv_single_get &&\n"
        "            __atomic_load_n(&raw->mkv_seek_active, __ATOMIC_ACQUIRE) ) {\n"
        "            /* NOVA_MKV_SEEK_PHASE_V3: Range establishment is not\n"
        "             * packet scan time. Retain bytes and absolute deadline. */\n"
        "            raw->mkv_seek_started_us = av_gettime_relative();\n"
        "        }\n",
        "restart read deadline after successful Range establishment")
    text = once(text,
        "        ff_p->raw.mkv_seek_started_us=av_gettime_relative();\n",
        "        ff_p->raw.mkv_seek_started_us=av_gettime_relative();\n"
        "        ff_p->raw.mkv_seek_deadline_us=ff_p->raw.mkv_seek_started_us+45000000;\n",
        "bound whole indexed relocation to 45 seconds")
    # libavformat Matroska may return success after an interrupted index
    # extension scan, leaving the last reachable keyframe far behind target.
    # Do not erase that evidence at the existing post-index budget reset.
    text = once(text,
        "    if(nova_mkv_seek && ret >= 0) {\n"
        "        int64_t nova_position_us =\n",
        "    if(nova_mkv_seek && ret >= 0 && nova_mkv_seek_guard_failed(&ff_p->raw)) {\n"
        "        serprintf(\"NOVA_MKV_SEEK_REJECT_V3: stage=index reason=io-or-budget targetMs=%d bytes=%llu\\n\",\n"
        "                  time,(unsigned long long)ff_p->raw.mkv_seek_bytes);\n"
        "        __atomic_store_n(&ff_p->raw.mkv_seek_active,0,__ATOMIC_RELEASE);\n"
        "        return 1;\n"
        "    }\n"
        "    if(nova_mkv_seek && ret >= 0) {\n"
        "        int64_t nova_position_us =\n",
        "reject false success from interrupted Matroska index scan")
    text = once(text,
        "        ff_p->raw.mkv_seek_started_us = av_gettime_relative();\n"
        "        ff_p->raw.mkv_seek_bytes = 0;\n",
        "        ff_p->raw.mkv_seek_started_us = av_gettime_relative();\n"
        "        ff_p->raw.mkv_seek_deadline_us = ff_p->raw.mkv_seek_started_us + 12000000;\n"
        "        ff_p->raw.mkv_seek_bytes = 0;\n",
        "independent bounded post-index packet scan")
    text = once(text,
        "        serprintf(\"NOVA_MKV_SEEK_DONE_V2: found=%d scanMs=%lld bytes=%llu rebuffer=%d seekPaused=%d\\n\",\n",
        "        serprintf(\"NOVA_MKV_SEEK_POSITION_V3: targetMs=%d actualTs=%d found=%d failed=%d\\n\",\n"
        "                  time,found ? sc->time : -1,found,\n"
        "                  nova_mkv_seek_guard_failed(&ff_p->raw));\n"
        "        if(nova_mkv_seek_guard_failed(&ff_p->raw)) found=0;\n"
        "        serprintf(\"NOVA_MKV_SEEK_DONE_V2: found=%d scanMs=%lld bytes=%llu rebuffer=%d seekPaused=%d\\n\",\n",
        "record achieved packet timestamp and reject failed scan")
    return text


def apply(root, report=None):
    video = root / "Source/avos_mp_video.c"
    parser = root / "Source/stream_parser_ffmpeg.c"
    changed_video = patch_video(video.read_text())
    changed_parser = patch_parser(parser.read_text())
    changed_parser = patch_initial_ffmpeg_audio_selection(changed_parser)
    # Validate both files before writing either.
    video.write_text(changed_video)
    parser.write_text(changed_parser)
    result = {"status": "PASS", "version": "NOVA_STARTUP_BBC_SEEK_FIX_V3",
              "native_zero_skip": "prepared direct non-ISO frame zero; no audio epoch",
              "mkv_relocation_total_ms": 45000, "mkv_packet_scan_ms": 12000,
              "mkv_scan_max_bytes": 67108864, "transport_changed": False,
              "raw128_policy_changed": False, "iso_seek_changed": False}
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--native", type=Path, required=True)
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    print(json.dumps(apply(a.native, a.report)))
