#!/usr/bin/env python3
"""TS-only rate detection for Run373 native FFmpeg rebuffer thresholds.

Applied AFTER native_rebuffer_patch.py and BEFORE compiling libavos.so.
Uses credible FFmpeg duration when available (upstream discards TS duration
for presentation), then a clearly labelled demux bitrate estimate. No new
network requests, no seek, no change to other containers or existing TS
duration/seek presentation. Falls back to Run373 24/64/128 MiB when unknown.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ANCHOR = (
    "    if (nova_x > 0) {\n"
    "        s->rebuffer_low_bytes = (int)(2 * nova_x);"
)

TS_CODE = r'''
    // TS has no presentation duration in upstream _parse_format(), but
    // libavformat may have learned a valid duration through timestamp probing.
    // Use it ONLY for buffer thresholds; do not alter playback seek/duration.
    if (s->etype == ETYPE_MPEG_TS) {
        const AVFormatContext *nova_ts_fmt = ff_p->fmt;
        const char *nova_ts_source = "fallback";
        int64_t nova_ts_duration_us = nova_ts_fmt ?
            nova_ts_fmt->duration : AV_NOPTS_VALUE;
        int64_t nova_ts_demux_bps = nova_ts_fmt ? nova_ts_fmt->bit_rate : 0;
        const uint64_t nova_ts_min_x = 8192;               // 64 kbit/s
        const uint64_t nova_ts_max_x = 25 * 1024 * 1024;   // 200+ Mbit/s

        // Only the locally generated Blu-ray ISO proxy can provide this
        // duration. Leave FFmpeg's presentation timebase and seek semantics
        // untouched. Invalid/missing metadata retains the original TS path.
        int nova_iso_metadata_valid = 0;
        const char *nova_iso_duration_arg = NULL;
        if (s->src_query &&
            strstr(s->src_query, "&nova_iso=1&") != NULL)
            nova_iso_duration_arg = strstr(
                s->src_query, "&nova_iso_duration_us=");
        if (nova_iso_duration_arg) {
            const char *digits = nova_iso_duration_arg +
                sizeof("&nova_iso_duration_us=") - 1;
            if (*digits >= '0' && *digits <= '9') {
                char *end = NULL;
                unsigned long long us = strtoull(digits, &end, 10);
                if (end != digits && (*end == '\0' || *end == '&') &&
                    us >= 10ULL * AV_TIME_BASE &&
                    us <= 24ULL * 3600 * AV_TIME_BASE) {
                    nova_ts_duration_us = (int64_t)us;
                    nova_iso_metadata_valid = 1;
                }
            }
        }

        if (ff_p->size_known && s->size > 0 && nova_ts_fmt) {
            // If the container duration is unknown, try timestamp duration
            // of a video stream, then audio. Do not sample or seek playback.
            if (nova_ts_duration_us <= 0 ||
                nova_ts_duration_us == AV_NOPTS_VALUE) {
                for (int pass = 0; pass < 2; pass++) {
                    for (unsigned int i = 0; i < nova_ts_fmt->nb_streams; i++) {
                        const AVStream *st = nova_ts_fmt->streams[i];
                        if (!st || !st->codecpar) continue;
                        if (st->codecpar->codec_type !=
                            (pass == 0 ? AVMEDIA_TYPE_VIDEO : AVMEDIA_TYPE_AUDIO))
                            continue;
                        if (st->duration <= 0 || st->duration == AV_NOPTS_VALUE ||
                            st->time_base.num <= 0 || st->time_base.den <= 0)
                            continue;
                        int64_t candidate = av_rescale_q(
                            st->duration, st->time_base, AV_TIME_BASE_Q);
                        if (candidate >= 10LL * AV_TIME_BASE &&
                            candidate <= 24LL * 3600 * AV_TIME_BASE) {
                            nova_ts_duration_us = candidate;
                            break;
                        }
                    }
                    if (nova_ts_duration_us >= 10LL * AV_TIME_BASE &&
                        nova_ts_duration_us <= 24LL * 3600 * AV_TIME_BASE)
                        break;
                }
            }

            // Exact file-size/duration arithmetic with overflow protection.
            // Reject impossible-looking metadata rather than using bad watermarks.
            if (nova_ts_duration_us >= 10LL * AV_TIME_BASE &&
                nova_ts_duration_us <= 24LL * 3600 * AV_TIME_BASE) {
                const uint64_t us = (uint64_t)nova_ts_duration_us;
                const uint64_t whole = (uint64_t)s->size / us;
                const uint64_t part = (uint64_t)s->size % us;
                uint64_t x = whole > nova_max_x / AV_TIME_BASE ?
                    nova_max_x : whole * AV_TIME_BASE +
                    (part * AV_TIME_BASE) / us;
                if (x >= nova_ts_min_x && x <= nova_ts_max_x) {
                    nova_x = x;
                    nova_ts_source = nova_iso_metadata_valid ?
                        "iso-title-metadata" : "duration-derived";
                }
            }

            // For streams without reliable duration, accept libavformat's
            // demux bitrate as an ESTIMATE, never claim exact average bitrate.
            if (nova_x == 0 &&
                nova_ts_demux_bps >= (int64_t)nova_ts_min_x * 8 &&
                nova_ts_demux_bps <= (int64_t)nova_ts_max_x * 8) {
                nova_x = (uint64_t)nova_ts_demux_bps / 8;
                nova_ts_source = "demux-estimate";
            }
            if (nova_x > nova_max_x) nova_x = nova_max_x;
        }
        serprintf("NOVA_TS_BITRATE: source=%s size=%llu duration_us=%lld demux_bps=%lld x_bytes_per_sec=%llu seekable=%d\n",
                  nova_ts_source, (unsigned long long)s->size,
                  (long long)nova_ts_duration_us, (long long)nova_ts_demux_bps,
                  (unsigned long long)nova_x,
                  nova_ts_fmt && nova_ts_fmt->pb ?
                    !!(nova_ts_fmt->pb->seekable & AVIO_SEEKABLE_NORMAL) : 0);
    }
'''.lstrip("\n")


def transform(source: str) -> str:
    if source.count(ANCHOR) != 1:
        raise RuntimeError("Run373 dynamic bitrate anchor missing or ambiguous")
    if "NOVA_TS_BITRATE:" in source:
        raise RuntimeError("TS bitrate patch already applied")
    if source.count("NOVA_DYNAMIC_BUFFER:") != 2:
        raise RuntimeError("Expected Run373 average/fallback diagnostics")
    return source.replace(ANCHOR, TS_CODE + "\n" + ANCHOR, 1)


def apply(root: Path, report: Path | None = None) -> dict:
    path = root / "Source" / "stream_parser_ffmpeg.c"
    old = path.read_text()
    new = transform(old)
    path.write_text(new)
    result = {
        "status": "PASS",
        "scope": "TS only, inside existing FFmpeg 2X/5X/10X allocation",
        "priority": ["libavformat demux duration", "stream timestamp duration",
                     "estimated demux bitrate", "original 24/64/128MiB fallback"],
        "non_ts": "Unchanged Run373 thresholds and source",
        "no_extra_network_requests": True,
        "no_playback_seek_or_duration_mutation": True,
        "log_tag": "NOVA_TS_BITRATE",
        "requires_device_test": True,
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("native_root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    print(json.dumps(apply(args.native_root, args.report), indent=2))


if __name__ == "__main__":
    main()
