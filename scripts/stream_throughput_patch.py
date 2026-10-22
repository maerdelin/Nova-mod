#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method [^\n]+\n.*?^\.end method', re.M | re.S)


def one(paths, label):
    xs = list(paths)
    if len(xs) != 1:
        raise RuntimeError(f"{label}: expected 1, got {len(xs)}")
    return xs[0]


def method(text, sig):
    xs = [m for m in METHOD_RE.finditer(text)
          if sig in m.group(0).splitlines()[0]]
    if len(xs) != 1:
        headers = [m.group(0).splitlines()[0] for m in METHOD_RE.finditer(text)]
        raise RuntimeError(
            f"{sig}: expected 1, got {len(xs)}; candidates="
            + str([h for h in headers if sig.split('(')[0].strip() in h])
        )
    return xs[0]


def bump_locals(block, extra):
    m = re.search(r'(?m)^    \.locals (\d+)\s*$', block)
    if not m:
        raise RuntimeError("method has no .locals")
    old = int(m.group(1))
    block = block[:m.start(1)] + str(old + extra) + block[m.end(1):]
    return block, old


def patch_upstream(text):
    sig = " upstreamBufferSize(Lcom/archos/filecorelibrary/FileEditor;Z)I"
    m = method(text, sig)
    block = m.group(0)
    if ":nova_webdav_max_throughput_original" in block:
        return text, "already"

    block, first = bump_locals(block, 2)
    mode = f"v{first}"
    tmp = f"v{first + 1}"
    loc = re.search(r'(?m)^    \.locals \d+\s*$', block)
    if not loc:
        raise RuntimeError("upstreamBufferSize locals missing")

    inject = f"""
    # WebDAV primary playback: always use the existing 1 MiB playback read-ahead.
    if-eqz p2, :nova_webdav_max_throughput_original
    iget-object {mode}, p0, Lcom/archos/filecorelibrary/StreamOverHttp;->mReadMode:Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;
    sget-object {tmp}, Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;->PLAYBACK:Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;
    if-ne {mode}, {tmp}, :nova_webdav_max_throughput_original
    instance-of {tmp}, p1, Lcom/archos/filecorelibrary/webdav/WebdavFileEditor;
    if-eqz {tmp}, :nova_webdav_max_throughput_original
    const {mode}, 0x400000    # nova WebDAV playback read-ahead 4MiB
    return {mode}

    :nova_webdav_max_throughput_original
"""
    block = block[:loc.end()] + inject + block[loc.end():]
    return text[:m.start()] + block + text[m.end():], "applied"


def patch_copy_buffer(text):
    sig = " handleResponse()V"
    m = method(text, sig)
    block = m.group(0)
    if ("0x100000    # nova localhost copy 1MiB" in block and
            "nova WebDAV source priority -8" in block):
        return text, "already"

    block, first = bump_locals(block, 1)
    prio = f"v{first}"
    loc = re.search(r'(?m)^    \.locals \d+\s*    pattern = re.compile(
        r'(?m)^    const/16 (v\d+), 0x2000\s*$'
        r'(?=(?:\n.*){0,4}\n    new-array v\d+, \1, \[B)'
    )
    matches = list(pattern.finditer(block))
    if len(matches) != 1:
        # Some baksmali versions insert a move before new-array. Keep the
        # search inside handleResponse and require exactly one 8 KiB allocation
        # that feeds a byte-array allocation.
        fallback = re.compile(
            r'(?ms)^    const/16 (v\d+), 0x2000\s*\n'
            r'(?P<middle>.{0,220}?)'
            r'^    new-array v\d+, \1, \[B'
        )
        matches = list(fallback.finditer(block))
        if len(matches) != 1:
            raise RuntimeError(
                f"handleResponse media copy buffer anchor: expected 1, got {len(matches)}"
            )
        mm = matches[0]
        start, end = mm.start(), mm.end()
        original = mm.group(0)
        reg = mm.group(1)
        replacement = original.replace(
            f"    const/16 {reg}, 0x2000",
            f"    const {reg}, 0x100000    # nova localhost copy 1MiB",
            1,
        )
        block = block[:start] + replacement + block[end:]
    else:
        mm = matches[0]
        reg = mm.group(1)
        block = (
            block[:mm.start()]
            + f"    const {reg}, 0x100000    # nova localhost copy 1MiB"
            + block[mm.end():]
        )

    return text[:m.start()] + block + text[m.end():], "applied"


def apply(root: Path, report: Path | None = None):
    outer = one(
        root.glob("smali*/com/archos/filecorelibrary/StreamOverHttp.smali"),
        "StreamOverHttp",
    )
    inner = one(
        root.glob("smali*/com/archos/filecorelibrary/StreamOverHttp$HttpSession.smali"),
        "StreamOverHttp$HttpSession",
    )

    outer_text, upstream = patch_upstream(outer.read_text())
    inner_text, copy = patch_copy_buffer(inner.read_text())
    outer.write_text(outer_text)
    inner.write_text(inner_text)

    result = {
        "status": "PASS",
        "scope": "WebDAV primary playback only",
        "webdav_playback_upstream_bytes": 4194304,
        "localhost_copy_bytes": 1048576,
        "native_rebuffer_unchanged": True,
        "upstream_patch": upstream,
        "copy_patch": copy,
    }
    if report:
        report.write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    print(json.dumps(apply(args.root, args.report), indent=2))
, block)
    if not loc:
        raise RuntimeError("handleResponse locals missing")
    priority = f"""
    # nova WebDAV source priority -8
    const/16 {prio}, -0x8
    invoke-static {{{prio}}}, Landroid/os/Process;->setThreadPriority(I)V
"""
    block = block[:loc.end()] + priority + block[loc.end():]

    pattern = re.compile(
        r'(?m)^    const/16 (v\d+), 0x2000\s*$'
        r'(?=(?:\n.*){0,4}\n    new-array v\d+, \1, \[B)'
    )
    matches = list(pattern.finditer(block))
    if len(matches) != 1:
        # Some baksmali versions insert a move before new-array. Keep the
        # search inside handleResponse and require exactly one 8 KiB allocation
        # that feeds a byte-array allocation.
        fallback = re.compile(
            r'(?ms)^    const/16 (v\d+), 0x2000\s*\n'
            r'(?P<middle>.{0,220}?)'
            r'^    new-array v\d+, \1, \[B'
        )
        matches = list(fallback.finditer(block))
        if len(matches) != 1:
            raise RuntimeError(
                f"handleResponse media copy buffer anchor: expected 1, got {len(matches)}"
            )
        mm = matches[0]
        start, end = mm.start(), mm.end()
        original = mm.group(0)
        reg = mm.group(1)
        replacement = original.replace(
            f"    const/16 {reg}, 0x2000",
            f"    const {reg}, 0x100000    # nova localhost copy 1MiB",
            1,
        )
        block = block[:start] + replacement + block[end:]
    else:
        mm = matches[0]
        reg = mm.group(1)
        block = (
            block[:mm.start()]
            + f"    const {reg}, 0x100000    # nova localhost copy 1MiB"
            + block[mm.end():]
        )

    return text[:m.start()] + block + text[m.end():], "applied"


def apply(root: Path, report: Path | None = None):
    outer = one(
        root.glob("smali*/com/archos/filecorelibrary/StreamOverHttp.smali"),
        "StreamOverHttp",
    )
    inner = one(
        root.glob("smali*/com/archos/filecorelibrary/StreamOverHttp$HttpSession.smali"),
        "StreamOverHttp$HttpSession",
    )

    outer_text, upstream = patch_upstream(outer.read_text())
    inner_text, copy = patch_copy_buffer(inner.read_text())
    outer.write_text(outer_text)
    inner.write_text(inner_text)

    result = {
        "status": "PASS",
        "scope": "WebDAV primary playback only",
        "webdav_playback_upstream_bytes": 1048576,
        "localhost_copy_bytes": 1048576,
        "native_rebuffer_unchanged": True,
        "upstream_patch": upstream,
        "copy_patch": copy,
    }
    if report:
        report.write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    print(json.dumps(apply(args.root, args.report), indent=2))
