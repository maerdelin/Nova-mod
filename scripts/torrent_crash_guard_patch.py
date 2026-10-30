#!/usr/bin/env python3
"""Protect torrent stdout parsing, without filtering torrents or touching Seek.

The stock observer parses daemon status fields 4 and 5 as decimal longs without
validating them. For malformed data, terminate ONLY this torrent session by
reusing exitProcess(), rather than killing the Android app (RUN964 log).
"""
import argparse
from pathlib import Path
import re

MARKER = "NOVA_TORRENT_STDOUT_CRASH_GUARD_V1"
METHOD_RE = re.compile(r"(?ms)^\.method[^\n]*\bobserveStdout\(\)V[^\n]*\n.*?^\.end method[ \t]*$")
LONG_RE = re.compile(r"(?m)^[ \t]*invoke-static(?:/range)?\s+\{[^}\n]+\},\s*Ljava/lang/Long;->parseLong\(Ljava/lang/String;\)J[ \t]*$")
LABEL_RE = re.compile(r"(?m)^[ \t]*(?P<label>:[A-Za-z0-9_$]+)[ \t]*(?:#.*)?$")
IO_RE = re.compile(r"(?m)^(?P<indent>[ \t]*)\.catch\s+Ljava/io/IOException;\s+\{\s*(?P<a>:[A-Za-z0-9_$]+)\s*\.\.\s*(?P<b>:[A-Za-z0-9_$]+)\s*\}\s+(?P<target>:[A-Za-z0-9_$]+)[ \t]*$")
EXCEPTIONS = ("Ljava/lang/NumberFormatException;", "Ljava/lang/ArrayIndexOutOfBoundsException;")
HANDLER = r"""
    # NOVA_TORRENT_STDOUT_CRASH_GUARD_V1
:nova_torrent_bad_stdout
    move-exception v0
    const-string v1, "NOVA_TORRENT_GUARD"
    const-string v2, "Malformed torrent status; closing torrent session"
    invoke-static {v1, v2, v0}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I
    invoke-virtual {p0}, Lcom/archos/mediacenter/video/browser/TorrentObserverService;->exitProcess()V
    return-void
"""


def patch_torrent_observer(source: str) -> str:
    if MARKER in source:
        raise RuntimeError("Torrent guard already installed")
    if not re.search(r"(?m)^\.method[^\n]*\bexitProcess\(\)V[ \t]*$", source):
        raise RuntimeError("Torrent cleanup method exitProcess() missing")
    found = list(METHOD_RE.finditer(source))
    if len(found) != 1:
        raise RuntimeError(f"observeStdout()V count is {len(found)}, expected one")
    original = found[0].group()
    reg = re.search(r"(?m)^[ \t]*\.(?:locals|registers)\s+(\d+)[ \t]*$", original)
    if not reg or int(reg.group(1)) < 4:
        raise RuntimeError("Insufficient observer registers for safe handler")
    longs = list(LONG_RE.finditer(original))
    if len(longs) != 2:
        raise RuntimeError(f"Expected two size parseLong calls, found {len(longs)}")
    labels = {m.group("label"): m.start() for m in LABEL_RE.finditer(original)}
    patches, covered = [], set()
    for m in IO_RE.finditer(original):
        lo, hi = labels.get(m.group("a")), labels.get(m.group("b"))
        if lo is None or hi is None or lo >= hi:
            raise RuntimeError("Unknown or reversed try range labels")
        inside = [i for i, call in enumerate(longs) if lo < call.start() < hi]
        if inside:
            covered.update(inside)
            patches.append(m)
    if covered != {0, 1}:
        raise RuntimeError("Size parsing is not covered by an existing IOException try span")
    output = original
    for m in reversed(patches):
        catch = m.group(0)
        extra = "".join("\n" + m.group("indent") + ".catch " + exc +
                        " {" + m.group("a") + " .. " + m.group("b") +
                        "} :nova_torrent_bad_stdout" for exc in EXCEPTIONS)
        output = output[:m.start()] + catch + extra + output[m.end():]
    at = output.rfind(".end method")
    output = output[:at] + HANDLER + output[at:]
    if output.count(MARKER) != 1:
        raise RuntimeError("Guard marker not unique")
    return source[:found[0].start()] + output + source[found[0].end():]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("smali", type=Path)
    args = p.parse_args()
    args.smali.write_text(patch_torrent_observer(args.smali.read_text()))
    print(MARKER + "=PASS")
