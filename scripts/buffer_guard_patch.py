#!/usr/bin/env python3
from __future__ import annotations
import json
import re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method [^\n]+\n.*?^\.end method', re.M | re.S)
PACKET_HANDOFF_MIB = 24


def one(paths, label):
    xs = list(paths)
    if len(xs) != 1:
        raise RuntimeError(f"{label}: expected 1, got {len(xs)}")
    return xs[0]


def method(text, sig):
    xs = [m for m in METHOD_RE.finditer(text) if sig in m.group(0).splitlines()[0]]
    if len(xs) != 1:
        raise RuntimeError(f"{sig}: expected 1, got {len(xs)}")
    return xs[0]


def bump_locals(block, extra=1):
    m = re.search(r'(?m)^    \.locals (\d+)\s*$', block)
    if not m:
        raise RuntimeError("method has no .locals")
    n = int(m.group(1))
    block = block[:m.start(1)] + str(n + extra) + block[m.end(1):]
    return block, n


def patch_player(text):
    m = method(text, " setVideoURI(Landroid/net/Uri;Ljava/util/Map;)V")
    block = m.group(0)
    if ":nova_packet_handoff_done" in block:
        return text, "already"

    block, reg = bump_locals(block, 1)
    tmp = f"v{reg}"
    loc = re.search(r'(?m)^    \.locals \d+\s*$', block)
    if not loc:
        raise RuntimeError("setVideoURI locals anchor missing")
    inject = f"""
    # Packet queue is only a bounded demux->decoder handoff/safety queue.
    # All remote download buffering policy lives in the native raw 2X/5X/10X layer.
    const/16 {tmp}, 0x18
    invoke-static {{{tmp}}}, Lcom/archos/medialib/LibAvos;->setStreamBufferSize(I)V
    :nova_packet_handoff_done
"""
    block = block[:loc.end()] + inject + block[loc.end():]
    return text[:m.start()] + block + text[m.end():], "applied"


def apply(root: Path, report: Path | None = None):
    player = one(root.glob("smali*/com/archos/mediacenter/video/player/Player.smali"), "Player")
    text, status = patch_player(player.read_text())
    player.write_text(text)
    result = {
        "status": "PASS",
        "player": status,
        "policy": {
            "packet_handoff_mib": PACKET_HANDOFF_MIB,
            "webdav_special_packet_buffer": False,
            "raw_prefetch_owner": "native FFmpeg source layer",
            "raw_policy": "dynamic 2X/5X/10X",
            "java_prefetch": False,
        },
    }
    if report:
        report.write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    print(json.dumps(apply(args.root, args.report), indent=2))
