#!/usr/bin/env python3
"""Reject Java and Logback diagnostic paths which bypass NOVA's single shared gate.

Run this against the FINAL, fully patched apktool smali tree, not source scripts.
"""
import argparse
import re
from pathlib import Path


def audit(root: Path):
    paths = list(root.glob("smali*/**/*.smali"))
    if not paths:
        raise RuntimeError("No smali sources in assembled APK")
    gates = [p for p in paths if p.name == "NovaGlobalLogs.smali"]
    if len(gates) != 1:
        raise RuntimeError(f"Expected one native-aware Java gate, found {len(gates)}")
    body = gates[0].read_text()
    if 'ON_AFTER_APPLY' not in body:
        raise RuntimeError("Real device Java logcat ON probe missing")
    if '.method public static enabled()Z' not in body:
        raise RuntimeError("Shared-byte Java enabled() method missing")
    if 'NovaGlobalLogs;->i(Ljava/lang/String;Ljava/lang/String;)I' not in body:
        raise RuntimeError("Device logcat probe bypasses the real Java log wrapper")
    if 'MappedByteBuffer;->get(I)B' not in body or 'MappedByteBuffer;->put(IB)' not in body:
        raise RuntimeError("Java shared mapped-byte read/write missing")

    direct = []
    for path in paths:
        text = path.read_text(errors="replace")
        if path == gates[0]:
            continue
        for match in re.finditer(r'Landroid/util/Log;->([A-Za-z_0-9]+)\(', text):
            if match.group(1) == "getStackTraceString":
                continue  # Not a log output; must preserve its exception-formatting semantics.
            direct.append(f"{path.relative_to(root)}:{match.group(1)}")
    if direct:
        raise RuntimeError("Ungated Java Android Log callsites: " + ", ".join(direct[:20]))

    logger = [p for p in paths if p.as_posix().endswith("ch/qos/logback/classic/Logger.smali")]
    if len(logger) != 1:
        raise RuntimeError(f"Expected one Logback Logger class, found {len(logger)}")
    covered = logger[0].read_text().count("NovaGlobalLogs;->enabled()Z")
    if covered < 18:
        raise RuntimeError(f"Logback diagnostic writer guard coverage insufficient: {covered}")
    prefs = root / "res/xml/preferences_video.xml"
    if not prefs.exists() or 'android:key="nova_logs_enabled"' not in prefs.read_text():
        raise RuntimeError("Real Logs preference missing")
    print(f"NOVA_GLOBAL_LOGS_FULL_JAVA_LOGBACK_AUDIT=PASS smali={len(paths)} logbackGuards={covered}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apktool-root", type=Path, required=True)
    audit(parser.parse_args().apktool_root)


if __name__ == "__main__":
    main()
