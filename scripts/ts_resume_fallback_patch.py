#!/usr/bin/env python3
"""Fail-closed guard for TS saved-bookmark seek units (Run374 + hotfix).

Run374 computes TS average bitrate from FFmpeg metadata but deliberately
preserves legacy no_duration semantics. Its player bookmark can be supplied
in milliseconds (e.g. 933206) while stream_seek_pos() expects 0..1000
permille units when no_duration is set. Such an out-of-range startup seek
returns error and aborts playback. Drop only THAT seek, leaving the demuxer
already positioned at zero, so playback starts normally.

Do NOT rewrite bookmarks, alter TS timescale, hide unrelated playback/network
errors, or change MKV/MP4 seeking.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ANCHOR = "\t\tstream_seek_pos(video->s, pos, dir, STREAM_SEEK_RELAXED );"

INSERT = r'''
        // Special case: TS has a valid buffer-rate estimate, but legacy AVOS
        // still reports no_duration. Its positional API expects 0..1000
        // permille; a remembered playback TIME in milliseconds can be passed
        // here instead (933206, 5336807 in real-device regression logs).
        // An attempted seek is fatal. BEFORE calling it, ignore only the
        // invalid startup bookmark and let demuxing continue from byte zero.
        if (video->s->etype == ETYPE_MPEG_TS &&
            video->s->no_duration && wind_start == 0 &&
            pos > STREAM_POS_MAX) {
            serprintf("NOVA_TS_RESUME_FALLBACK: invalid_saved_pos=%u max_pos=%d action=play_from_start\n",
                      pos, STREAM_POS_MAX);
            return AVOS_ERR_OK;
        }
'''.lstrip("\n")


def is_invalid_startup_bookmark(etype_is_ts: bool, no_duration: bool,
                                current_pos: int, requested_pos: int) -> bool:
    """Mirror the narrow C condition for boundary/regression tests."""
    return (etype_is_ts and no_duration and current_pos == 0
            and requested_pos > 1000)


def transform(original: str) -> str:
    if original.count(ANCHOR) != 1:
        raise RuntimeError("Run374 seek call anchor missing or ambiguous")
    if "NOVA_TS_RESUME_FALLBACK:" in original:
        raise RuntimeError("TS fallback patch was already applied")
    if "int avos_mp_video_seek(" not in original:
        raise RuntimeError("Expected AVOS video seek function missing")
    # Keep all original seek paths byte-identical; insert one small guard.
    inserted = INSERT.replace("        ", "\t\t")
    return original.replace(ANCHOR, inserted + ANCHOR, 1)


def apply(root: Path, report: Path | None = None) -> dict:
    file = root / "Source" / "avos_mp_video.c"
    original = file.read_text()
    output = transform(original)
    file.write_text(output)
    result = {
        "status": "PASS",
        "purpose": "TS invalid saved-position startup -> play from beginning",
        "guard": "ETYPE_MPEG_TS and no_duration and current_pos==0 and requested_pos>STREAM_POS_MAX(1000)",
        "behavior": "suppress only invalid resume seek; do not set playback error",
        "unaffected": ["valid 0..1000 seeks", "already playing positions",
                       "MP4", "MKV", "all buffering thresholds", "WebDAV reconnect"],
        "log_tag": "NOVA_TS_RESUME_FALLBACK",
        "needs_real_reproduction_test": True,
    }
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("native_root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    print(json.dumps(apply(args.native_root, args.report), indent=2))


if __name__ == "__main__":
    main()
