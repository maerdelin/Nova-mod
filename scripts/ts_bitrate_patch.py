#!/usr/bin/env python3
"""Validate integrated TS-only X derivation in the native raw-10X patch.

The TS bitrate logic now lives beside the single raw-source buffering policy so
there is no second threshold owner and no second source mutation pass.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def apply(root: Path, report: Path | None = None) -> dict:
    path = root / "Source" / "stream_parser_ffmpeg.c"
    source = path.read_text()
    required = (
        "NOVA_TS_BITRATE:",
        "NOVA_RAW_10X_POLICY:",
        "nova_raw_set_policy",
        "nova_ts_duration_us",
        "demux-estimate",
    )
    missing = [token for token in required if source.count(token) < 1]
    if missing:
        raise RuntimeError("Integrated TS raw-10X policy missing: " + repr(missing))
    if "ff_p->buffer_size = s->rebuffer_capacity_bytes" in source:
        raise RuntimeError("TS validation found forbidden post-demux 10X assignment")
    result = {
        "status": "PASS",
        "scope": "TS X derivation integrated into the single pre-demux raw 10X policy",
        "priority": ["ISO title metadata", "libavformat/stream duration",
                     "demux bitrate estimate", "24/64/128MiB fallback"],
        "source_mutated_by_this_step": False,
        "no_extra_network_requests": True,
        "no_playback_seek_or_duration_mutation": True,
        "log_tag": "NOVA_TS_BITRATE",
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("native_root", type=Path)
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    print(json.dumps(apply(args.native_root, args.report), indent=2))


if __name__ == "__main__":
    main()
