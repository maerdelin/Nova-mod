#!/usr/bin/env python3
"""Disable automatic whole-player reopen after HDMI/audio route capability reports.

Only touches the targeted Player methods. The ordinary audio-track selection,
manual reopen, error recovery, and initial audio-output capability snapshot
remain unmodified. The build fails closed on any unexpected smali layout.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re

PLAYER = "Lcom/archos/mediacenter/video/player/Player;"
METHOD = "onAudioOutputChanged()V"

def _replace_player_method(smali: str) -> str:
    pattern = re.compile(
        r"(?ms)^(?P<header>\.method [^\n]*\bonAudioOutputChanged\(\)V\n)"
        r"(?P<body>.*?)^\.end method$"
    )
    matches = list(pattern.finditer(smali))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly 1 {METHOD} definition, got {len(matches)}")
    old = matches[0].group("body")
    if "openVideo()V" not in old or "suspendForSurface()V" not in old:
        raise RuntimeError("Audio output callback no longer rebuilds as expected")
    # No Java notification should destroy the current playback instance.
    return pattern.sub(lambda m: m.group("header") + "    .locals 0\n    return-void\n.end method", smali, count=1)

def _allow_prepared_to_continue(smali: str) -> str:
    pattern = re.compile(
        r"(?m)^(?P<call>\s+invoke-virtual(?:/range)?\s+\{[^}\n]+\},\s*"
        + re.escape(PLAYER + "->" + METHOD)
        + r"\s*\n)(?P<ret>[ \t]+)return-void(?P<after>[ \t]*(?:\#.*)?\n)"
    )
    if len(pattern.findall(smali)) != 1:
        raise RuntimeError("Expected 1 onPrepared audio-output rebuild early-return site")
    # The old early return is invalid once the callback stops rebuilding.
    # The media prepare state machine must continue to resume/start playback.
    return pattern.sub(lambda m: m.group("call") + m.group("ret") + "nop" + m.group("after"), smali, count=1)

def apply(decoded_root: Path, report: Path | None = None) -> dict:
    candidates = sorted(decoded_root.glob("smali*/com/archos/mediacenter/video/player/Player.smali"))
    if len(candidates) != 1:
        raise RuntimeError(f"Expected one Player.smali, got {len(candidates)}")
    path = candidates[0]
    source = path.read_text(encoding="utf-8")
    changed = _replace_player_method(source)
    changed = _allow_prepared_to_continue(changed)
    if changed == source:
        raise RuntimeError("Audio lifecycle patch did not change decoded APK")
    path.write_text(changed, encoding="utf-8")
    result = {
        "status": "PASS",
        "player_path": str(path.relative_to(decoded_root)),
        "audio_route_reopens_disabled": 1,
        "prepared_early_return_removed": 1,
        "audio_track_switch_preserved": "setAudioTrack(I)Z",
        "scope": "Player.smali only",
    }
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n")
    return result

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("decoded_root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    print(json.dumps(apply(args.decoded_root, args.report), indent=2))

if __name__ == "__main__":
    main()
