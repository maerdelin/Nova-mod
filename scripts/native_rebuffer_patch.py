#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

EXPECTED_AVOS_COMMIT = "b313441df14414632781617742efb66778689b91"
LOW_BYTES = 24 * 1024 * 1024
RESUME_BYTES = 64 * 1024 * 1024
ARM_BUFFER_BYTES = 128 * 1024 * 1024
POLL_MS = 50


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


def sub_once(text: str, pattern: str, repl, label: str) -> str:
    out, count = re.subn(pattern, repl, text, count=1, flags=re.M)
    if count != 1:
        raise RuntimeError(f"{label}: expected one regex anchor, got {count}")
    return out


def check_head(root: Path, allow_unpinned_head: bool = False) -> str:
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != EXPECTED_AVOS_COMMIT and not allow_unpinned_head:
        raise RuntimeError(
            f"aos-avos commit mismatch: expected {EXPECTED_AVOS_COMMIT}, got {head}"
        )
    if head != EXPECTED_AVOS_COMMIT:
        required = (
            root / "Include" / "stream.h",
            root / "Source" / "stream_video.c",
            root / "Source" / "stream.c",
            root / "Source" / "avos_mp_video.c",
            root / "Source" / "stream_parser_ffmpeg.c",
        )
        missing = [str(p.relative_to(root)) for p in required if not p.is_file()]
        if missing:
            raise RuntimeError(
                "unpinned aos-avos source is missing required files: " + ", ".join(missing)
            )
    return head


def patch_stream_h(path: Path) -> None:
    text = path.read_text()
    text = replace_once(
        text,
        "\tSTREAM_DECODER_CHANGED,\n\tSTREAM_SUBTITLE_CLEARED,\n} STREAM_MESSAGE;",
        "\tSTREAM_DECODER_CHANGED,\n\tSTREAM_SUBTITLE_CLEARED,\n"
        "\tSTREAM_BUFFERING_START,\n\tSTREAM_BUFFERING_END,\n} STREAM_MESSAGE;",
        "STREAM_MESSAGE enum",
    )
    # Append fields at the END of STREAM so all existing field offsets remain
    # byte-for-byte ABI compatible with official companion native libraries.
    text = sub_once(
        text,
        r"(\n\s*int\s+fps_start;\n\s*int\s+fps_count;\n\s*void\s+\*surface_handle;\n)(\s*\n}\s*STREAM;)",
        r"\1"
        "\n\t// Nova native WebDAV rebuffer state. Appended for ABI safety.\n"
        "\tpthread_t\trebuffer_thread_handle;\n"
        "\tint\t\trebuffer_thread_started;\n"
        "\tTHREAD_STATE\trebuffer_tstate;\n"
        "\tvolatile int\trebuffering;\n"
        "\tvolatile int\trebuffer_user_paused;\n"
        "\tvolatile int\trebuffer_play_requested;\n"
        "\tvolatile int\trebuffer_frame_seen;\n"
        "\tvolatile int\treadahead_enabled;\n"
        "\tvolatile int\tstartup_first_sink_logged;\n"
        "\tint\t\trebuffer_low_bytes;\n"
        "\tint\t\trebuffer_resume_bytes;\n"
        "\tint\t\trebuffer_capacity_bytes;\n"
        r"\2",
        "STREAM tail rebuffer fields",
    )
    path.write_text(text)


REBUFFER_THREAD = r'''
// *****************************************************************************
//
//  WebDAV native rebuffer monitor
//
//  The controller is inactive during prepare/preroll. It may enter automatic
//  rebuffering only after AVOS received a real Start command AND a video frame
//  has subsequently been submitted to the video sink.
//
// *****************************************************************************
static int _nova_rebuffer_eof( STREAM *s )
{
    int audio_done = !s->audio->valid || s->audio_parse_end;
    int video_done = !s->video->valid || s->video_parse_end;
    return audio_done && video_done;
}

static void *_rebuffer_thread( void *data )
{
    STREAM *s = (STREAM *)data;
    int last_wait_log = 0;

    DBGS serprintf("PID[%5d] rebuffer_thread::Starting\r\n", getpid());

    while( thread_state_get( &s->rebuffer_tstate ) != THREAD_EXIT ) {
        thread_state_ack( &s->rebuffer_tstate );

        if( thread_state_get( &s->rebuffer_tstate ) == THREAD_RUNNING ) {
            if( !s->seek && !s->seek_paused && !s->paused_internal &&
                s->parser && s->parser->get_stats ) {
                STREAM_PARSER_STATS stats;
                STREAM_PARSER_STATS *pst = s->parser->get_stats( s, &stats );

                if( pst && pst->buffer_size == s->rebuffer_capacity_bytes &&
                    s->rebuffer_low_bytes > 0 && s->rebuffer_resume_bytes > 0 ) {
                    int used = pst->buffer_used;
                    int eof = _nova_rebuffer_eof( s );
                    int active = __atomic_load_n( &s->rebuffering, __ATOMIC_ACQUIRE );
                    static int nova_ahead_last_log = 0;
                    if( s->paused && __atomic_load_n( &s->readahead_enabled, __ATOMIC_ACQUIRE ) ) {
                        int now = atime();
                        if( now - nova_ahead_last_log >= 1000 ) {
                            nova_ahead_last_log = now;
                            serprintf("NOVA_10X_READAHEAD: used=%d capacity=%d paused=1\n", used, pst->buffer_size);
                        }
                    }

                    if( !active ) {
                        int play_requested = __atomic_load_n(
                            &s->rebuffer_play_requested, __ATOMIC_ACQUIRE );
                        int frame_seen = __atomic_load_n(
                            &s->rebuffer_frame_seen, __ATOMIC_ACQUIRE );

                        if( play_requested && frame_seen &&
                            !s->paused && !s->stream_end &&
                            s->video_error == VE_NO_ERROR && !eof &&
                            used < s->rebuffer_low_bytes ) {
                            __atomic_store_n( &s->rebuffering, 1, __ATOMIC_RELEASE );
                            __atomic_store_n(
                                &s->rebuffer_user_paused, 0, __ATOMIC_RELEASE );

                            int was_paused = stream_pause( s );
                            if( was_paused ) {
                                __atomic_store_n(
                                    &s->rebuffering, 0, __ATOMIC_RELEASE );
                            } else {
                                last_wait_log = atime();
                                serprintf(
                                    "NOVA_REBUFFER_ENTER: used=%d low=%d resume=%d size=%d\n",
                                    used, s->rebuffer_low_bytes,
                                    s->rebuffer_resume_bytes, pst->buffer_size );
                                if( s->message_cb )
                                    s->message_cb( s, STREAM_BUFFERING_START );
                            }
                        }
                    } else {
                        int user_paused = __atomic_load_n(
                            &s->rebuffer_user_paused, __ATOMIC_ACQUIRE );
                        int now = atime();
                        if( now - last_wait_log >= 1000 ) {
                            last_wait_log = now;
                            serprintf(
                                "NOVA_REBUFFER_WAIT: used=%d resume=%d size=%d user_paused=%d\n",
                                used, s->rebuffer_resume_bytes,
                                pst->buffer_size, user_paused );
                        }

                        if( eof || s->stream_end ||
                            s->video_error != VE_NO_ERROR ||
                            used >= s->rebuffer_resume_bytes ) {
                            const char *reason =
                                s->video_error != VE_NO_ERROR ? "error" :
                                (eof || s->stream_end) ? "eof" : "threshold";

                            serprintf(
                                "NOVA_REBUFFER_EXIT: used=%d reason=%s user_paused=%d\n",
                                used, reason, user_paused );
                            if( s->message_cb )
                                s->message_cb( s, STREAM_BUFFERING_END );

                            if( !user_paused )
                                stream_un_pause( s, 0 );

                            __atomic_store_n(
                                &s->rebuffer_user_paused, 0, __ATOMIC_RELEASE );
                            __atomic_store_n(
                                &s->rebuffering, 0, __ATOMIC_RELEASE );
                        }
                    }
                } else if( __atomic_load_n(
                    &s->rebuffering, __ATOMIC_ACQUIRE ) ) {
                    int user_paused = __atomic_load_n(
                        &s->rebuffer_user_paused, __ATOMIC_ACQUIRE );
                    serprintf(
                        "NOVA_REBUFFER_EXIT: disabled user_paused=%d\n",
                        user_paused );
                    if( s->message_cb )
                        s->message_cb( s, STREAM_BUFFERING_END );
                    if( !user_paused )
                        stream_un_pause( s, 0 );
                    __atomic_store_n(
                        &s->rebuffer_user_paused, 0, __ATOMIC_RELEASE );
                    __atomic_store_n(
                        &s->rebuffering, 0, __ATOMIC_RELEASE );
                }
            }
        }

        msec_sleep( NOVA_REBUFFER_POLL_MS );
    }

    DBGS serprintf("PID[%5d] rebuffer_thread::Exiting\r\n", getpid());
    return NULL;
}
'''


def patch_stream_video(path: Path) -> None:
    text = path.read_text()

    text = replace_once(
        text,
        "#define THREAD_PRIO_SUBTITLE\t0\n",
        "#define THREAD_PRIO_SUBTITLE\t0\n\n"
        "#define NOVA_REBUFFER_ARM_BYTES    (128 * 1024 * 1024)\n"
        "#define NOVA_REBUFFER_LOW_BYTES    (24 * 1024 * 1024)\n"
        "#define NOVA_REBUFFER_RESUME_BYTES (64 * 1024 * 1024)\n"
        "#define NOVA_REBUFFER_POLL_MS      50\n",
        "rebuffer constants",
    )

    text = sub_once(
        text,
        r"(static\s+void\s+\*_parser_thread\s*\(\s*void\s+\*data\s*\);\n)",
        r"\1static void\t*_rebuffer_thread( void *data );\n",
        "rebuffer forward declaration",
    )

    text = sub_once(
        text,
        r"if\s*\(\s*!s->paused\s*\|\|\s*s->play_n_video_frames\s*\|\|\s*"
        r"s->play_n_audio_frames\s*\|\|\s*s->parser_parse_once\s*\)\s*\{",
        "if( !s->paused || __atomic_load_n( &s->readahead_enabled, __ATOMIC_ACQUIRE ) || "
        "__atomic_load_n( &s->rebuffering, __ATOMIC_ACQUIRE ) || "
        "s->play_n_video_frames || s->play_n_audio_frames || s->parser_parse_once ) {",
        "parser continues during rebuffer",
    )

    text = replace_once(
        text,
        "static void _seek_init( STREAM *s )\n{\n\ts->seek = 1;",
        "static void _seek_init( STREAM *s )\n{\n"
        "\t__atomic_store_n( &s->rebuffer_frame_seen, 0, __ATOMIC_RELEASE );\n"
        "\ts->seek = 1;",
        "reset rebuffer first-frame proof on seek",
    )

    text = replace_once(
        text,
        "\ts->video_sink_count ++;\n\tpthread_mutex_unlock( &s->video_sink_mutex );",
        "\ts->video_sink_count ++;\n"
        "\tif( __atomic_load_n( &s->rebuffer_play_requested, __ATOMIC_ACQUIRE ) )\n"
        "\t\t__atomic_store_n( &s->rebuffer_frame_seen, 1, __ATOMIC_RELEASE );\n"
        "\tpthread_mutex_unlock( &s->video_sink_mutex );",
        "prove first frame reached video sink",
    )

    text = sub_once(
        text,
        r"(static\s+void\s+\*_player_thread\s*\(\s*void\s+\*data\s*\)\s*\n\{)",
        lambda m: REBUFFER_THREAD + "\n" + m.group(1),
        "insert rebuffer thread",
    )

    marker = "\t// lock and start the subtitle_thread\n"
    start_block = (
        "\t// independent low-water monitor; parser remains the producer.\n"
        "\tif( _stream_start_thread( &s->rebuffer_tstate, &s->rebuffer_thread_handle,\n"
        "\t\t&s->rebuffer_thread_started, _rebuffer_thread, s, stream_prio_parser, \"rbuf\" ) )\n"
        "\t\tgoto ErrorExit;\n\t\n"
    )
    text = replace_once(text, marker, start_block + marker, "start rebuffer thread")

    text = replace_once(
        text,
        "\tthread_state_set( &s->parser_tstate, THREAD_RUNNING );\n"
        "\tthread_state_set( &s->engine_tstate, THREAD_RUNNING );",
        "\tthread_state_set( &s->parser_tstate,   THREAD_RUNNING );\n"
        "\tthread_state_set( &s->rebuffer_tstate, THREAD_RUNNING );\n"
        "\tthread_state_set( &s->engine_tstate,   THREAD_RUNNING );",
        "run rebuffer thread",
    )

    path.write_text(text)


def patch_stream_c(path: Path) -> None:
    text = path.read_text()
    marker = 'DBGS serprintf("waiting for threads to join\\r\\n");\n'
    block = r'''DBGS serprintf("waiting for threads to join\r\n");
    // Stop the rebuffer controller before playback/parser threads it may touch.
    if( s->rebuffer_thread_started ) {
        thread_state_set( &s->rebuffer_tstate, THREAD_EXIT );
        apthread_join( s->rebuffer_thread_handle, NULL );
        s->rebuffer_thread_started = 0;
        __atomic_store_n( &s->rebuffering, 0, __ATOMIC_RELEASE );
        __atomic_store_n( &s->rebuffer_user_paused, 0, __ATOMIC_RELEASE );
        __atomic_store_n( &s->rebuffer_play_requested, 0, __ATOMIC_RELEASE );
        __atomic_store_n( &s->rebuffer_frame_seen, 0, __ATOMIC_RELEASE );
        __atomic_store_n( &s->readahead_enabled, 0, __ATOMIC_RELEASE );
        pthread_cond_destroy( &s->rebuffer_tstate._cond );
        pthread_mutex_destroy( &s->rebuffer_tstate._mutex );
DBGS   serprintf("rebuffer_thread joined\r\n");
    }
'''
    text = replace_once(text, marker, block, "join rebuffer thread")
    path.write_text(text)


def patch_avos_mp_video(path: Path) -> None:
    text = path.read_text()

    text = replace_once(
        text,
        "\tcase STREAM_SUBTITLE_CHANGED:\n"
        "\t\tsend_subtitle(mp, video);\n"
        "\t\tbreak;\n"
        "\tdefault:",
        "\tcase STREAM_SUBTITLE_CHANGED:\n"
        "\t\tsend_subtitle(mp, video);\n"
        "\t\tbreak;\n"
        "\tcase STREAM_BUFFERING_START:\n"
        "\t\tavos_mp_sendevent(mp, MEDIA_INFO, MEDIA_INFO_BUFFERING_START, 0);\n"
        "\t\tbreak;\n"
        "\tcase STREAM_BUFFERING_END:\n"
        "\t\tavos_mp_sendevent(mp, MEDIA_INFO, MEDIA_INFO_BUFFERING_END, 0);\n"
        "\t\tbreak;\n"
        "\tdefault:",
        "buffering media info",
    )

    text = replace_once(
        text,
        "int avos_mp_video_start(avos_mp_t *mp, avos_mp_video_t *video)\n"
        "{\n"
        "\tif (stream_is_paused(video->s))\n"
        "\t\tstream_un_pause_from_jni(video->s, 0);",
        "int avos_mp_video_start(avos_mp_t *mp, avos_mp_video_t *video)\n"
        "{\n"
        "\t// A real AVOS Start is the first permission for low-water control.\n"
        "\t__atomic_store_n(&video->s->rebuffer_play_requested, 1, __ATOMIC_RELEASE);\n"
        "\t__atomic_store_n(&video->s->readahead_enabled, 1, __ATOMIC_RELEASE);\n"
        "\t__atomic_store_n(&video->s->rebuffer_frame_seen, 0, __ATOMIC_RELEASE);\n"
        "\tif (__atomic_load_n(&video->s->rebuffering, __ATOMIC_ACQUIRE)) {\n"
        "\t\t// This path is reachable only after prior real playback entered\n"
        "\t\t// automatic rebuffering. Keep waiting for the resume watermark.\n"
        "\t\t__atomic_store_n(&video->s->rebuffer_user_paused, 0, __ATOMIC_RELEASE);\n"
        "\t\treturn AVOS_ERR_OK;\n"
        "\t}\n"
        "\tif (stream_is_paused(video->s))\n"
        "\t\tstream_un_pause_from_jni(video->s, 0);",
        "real play arms rebuffer lifecycle",
    )

    text = replace_once(
        text,
        "int avos_mp_video_pause(avos_mp_t *mp, avos_mp_video_t *video)\n"
        "{\n"
        "\tif (is_stream_pauseable(mp, video))",
        "int avos_mp_video_pause(avos_mp_t *mp, avos_mp_video_t *video)\n"
        "{\n"
        "\t__atomic_store_n(&video->s->rebuffer_play_requested, 0, __ATOMIC_RELEASE);\n"
        "\t__atomic_store_n(&video->s->rebuffer_frame_seen, 0, __ATOMIC_RELEASE);\n"
        "\tif (__atomic_load_n(&video->s->rebuffering, __ATOMIC_ACQUIRE)) {\n"
        "\t\t// Manual pause issued while buffering: user pause wins.\n"
        "\t\t__atomic_store_n(&video->s->rebuffer_user_paused, 1, __ATOMIC_RELEASE);\n"
        "\t\treturn AVOS_ERR_OK;\n"
        "\t}\n"
        "\tif (is_stream_pauseable(mp, video))",
        "manual pause disarms rebuffer lifecycle",
    )

    path.write_text(text)



def patch_stream_parser_ffmpeg(path: Path) -> None:
    text = path.read_text()

    text = replace_once(
        text,
        """static int _add_packet( AVQueue *q, AVPacket *packet )
{
\tpthread_mutex_lock( &q->mutex );
\tint64_t cost = packet_cost(packet);
\tif (cost > INT_MAX - q->mem_used || q->packets >= FF_QUEUE_MAX_PACKETS) {
\t\tpthread_mutex_unlock(&q->mutex);
\t\treturn 1;
\t}
""",
        """static int _add_packet_limited( AVQueue *q, AVPacket *packet, int packet_limit )
{
\tpthread_mutex_lock( &q->mutex );
\tint64_t cost = packet_cost(packet);
\tif (cost > INT_MAX - q->mem_used || q->packets >= packet_limit) {
\t\tpthread_mutex_unlock(&q->mutex);
\t\treturn 1;
\t}
""",
        "FFmpeg packet queue admission helper",
    )

    text = replace_once(
        text,
        """\tpthread_mutex_unlock( &q->mutex );
\treturn 0;
}

// ************************************************************
//
//\t_get_packet
""",
        """\tpthread_mutex_unlock( &q->mutex );
\treturn 0;
}

static int _add_packet( AVQueue *q, AVPacket *packet )
{
\treturn _add_packet_limited( q, packet, FF_QUEUE_MAX_PACKETS );
}

// ************************************************************
//
//\t_get_packet
""",
        "preserve default FFmpeg packet cap wrapper",
    )

    text = replace_once(
        text,
        """\t// One admitted packet may cross the normal budget. Beyond that, fail
\t// explicitly instead of silently losing audio or allocating without limit.
\tif (used + cost > budget * 2 || _add_packet(q, packet))
\t\treturn parser_read_error(s, AVERROR(ENOMEM));
""",
        """\t// One admitted packet may cross the normal budget. Beyond that, fail
\t// explicitly instead of silently losing audio or allocating without limit.
\t//
\t// After the first real Start, playback/decoder state must not create a
\t// second packet-count wall before the dynamic 10X byte budget.
\tint nova_fill_to_byte_wall =
\t\t__atomic_load_n(&s->readahead_enabled, __ATOMIC_ACQUIRE) ||
\t\t__atomic_load_n(&s->rebuffering, __ATOMIC_ACQUIRE);
\tint packet_limit = nova_fill_to_byte_wall ? INT_MAX : FF_QUEUE_MAX_PACKETS;
\tif (used + cost > budget * 2 ||
\t    _add_packet_limited(q, packet, packet_limit))
\t\treturn parser_read_error(s, AVERROR(ENOMEM));
""",
        "rebuffer FFmpeg packet admission",
    )

    text = replace_once(
        text,
        """\t// Preserve the bounded audio-gap scan and seek-preroll policies below.
\tif (!ff_p->seeking && !audio_starved &&
\t    (audio_packets >= FF_QUEUE_MAX_PACKETS ||
\t     queue_packets(&ff_p->vq) >= FF_QUEUE_MAX_PACKETS ||
\t     queue_packets(&ff_p->sq) >= FF_QUEUE_MAX_PACKETS)) {
DBGP2\t\tserprintf("FFMPEG: packet queue full, waiting for consumption (audio=%d)\\n", audio_packets);
\t\treturn FF_PARSE_WAIT;
\t}
""",
        """\t// Preserve the bounded audio-gap scan and seek-preroll policies below.
\t// During Nova INTERNAL rebuffer, consumers are deliberately frozen until a
\t// BYTE watermark is reached. Do not let the unrelated packet-count watermark
\t// block this producer first; the byte budget below remains the hard memory
\t// bound. Outside internal rebuffer, behavior is byte-for-byte equivalent.
\tint nova_rebuffering = __atomic_load_n(&s->rebuffering, __ATOMIC_ACQUIRE);
\tint nova_fill_to_byte_wall =
\t\t__atomic_load_n(&s->readahead_enabled, __ATOMIC_ACQUIRE) || nova_rebuffering;
\tint video_packets = queue_packets(&ff_p->vq);
\tint sub_packets = queue_packets(&ff_p->sq);
\tif (!nova_fill_to_byte_wall && !ff_p->seeking && !audio_starved &&
\t    (audio_packets >= FF_QUEUE_MAX_PACKETS ||
\t     video_packets >= FF_QUEUE_MAX_PACKETS ||
\t     sub_packets >= FF_QUEUE_MAX_PACKETS)) {
DBGP2\t\tserprintf("FFMPEG: packet queue full, waiting for consumption (audio=%d)\\n", audio_packets);
\t\treturn FF_PARSE_WAIT;
\t}
\tif (nova_fill_to_byte_wall &&
\t    (audio_packets == FF_QUEUE_MAX_PACKETS ||
\t     video_packets == FF_QUEUE_MAX_PACKETS ||
\t     sub_packets == FF_QUEUE_MAX_PACKETS)) {
\t\tserprintf("NOVA_10X_PACKET_CAP_BYPASS: aq=%d vq=%d sq=%d used=%lld budget=%d\\n",
\t\t\taudio_packets, video_packets, sub_packets,
\t\t\t(long long)mem_used, ff_p->buffer_size);
\t}
""",
        "pre-read FFmpeg packet backpressure",
    )

    if text.count("_add_packet_limited") != 3:
        raise RuntimeError("FFmpeg root-fix postcondition failed: _add_packet_limited count")
    if text.count("NOVA_10X_PACKET_CAP_BYPASS") != 1:
        raise RuntimeError("FFmpeg 10X read-ahead postcondition failed: diagnostic count")
    if text.count("readahead_enabled") < 2:
        raise RuntimeError("FFmpeg 10X read-ahead flag missing")
    if text.count("if( mem_used > ff_p->buffer_size && !audio_starved && !ff_p->seeking )") != 1:
        raise RuntimeError("FFmpeg dynamic 10X byte wall missing")

    path.write_text(text)


def patch_dynamic_bitrate(root: Path) -> None:
    """Per-title 2/5/10 seconds of average bytes; FFmpeg demux queue budget authoritative."""
    ff = root / "Source" / "stream_parser_ffmpeg.c"
    text = ff.read_text()
    needle = """\ts->duration = ff_p->duration;
\ts->size     = ff_p->size;
"""
    dynamic = r'''\ts->duration = ff_p->duration;
\ts->size     = ff_p->size;

    // X = file bytes / duration seconds. Compute without multiplying a
    // multi-gigabyte file length by 1000 (overflow); clamp BEFORE narrowing.
    // Packet queue counters use signed int, so cap total at INT_MAX/2.
    uint64_t nova_x = 0;
    const uint64_t nova_max_x = (uint64_t)(INT_MAX / 2) / 10;
    if (ff_p->size_known && s->size > 0 && s->duration > 0) {
        uint64_t duration_ms = (uint64_t)s->duration;
        uint64_t whole = (uint64_t)s->size / duration_ms;
        uint64_t remain = (uint64_t)s->size % duration_ms;
        if (whole > nova_max_x / 1000)
            nova_x = nova_max_x;
        else
            nova_x = whole * 1000 + (remain * 1000) / duration_ms;
        if (nova_x > nova_max_x) nova_x = nova_max_x;
    }
    if (nova_x > 0) {
        s->rebuffer_low_bytes = (int)(2 * nova_x);
        s->rebuffer_resume_bytes = (int)(5 * nova_x);
        s->rebuffer_capacity_bytes = (int)(10 * nova_x);
        ff_p->buffer_size = s->rebuffer_capacity_bytes;
        // STREAM retains legacy MiB unit. The FFmpeg budget above is exact.
        s->buffer_size = (s->rebuffer_capacity_bytes + 1048575) / 1048576;
        serprintf("NOVA_DYNAMIC_BUFFER: mode=average size=%llu duration_ms=%d x_bytes_per_sec=%llu low=%d resume=%d capacity=%d\n",
                  (unsigned long long)s->size, s->duration,
                  (unsigned long long)nova_x,
                  s->rebuffer_low_bytes, s->rebuffer_resume_bytes,
                  s->rebuffer_capacity_bytes);
    } else {
        // Metadata absent or invalid: preserve playable known-good defaults.
        s->rebuffer_low_bytes = 24 * 1024 * 1024;
        s->rebuffer_resume_bytes = 64 * 1024 * 1024;
        s->rebuffer_capacity_bytes = 128 * 1024 * 1024;
        ff_p->buffer_size = s->rebuffer_capacity_bytes;
        serprintf("NOVA_DYNAMIC_BUFFER: mode=fallback size=%llu duration_ms=%d low=%d resume=%d capacity=%d\n",
                  (unsigned long long)s->size, s->duration,
                  s->rebuffer_low_bytes, s->rebuffer_resume_bytes,
                  s->rebuffer_capacity_bytes);
    }
'''
    text = replace_once(text, needle, dynamic.replace(r"\t", "\t"), "install exact dynamic FFmpeg queue budget")
    ff.write_text(text)


def patch_startup_trace(root: Path) -> None:
    """Observational startup milestones only; no threshold or scheduling changes."""
    avos = root / "Source" / "avos_mp_video.c"
    text = avos.read_text()
    text = replace_once(text,
        "\tint _flags = STREAM_PAUSED;\n",
        "\tint _flags = STREAM_PAUSED;\n"
        "\tint nova_trace_t0 = atime();\n"
        '\tserprintf("NOVA_STARTUP_TRACE open_begin t=%d starttime=%d\\n", nova_trace_t0, starttime);\n',
        "trace player open entry")
    text = replace_once(text,
        "\tif (stream_open(video->s, src, etype, _flags)) {",
        '\tserprintf("NOVA_STARTUP_TRACE stream_open_begin t=%d elapsed=%d\\n", atime(), atime()-nova_trace_t0);\n'
        "\tif (stream_open(video->s, src, etype, _flags)) {",
        "trace stream open entry")
    text = replace_once(text,
        "\tAV_set_state(AV_PLAYING, TYPE_VID, 0, video->s, NULL);",
        '\tserprintf("NOVA_STARTUP_TRACE stream_open_done t=%d elapsed=%d\\n", atime(), atime()-nova_trace_t0);\n'
        "\tAV_set_state(AV_PLAYING, TYPE_VID, 0, video->s, NULL);",
        "trace stream open return")
    text = replace_once(text,
        "\tif (stream_start(video->s)) {",
        '\tserprintf("NOVA_STARTUP_TRACE stream_start_begin t=%d elapsed=%d\\n", atime(), atime()-nova_trace_t0);\n'
        "\tif (stream_start(video->s)) {",
        "trace stream start entry")
    text = replace_once(text,
        "\tvideo->last_seekable = stream_seekable(video->s);",
        '\tserprintf("NOVA_STARTUP_TRACE stream_start_done t=%d elapsed=%d\\n", atime(), atime()-nova_trace_t0);\n'
        "\tvideo->last_seekable = stream_seekable(video->s);",
        "trace stream start return")
    avos.write_text(text)

    ff = root / "Source" / "stream_parser_ffmpeg.c"
    text = ff.read_text()
    text = replace_once(text,
        "\tif( !(s->parser_priv = (FF_PRIV*)amalloc( sizeof( FF_PRIV ) ) ) ) {",
        '\tserprintf("NOVA_STARTUP_TRACE ff_open_begin t=%d\\n", atime());\n'
        "\tif( !(s->parser_priv = (FF_PRIV*)amalloc( sizeof( FF_PRIV ) ) ) ) {",
        "trace ffmpeg parser entry")
    text = replace_once(text,
        "\tif( ffmpeg_open_input(ff_p, s->src.url, &ff_p->fmt_opts) != 0) {",
        '\tserprintf("NOVA_STARTUP_TRACE network_open_begin t=%d\\n", atime());\n'
        "\tif( ffmpeg_open_input(ff_p, s->src.url, &ff_p->fmt_opts) != 0) {",
        "trace network open start")
    text = replace_once(text,
        'DBGP serprintf("info\\r\\n");',
        '\tserprintf("NOVA_STARTUP_TRACE network_open_done t=%d\\n", atime());\n'
        'DBGP serprintf("info\\r\\n");',
        "trace network open complete")
    text = replace_once(text,
        "\t// Retrieve stream information\n",
        '\tserprintf("NOVA_STARTUP_TRACE probe_begin t=%d\\n", atime());\n'
        "\t// Retrieve stream information\n",
        "trace stream info start")
    text = replace_once(text,
        "\tif (_parse_format(s->etype, ff_p)) goto ErrorExit4;",
        '\tserprintf("NOVA_STARTUP_TRACE probe_done t=%d streams=%d\\n", atime(), ff_p->fmt->nb_streams);\n'
        "\tif (_parse_format(s->etype, ff_p)) goto ErrorExit4;",
        "trace probe complete")
    text = replace_once(text,
        "\tif( s->video->valid ) {\n\t\tff_p->need_key = 1;\n\t}",
        '\tserprintf("NOVA_STARTUP_TRACE parser_ready t=%d budget=%d\\n", atime(), ff_p->buffer_size);\n'
        "\tif( s->video->valid ) {\n\t\tff_p->need_key = 1;\n\t}",
        "trace parser ready")
    ff.write_text(text)

    video = root / "Source" / "stream_video.c"
    text = video.read_text()
    text = replace_once(text,
        'serprintf("\\r\\nstream_start %s\\r\\n", s->src.url );',
        'serprintf("NOVA_STARTUP_TRACE native_stream_start t=%d\\n", atime());\n'
        'serprintf("\\r\\nstream_start %s\\r\\n", s->src.url );',
        "trace native stream start")
    text = replace_once(text,
        "\t\t\t_check_sink_delay( s );\n\n\t\t\ts->current_frame     = frame;",
        '\t\t\tif( !__atomic_exchange_n( &s->startup_first_sink_logged, 1, __ATOMIC_ACQ_REL ) )\n'
        '\t\t\t\tserprintf("NOVA_STARTUP_TRACE first_frame_sink t=%d pts=%d\\n", atime(), frame->time);\n'
        "\t\t\t_check_sink_delay( s );\n\n\t\t\ts->current_frame     = frame;",
        "trace first sink frame")
    video.write_text(text)

def apply(
    root: Path,
    report: Path | None = None,
    allow_unpinned_head: bool = False,
) -> dict:
    root = root.resolve()
    head = check_head(root, allow_unpinned_head)

    patch_stream_h(root / "Include" / "stream.h")
    patch_stream_video(root / "Source" / "stream_video.c")
    patch_stream_c(root / "Source" / "stream.c")
    patch_avos_mp_video(root / "Source" / "avos_mp_video.c")
    patch_stream_parser_ffmpeg(root / "Source" / "stream_parser_ffmpeg.c")
    patch_startup_trace(root)
    patch_dynamic_bitrate(root)

    result = {
        "status": "PASS",
        "aos_avos_commit": head,
        "aos_avos_head_policy": "latest-structural" if allow_unpinned_head else "pinned",
        "architecture": "native AVOS single-stream read-ahead; presentation pause/decode consumption is decoupled from parser production",
        "activation": "real AVOS Start arms continuous parser read-ahead; no Java FIFO or parallel downloader",
        "measurement": "STREAM_PARSER_STATS.buffer_used = FFmpeg audio queue bytes + video queue bytes",
        "startup_policy": "prepare/preroll/seek preview cannot enter automatic rebuffer",
        "low_bytes": LOW_BYTES,
        "resume_bytes": RESUME_BYTES,
        "poll_ms": POLL_MS,
        "abi_safety": "new STREAM fields appended at struct tail; existing offsets unchanged",
        "manual_pause_policy": "manual pause stops presentation but leaves read-ahead armed; parser keeps filling until the dynamic 10X byte budget",
        "events": ["MEDIA_INFO_BUFFERING_START", "MEDIA_INFO_BUFFERING_END"],
        "queue_root_fix": "after real Start, FF_QUEUE_MAX_PACKETS is not a second wall; the existing dynamic 10X FFmpeg byte budget is normal backpressure",
        "pre_start_packet_cap": 8192,
        "post_start_packet_cap": None,
        "extra_prefetch_wall_bytes": 0,
        "diagnostic": "NOVA_10X_PACKET_CAP_BYPASS",
        "startup_diagnostic": "NOVA_STARTUP_TRACE",
        "dynamic_buffer": "2X low / 5X resume / 10X FFmpeg demux capacity, X=file size bytes / duration seconds",
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument(
        "--allow-unpinned-head",
        action="store_true",
        help="Allow a newer aos-avos HEAD; all exact patch anchors still fail closed.",
    )
    args = p.parse_args()
    print(json.dumps(apply(args.root, args.report, args.allow_unpinned_head), indent=2))


if __name__ == "__main__":
    main()
