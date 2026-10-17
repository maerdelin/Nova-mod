#!/usr/bin/env python3
from __future__ import annotations
import json
import re
from pathlib import Path

METHOD_RE = re.compile(r'^\\.method [^\\n]+\\n.*?^\\.end method', re.M | re.S)


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
    m = re.search(r'(?m)^    \\.locals (\\d+)\\s*$', block)
    if not m:
        raise RuntimeError("method has no .locals")
    n = int(m.group(1))
    block = block[:m.start(1)] + str(n + extra) + block[m.end(1):]
    return block, n


def patch_player(text):
    m = method(text, " setVideoURI(Landroid/net/Uri;Ljava/util/Map;)V")
    b = m.group(0)
    if ":nova_native_buffer_done" in b:
        return text, "already"

    b, newreg = bump_locals(b, 2)
    scheme = f"v{newreg}"
    tmp = f"v{newreg + 1}"
    loc = re.search(r'(?m)^    \\.locals \\d+\\s*$', b)
    if not loc:
        raise RuntimeError("setVideoURI locals anchor missing")

    inject = f"""
    if-eqz p1, :nova_native_buffer_default
    invoke-virtual {{p1}}, Landroid/net/Uri;->getScheme()Ljava/lang/String;
    move-result-object {scheme}
    if-eqz {scheme}, :nova_native_buffer_default
    const-string {tmp}, "webdav"
    invoke-virtual {{{tmp}, {scheme}}}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result {tmp}
    if-nez {tmp}, :nova_native_buffer_webdav
    const-string {tmp}, "webdavs"
    invoke-virtual {{{tmp}, {scheme}}}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result {tmp}
    if-eqz {tmp}, :nova_native_buffer_default

    :nova_native_buffer_webdav
    const/16 {tmp}, 0x80
    invoke-static {{{tmp}}}, Lcom/archos/medialib/LibAvos;->setStreamBufferSize(I)V
    goto :nova_native_buffer_done

    :nova_native_buffer_default
    const/16 {tmp}, 0x18
    invoke-static {{{tmp}}}, Lcom/archos/medialib/LibAvos;->setStreamBufferSize(I)V

    :nova_native_buffer_done
"""
    b = b[:loc.end()] + inject + b[loc.end():]
    return text[:m.start()] + b + text[m.end():], "applied"


def apply(root: Path, report: Path | None = None):
    player = one(root.glob("smali*/com/archos/mediacenter/video/player/Player.smali"), "Player")
    text, status = patch_player(player.read_text())
    player.write_text(text)

    result = {
        "status": "PASS",
        "player": status,
        "policy": {
            "webdav_native_buffer_mib": 128,
            "default_native_buffer_mib": 24,
            "control": "native aos-avos rebuffer state machine",
            "low_bytes": 25165824,
            "resume_bytes": 47185920,
            "java_prefetch": False,
            "java_pause_resume_guard": False,
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
