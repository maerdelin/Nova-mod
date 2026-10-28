#!/usr/bin/env python3
"""Fail-closed official native manifest selection for the actual latest APK.

Never reuse the v6_6.xml native source when the official latest stable APK
moves to a different major/minor release. No fallback to an older branch.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

OFFICIAL_REPOSITORY = "nova-video-player/aos-AVP"
OFFICIAL_POLICY = "github-official-latest-stable"
VERSION = re.compile(r"v([1-9][0-9]*)\.([0-9]+)\.([0-9]+)\Z")


def native_manifest(metadata: dict) -> str:
    if metadata.get("repository") != OFFICIAL_REPOSITORY:
        raise ValueError("Official repository mismatch")
    if metadata.get("policy") != OFFICIAL_POLICY:
        raise ValueError("Refusing unverified or pinned upstream policy")
    tag = metadata.get("tag")
    if not isinstance(tag, str):
        raise ValueError("Official latest stable tag is missing")
    match = VERSION.fullmatch(tag)
    if match is None:
        raise ValueError(f"Unknown official release tag {tag!r}; no old native fallback")
    major, minor, _patch = map(int, match.groups())
    return f"v{major}_{minor}.xml"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: official_native_manifest.py inputs/upstream.json")
    metadata = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(native_manifest(metadata))


if __name__ == "__main__":
    main()
