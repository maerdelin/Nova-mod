#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

EXPECTED_AVOS_COMMIT = "b313441df14414632781617742efb66778689b91"
LOW_BYTES = 24 * 1024 * 1024
RESUME_BYTES = 45 * 1024 * 1024
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


def check_head(root: Path) -> str:
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != EXPECTED_AVOS_COMMIT:
        raise RuntimeError(
            f"aos-avos commit mismatch: expected {EXPECTED_AVOS_COMMIT}, got {head}"
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
        r"\2",
        "STREAM tail rebuffer fields",
    )
    path.write_text(text)


REBUFFER_THREAD = r'''
// *****************************************************************************
//
//  WebDAV native rebuffer monitor
//
//  WebDAV playback is marked by the 128 MiB AVOS parser buffer configured by
//  the Java entry point. This monitor reads the real FFmpeg packet-queue byte
//  count. It uses the normal AVOS pause/resume machinery to freeze clocks,
//  AudioTrack and decoder output, while parser_thread is explicitly allowed to
//  keep parsing during rebuffering.
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

                if( pst && pst->buffer_size >= NOVA_REBUFFER_ARM_BYTES ) {
                    int used = pst->buffer_used;
                    int eof = _nova_rebuffer_eof( s );

                    if( !s->rebuffering ) {
                        if( !s->paused && !s->stream_end &&
                            s->video_error == VE_NO_ERROR && !eof &&
                            used < NOVA_REBUFFER_LOW_BYTES ) {
                            s->rebuffering = 1;
                            s->rebuffer_user_paused = 0;

                            int was_paused = stream_pause( s );
                            if( was_paused ) {
                                s->rebuffering = 0;
                            } else {
                                last_wait_log = atime();
                                serprintf(
                                    "NOVA_REBUFFER_ENTER: used=%d low=%d resume=%d size=%d\n",
                                    used, NOVA_REBUFFER_LOW_BYTES,
                                    NOVA_REBUFFER_RESUME_BYTES, pst->buffer_size );
                                if( s->message_cb )
                                    s->message_cb( s, STREAM_BUFFERING_START );
                            }
                        }
                    } else {
                        int now = atime();
                        if( now - last_wait_log >= 1000 ) {
                            last_wait_log = now;
                            serprintf(
                                "NOVA_REBUFFER_WAIT: used=%d resume=%d size=%d user_paused=%d\n",
                                used, NOVA_REBUFFER_RESUME_BYTES,
                                pst->buffer_size, s->rebuffer_user_paused );
                        }

                        if( eof || s->stream_end ||
                            s->video_error != VE_NO_ERROR ||
                            used >= NOVA_REBUFFER_RESUME_BYTES ) {
                            int user_paused = s->rebuffer_user_paused;
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

                            s->rebuffer_user_paused = 0;
                            s->rebuffering = 0;
                        }
                    }
                } else if( s->rebuffering ) {
                    int user_paused = s->rebuffer_user_paused;
                    serprintf("NOVA_REBUFFER_EXIT: disabled user_paused=%d\n", user_paused);
                    if( s->message_cb )
                        s->message_cb( s, STREAM_BUFFERING_END );
                    if( !user_paused )
                        stream_un_pause( s, 0 );
                    s->rebuffer_user_paused = 0;
                    s->rebuffering = 0;
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
        "#define NOVA_REBUFFER_RESUME_BYTES (45 * 1024 * 1024)\n"
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
        "if( !s->paused || s->rebuffering || s->play_n_video_frames || "
        "s->play_n_audio_frames || s->parser_parse_once ) {",
        "parser continues during rebuffer",
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
        s->rebuffering = 0;
        s->rebuffer_user_paused = 0;
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
        "\tif (video->s->rebuffering) {\n"
        "\t\tvideo->s->rebuffer_user_paused = 0;\n"
        "\t\treturn AVOS_ERR_OK;\n"
        "\t}\n"
        "\tif (stream_is_paused(video->s))\n"
        "\t\tstream_un_pause_from_jni(video->s, 0);",
        "manual start during rebuffer",
    )

    text = replace_once(
        text,
        "int avos_mp_video_pause(avos_mp_t *mp, avos_mp_video_t *video)\n"
        "{\n"
        "\tif (is_stream_pauseable(mp, video))",
        "int avos_mp_video_pause(avos_mp_t *mp, avos_mp_video_t *video)\n"
        "{\n"
        "\tif (video->s->rebuffering) {\n"
        "\t\t// manual pause issued while buffering: user pause wins.\n"
        "\t\tvideo->s->rebuffer_user_paused = 1;\n"
        "\t\treturn AVOS_ERR_OK;\n"
        "\t}\n"
        "\tif (is_stream_pauseable(mp, video))",
        "manual pause during rebuffer",
    )

    path.write_text(text)


def apply(root: Path, report: Path | None = None) -> dict:
    root = root.resolve()
    head = check_head(root)

    patch_stream_h(root / "Include" / "stream.h")
    patch_stream_video(root / "Source" / "stream_video.c")
    patch_stream_c(root / "Source" / "stream.c")
    patch_avos_mp_video(root / "Source" / "avos_mp_video.c")

    result = {
        "status": "PASS",
        "aos_avos_commit": head,
        "architecture": "native AVOS rebuffer monitor; normal pause freezes consumers while parser continues",
        "activation": "parser buffer_size >= 128 MiB (set only for WebDAV by APK patch)",
        "measurement": "STREAM_PARSER_STATS.buffer_used = FFmpeg audio queue bytes + video queue bytes",
        "low_bytes": LOW_BYTES,
        "resume_bytes": RESUME_BYTES,
        "poll_ms": POLL_MS,
        "abi_safety": "new STREAM fields appended at struct tail; existing offsets unchanged",
        "manual_pause_policy": "user pause wins; automatic resume is suppressed until user starts again",
        "events": ["MEDIA_INFO_BUFFERING_START", "MEDIA_INFO_BUFFERING_END"],
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    print(json.dumps(apply(args.root, args.report), indent=2))


if __name__ == "__main__":
    main()
