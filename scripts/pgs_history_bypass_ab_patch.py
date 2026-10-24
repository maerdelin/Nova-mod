#!/usr/bin/env python3
"""NOVA RUN635 PGS history-cache bypass A/B experiment.

Single runtime change: skip retaining PGS subtitle history, including its
repeated multi-track PGS recovery scans. The selected PGS track still feeds the
existing subtitle decode queue. All non-PGS subtitle handling and every audio,
video, buffering, seek and timing path are unchanged.
"""
import argparse
import json
from pathlib import Path


MARKER = "NOVA_PGS_HISTORY_BYPASS_AB_V1"
ORIGINAL = "\t\t_cache_subtitle_packet(s, &packet);\n"
REPLACEMENT = (
    "\t\t/* NOVA_PGS_HISTORY_BYPASS_AB_V1: one-variable A/B experiment.\n"
    "\t\t * Bypass ONLY PGS history caching; active PGS subtitle packets still\n"
    "\t\t * reach the selected sq queue through the original code below.\n"
    "\t\t * Consequence: PGS track switching cannot replay old PGS state.\n"
    "\t\t */\n"
    "\t\tif (_subtitle_props_for_stream(s, stream)->format != SUB_FORMAT_PGS)\n"
    "\t\t\t_cache_subtitle_packet(s, &packet);\n"
)
ACTIVE_SUBTITLE_GUARD = (
    "\t\tif (s->subtitle->valid && !s->subtitle->ext && stream == s->subtitle->stream) {\n"
)
EXPECTED_ROUTING = "\t} else if( _subtitle_props_for_stream(s, stream) ) {\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    source_file = args.native / "Source/stream_parser_ffmpeg.c"
    original = source_file.read_text(encoding="utf-8")
    assert original.count(ORIGINAL) == 1, "PGS cache call anchor must occur once"
    assert original.count(EXPECTED_ROUTING) == 1, "subtitle routing anchor changed"
    assert original.count(ACTIVE_SUBTITLE_GUARD) == 1, "active subtitle delivery anchor changed"
    assert MARKER not in original, "PGS history bypass already installed"
    # Preserve adjacent subtitle routing and selected subtitle playback exactly.
    routing = original.index(EXPECTED_ROUTING)
    cache = original.index(ORIGINAL, routing)
    selected = original.index(ACTIVE_SUBTITLE_GUARD, routing)
    assert routing < cache < selected, "unexpected subtitle routing order"

    modified = original.replace(ORIGINAL, REPLACEMENT, 1)
    assert modified.replace(REPLACEMENT, ORIGINAL, 1) == original, "non-isolated patch"
    assert modified.count(ACTIVE_SUBTITLE_GUARD) == 1
    assert modified.count(MARKER) == 1
    source_file.write_text(modified, encoding="utf-8")

    report = {
        "experiment": MARKER,
        "only_runtime_change": "Skip historical subtitle-cache processing for PGS packets",
        "pgs_history_enabled": False,
        "selected_pgs_subtitle_delivery": "unchanged",
        "non_pgs_subtitle_history": "unchanged",
        "video_audio_demux": "unchanged",
        "decoder_render_sync_rebuffer": "unchanged",
        "seek_policies": "unchanged",
        "known_tradeoff": "PGS subtitle hot-switching cannot replay prior PGS decoder state",
        "source": str(source_file),
        "anchor_count": 1,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    print(MARKER + "=ENABLED selected_pgs_delivery=UNCHANGED")


if __name__ == "__main__":
    main()
