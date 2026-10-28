#!/usr/bin/env python3
"""Load AVOS v6.6 subtitle JNI bridge before the native subtitle constructor.

Official v6.6 SubtitleEngine invokes nativeCreate() directly; direct video
launch can construct it before another class has loaded libavosjni.so.
Preserve native subtitle features and load the matching rebuilt JNI bridge.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

MARKER = "NOVA_V66_SUBTITLE_JNI_LOAD_V1"


def inject(source: str) -> str:
    if MARKER in source:
        raise RuntimeError("SubtitleEngine JNI loader applied twice")
    if "nativeCreate()J" not in source:
        raise RuntimeError("Official SubtitleEngine.nativeCreate()J missing")
    pattern = re.compile(
        r"(?m)^(\.method[ \t]+static[ \t]+constructor[ \t]+<clinit>\(\)V[ \t]*\n)"
        r"([ \t]*\.locals[ \t]+)([0-9]+)([ \t]*\n)"
    )
    found = list(pattern.finditer(source))
    if len(found) != 1:
        raise RuntimeError("SubtitleEngine <clinit>/.locals layout changed")
    m = found[0]
    count = int(m.group(3))
    if count > 220:
        raise RuntimeError("Unexpected static initializer register count")
    extra = (
        f"    # {MARKER}\n"
        f'    const-string v{count}, "avosjni"\n'
        f"    invoke-static {{v{count}}}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V\n"
    )
    out = (source[:m.start()] + m.group(1) + m.group(2) +
           str(count + 1) + m.group(4) + extra + source[m.end():])
    if out.count(MARKER) != 1:
        raise RuntimeError("SubtitleEngine JNI load guard was not unique")
    return out


def apply(candidate: Path, report: Path) -> None:
    files = sorted(candidate.glob("smali*/com/archos/mediacenter/video/player/SubtitleEngine.smali"))
    if len(files) != 1:
        raise RuntimeError(f"Expected one v6.6 SubtitleEngine.smali; got {len(files)}")
    path = files[0]
    before = path.read_text(encoding="utf-8")
    after = inject(before)
    path.write_text(after, encoding="utf-8")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({
        "status": "PASS", "marker": MARKER, "library": "avosjni",
        "subtitle_class": str(path), "keeps_official_subtitle_engine": True
    }, indent=2) + "\n", encoding="utf-8")
    print("NOVA_V66_SUBTITLE_JNI_LOAD=PASS")
