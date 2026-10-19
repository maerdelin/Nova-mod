#!/usr/bin/env python3
"""Apply the proven ISO-only MPEG-TS proxy fast probe to current pinned AVOS.

Keep Run377 buffering, TS rate detection and resume fallback unchanged.
The historical ISO bridge produces localhost ?mpegts&nova_iso=1 streams;
deep PTS duration estimation would otherwise probe far into an ISO.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

OLD = '''\t// For thumbnails: use minimal probing to speed up processing
\tif (ff_p->flags & STREAM_PARSER_THUMB) {
\t\tav_dict_set(&ff_p->fmt_opts, "probesize", "500000", 0);      // 500KB instead of 10MB
\t\tav_dict_set(&ff_p->fmt_opts, "analyzeduration", "1000000", 0);  // 1 second max
\t} else {
\t\tav_dict_set(&ff_p->fmt_opts, "probesize", "10000000", 0);
\t}
'''
NEW = '''\t// ISO proxy is already resolved by libbluray. Probe only its first
\t// MPEG-TS packets; do not seek through the virtual title for PTS duration.
\t// All ordinary TS/MKV/MP4 paths retain their Run377 probe settings.
\tconst int nova_iso_proxy = strstr(s->src_query, "nova_iso=1") != NULL;
\tif (ff_p->flags & STREAM_PARSER_THUMB) {
\t\tav_dict_set(&ff_p->fmt_opts, "probesize", "500000", 0);      // 500KB instead of 10MB
\t\tav_dict_set(&ff_p->fmt_opts, "analyzeduration", "1000000", 0);  // 1 second max
\t} else if (nova_iso_proxy) {
\t\tav_dict_set(&ff_p->fmt_opts, "probesize", "2000000", 0);
\t\tav_dict_set(&ff_p->fmt_opts, "analyzeduration", "1500000", 0);
\t\tav_dict_set(&ff_p->fmt_opts, "skip_estimate_duration_from_pts", "1", 0);
\t\tserprintf("NOVA_ISO_FAST_PROBE: enabled\\n");
\t} else {
\t\tav_dict_set(&ff_p->fmt_opts, "probesize", "10000000", 0);
\t}
'''


def transform(source: str) -> str:
    if source.count(OLD) != 1:
        raise RuntimeError("ISO fast-probe source block missing or ambiguous")
    if "NOVA_ISO_FAST_PROBE:" in source:
        raise RuntimeError("ISO fast-probe already applied")
    if source.count("NOVA_TS_BITRATE:") != 1 or source.count("NOVA_TS_RESUME_FALLBACK:") != 0:
        # AVOS resume guard is in avos_mp_video.c; don't let the check rely on it.
        if source.count("NOVA_TS_BITRATE:") != 1:
            raise RuntimeError("Current Run377 TS-rate patch not installed")
    return source.replace(OLD, NEW, 1)


def apply(native_root: Path, report: Path | None = None) -> dict:
    path = native_root / "Source" / "stream_parser_ffmpeg.c"
    path.write_text(transform(path.read_text()))
    result = {
        "status": "PASS",
        "scope": "only localhost Blu-ray ISO proxy probe",
        "original_ts_mkv_mp4": "unchanged",
        "source_tag": "NOVA_ISO_FAST_PROBE",
        "ISO_probesize": 2000000,
        "ISO_analyzeduration": 1500000,
        "ISO_skip_estimate_duration_from_pts": True,
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("native_root", type=Path)
    p.add_argument("--report", type=Path)
    opts = p.parse_args()
    print(json.dumps(apply(opts.native_root, opts.report), indent=2))


if __name__ == "__main__":
    main()
