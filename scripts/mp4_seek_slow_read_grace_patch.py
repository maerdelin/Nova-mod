#!/usr/bin/env python3
"""Fix FFmpeg runtime seek false error after a slow but successful RAW128 read.

The same MediaCodec + WebDAV RAW path can return a valid packet after >5s when
a simulated throttled HTTP range connection seeks repeatedly. The previous
5-second seek refill deadline expires inside av_read_frame(), then the seek
loop wrongly reports INVALIDDATA before attempting the next demux packet.
This isolated change extends the existing guarded refill window to 15 seconds;
does not change PGS caching, decoder, A/V clock, buffering or stream IO.
"""
import argparse
import json
from pathlib import Path

ORIGINAL = "while ((unsigned)(atime() - deadline) < 5000) {"
PATCHED = "while ((unsigned)(atime() - deadline) < 15000) { /* NOVA_MP4_SEEK_SLOW_READ_GRACE_V1 */"
CONTEXT = "FFMPEG: seek did not find a usable starting packet"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--native", type=Path, required=True)
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    path = a.native / "Source/stream_parser_ffmpeg.c"
    text = path.read_text(encoding="utf-8")
    assert text.count(ORIGINAL) == 1, "Seek deadline anchor missing or ambiguous"
    assert text.count(CONTEXT) == 1, "Seek fallback path changed"
    assert PATCHED not in text, "Seek patch already applied"
    text2 = text.replace(ORIGINAL, PATCHED, 1)
    assert text2.replace(PATCHED, ORIGINAL, 1) == text
    path.write_text(text2, encoding="utf-8")
    report = {
        "marker": "NOVA_MP4_SEEK_SLOW_READ_GRACE_V1",
        "change": "successful-read seek refill timeout 5000ms -> 15000ms",
        "cancellation_guards": "unchanged",
        "pgs_history_cache": "unchanged",
        "decoder_render_audio_buffering": "unchanged",
        "scope": "avoids false AVERROR_INVALIDDATA when an in-flight RAW128 read exceeds 5 seconds",
    }
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("NOVA_MP4_SEEK_SLOW_READ_GRACE_V1=PATCHED")


if __name__ == "__main__":
    main()
