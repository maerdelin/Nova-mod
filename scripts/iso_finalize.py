#!/usr/bin/env python3
"""Append ISO-only patches *after* Run377 hash-locked WebDAV DEX patch.

Input is the verified Run377 credential-UNSIGNED.apk. The older ISO smali
feature changes classes.dex, so the WebDAV in-place DEX fix MUST happen before
ISO smali assembly. Verify coldboot fix before and after, APK roundtrip, and
exact scope for native payloads. Never replace old classes/modules.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import granular as g
import iso_patch
import webdav_safety_patch
import iso_seek_ui_patch
import main_transport_audit

ABIS = ("arm64-v8a", "armeabi-v7a", "x86", "x86_64")
WEBDAV_UTILS = "Lcom/archos/filecorelibrary/webdav/WebdavUtils;"
EXPECTED_ISO = {f"lib/{abi}/libnova_iso.so" for abi in ABIS}


def verify_credential(root: Path) -> None:
    """Ensure patched WebdavUtils.getSardine still reloads saved DB credentials."""
    classes = g.class_index(root)
    if WEBDAV_UTILS not in classes:
        raise g.Conflict("Missing WebdavUtils in decoded candidate")
    text = classes[WEBDAV_UTILS].read_text()
    import re
    methods = re.findall(r"(?ms)^\.method [^\n]*\bgetSardine\(Landroid/net/Uri;\)[^\n]*\n.*?^\.end method$", text)
    if len(methods) != 1:
        raise g.Conflict(f"Expected one WebdavUtils.getSardine Uri method, got {len(methods)}")
    body = methods[0]
    required = ["NetworkCredentialsDatabase;->getInstance(", "WebdavUtils;->getContext(", "->loadCredentials(", "->getCredential("]
    missing = [token for token in required if token not in body]
    if missing:
        raise g.Conflict("WebDAV coldboot credential instructions missing: " + repr(missing))


def verify_native_delta(before: Path, after: Path) -> None:
    with zipfile.ZipFile(before) as a, zipfile.ZipFile(after) as b:
        if b.testzip() is not None or len(b.namelist()) != len(set(b.namelist())):
            raise g.Conflict("Invalid ISO APK ZIP")
        prior = set(a.namelist())
        result = set(b.namelist())
        untouched = {n for n in prior if n.startswith(("lib/", "assets/")) and not n.endswith("/")}
        altered = {n for n in untouched if n not in result or a.read(n) != b.read(n)}
        if altered:
            raise g.Conflict("ISO assembly changed existing native library or asset: " + repr(sorted(altered)[:6]))
        additions = {n for n in result - prior if n.startswith(("lib/", "assets/")) and not n.endswith("/")}
        if additions != EXPECTED_ISO:
            raise g.Conflict("Expected exactly four new ISO bridge libraries, got " + repr(sorted(additions)))
        for name in EXPECTED_ISO:
            val = b.read(name)
            if len(val) < 10000 or not val.startswith(b"\x7fELF"):
                raise g.Conflict("Invalid native ISO ELF: " + name)
        if b.getinfo("resources.arsc").compress_type != zipfile.ZIP_STORED:
            raise g.Conflict("ISO APK resources.arsc is not stored uncompressed")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--apktool", type=Path, required=True)
    p.add_argument("--iso-native-root", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--reports", type=Path, required=True)
    args = p.parse_args()

    args.work.mkdir(parents=True, exist_ok=True)
    args.reports.mkdir(parents=True, exist_ok=True)
    decoded = args.work / "iso-candidate"
    assembled = args.work / "iso-roundtrip"
    subprocess.run(["java", "-Xmx4g", "-jar", str(args.apktool), "d", "--no-debug-info",
                    "-f", str(args.source), "-o", str(decoded)], check=True)
    verify_credential(decoded)
    transport = main_transport_audit.capture(decoded)
    main_transport_audit.verify_source_baseline()
    result = iso_patch.apply(decoded, args.iso_native_root, args.reports / "blu-ray-iso.json")
    safety = webdav_safety_patch.apply(decoded, args.reports / "webdav-safety.json")
    ui = iso_seek_ui_patch.apply(decoded, args.reports / "iso-seek-ui.json")
    main_transport_audit.verify(decoded, transport, args.reports / "main-transport.json")
    verify_credential(decoded)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["java", "-Xmx4g", "-jar", str(args.apktool), "b", str(decoded),
                    "-o", str(args.output)], check=True)
    subprocess.run(["java", "-Xmx4g", "-jar", str(args.apktool), "d", "--no-debug-info",
                    "-f", str(args.output), "-o", str(assembled)], check=True)
    verify_credential(assembled)
    main_transport_audit.verify(assembled, transport, args.reports / "main-transport-roundtrip.json")
    g.verify(decoded, assembled, args.reports / "iso-roundtrip.json")
    verify_native_delta(args.source, args.output)
    report = {
        "status": "PASS",
        "ISO": result,
        "main_transport": "main copy methods retained without replacement",
        "preserved_safety": safety,
        "preserved_ui": ui,
        "coldboot_webdav_credential_instructions": "present before and after ISO assembly",
        "existing_native_and_asset_payload": "byte-for-byte preserved, including patched AVOS",
        "new_native_payload": sorted(EXPECTED_ISO),
        "whole_old_dex_replacements": 0,
        "android_device_iso_tested": False,
    }
    (args.reports / "iso-integration.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
