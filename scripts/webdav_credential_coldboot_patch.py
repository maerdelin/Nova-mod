#!/usr/bin/env python3
"""Run370 WebDAV credential cold-boot fix; byte-exact and fail-closed.

Makes WebdavUtils.getSardine(Uri) synchronously load SQLite credentials
before its existing getCredential lookup. Leaves player, native libs,
midstream resume and login persistence semantics unchanged.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile
import zlib

BASE_SHA = "b7fb6efade28434496bd443caca7267708fb70f3688f19d5070b1d9791b00840"
PATCHED_SHA = "8d88ebb789e75776654de51583f4394d094da861e0d3253884bab5220a9df5f0"
CODE_OFF = 4980816
INSNS_OFF = CODE_OFF + 16


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patch_dex(original: bytes) -> bytes:
    # The raw-10X branch intentionally changes an unrelated Player constant in
    # classes.dex. Do not key this credential fix to the whole-DEX hash.
    # Fail closed on the exact target method layout/instructions instead.
    if len(original) <= INSNS_OFF + 512:
        raise RuntimeError("classes.dex is too small for reviewed credential target")
    b = bytearray(original)
    regs, ins, outs, tries, debug, size = struct.unpack_from("<HHHHII", b, CODE_OFF)
    if (regs, ins, tries, size) != (13, 2, 2, 256):
        raise RuntimeError("Unexpected WebdavUtils.getSardine method layout")

    def words(pc: int, n: int = 1) -> list[int]:
        return list(struct.unpack_from("<" + "H" * n, b, INSNS_OFF + 2 * pc))

    def put(pc: int, values: list[int]) -> None:
        struct.pack_into("<" + "H" * len(values), b, INSNS_OFF + 2 * pc, *values)

    if words(1, 3) != [0x0071, 12993, 0] or words(4) != [0x000c]:
        raise RuntimeError("Credential getter changed")
    if words(70, 2) != [0x0038, 43] or words(72)[0] & 0xff != 0x22:
        raise RuntimeError("Expected trace-only region changed")

    # Branch from original method entry into trace-only code space.
    put(1, [0x002a, 71, 0])  # goto/32 -> pc72
    put(4, [0])
    put(70, [0x0029, 43])  # skip old trace region -> pc113
    # Load saved credentials before the existing getCredential(path).
    put(72, [
        0x0071, 12993, 0x0000,    # NetworkCredentialsDatabase.getInstance()
        0x000c,                   # move-result-object v0
        0x0071, 13714, 0x0000,    # WebdavUtils.getContext()
        0x010c,                   # move-result-object v1
        0x0138, 8,                # if-eqz v1 -> pc88
        0x206e, 12994, 0x0010,   # v0.loadCredentials(v1)
        0x002a, 0xffb0, 0xffff,   # goto/32 -> pc5
        0x002a, 0xffad, 0xffff,   # null context: goto/32 -> pc5
    ])
    put(91, [0] * 22)
    b[12:32] = hashlib.sha1(b[32:]).digest()
    b[8:12] = struct.pack("<I", zlib.adler32(b[12:]) & 0xffffffff)
    patched = bytes(b)
    if len(patched) != len(original):
        raise RuntimeError("Credential patch unexpectedly changed DEX length")
    # Re-check the exact local control-flow edits. Unrelated same-size changes
    # elsewhere in the DEX are allowed on this feature branch.
    if words(1, 3) != [0x002a, 71, 0] or words(70, 2) != [0x0029, 43]:
        raise RuntimeError("Credential patch postcondition failed")
    return patched


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("source", type=Path, help="Cloud-built granular-UNSIGNED.apk")
    p.add_argument("destination", type=Path, help="APK to feed into zipalign/apksigner")
    p.add_argument("--report", required=True, type=Path)
    args = p.parse_args()
    if args.source.resolve() == args.destination.resolve():
        raise RuntimeError("Source and destination must differ")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.source) as src:
        if src.testzip() is not None or src.namelist().count("classes.dex") != 1:
            raise RuntimeError("Invalid original unsigned APK")
        original_dex = src.read("classes.dex")
        input_dex_sha256 = sha256(original_dex)
        patched_dex = patch_dex(original_dex)
        original_names = src.namelist()
        with zipfile.ZipFile(args.destination, "w", allowZip64=True) as dst:
            dst.comment = src.comment
            for info in src.infolist():
                data = patched_dex if info.filename == "classes.dex" else src.read(info.filename)
                dst.writestr(info, data)

    with zipfile.ZipFile(args.source) as src, zipfile.ZipFile(args.destination) as dst:
        if dst.testzip() is not None or dst.namelist() != original_names:
            raise RuntimeError("Patched APK ZIP validation failed")
        changed = [n for n in original_names if src.read(n) != dst.read(n)]
        if changed != ["classes.dex"]:
            raise RuntimeError("Unexpected payload changes: " + str(changed))
    report = {
        "status": "PASS",
        "baseline": "Run370 target method layout/instructions; unrelated DEX bytes may differ",
        "changes": ["classes.dex: WebdavUtils.getSardine credentials DB cold load"],
        "preserved": "native libraries, AVOS, raw buffering and WebDAV midstream reconnect",
        "input_classes_dex_sha256": input_dex_sha256,
        "patched_classes_dex_sha256": sha256(patched_dex),
        "sqlite_write_logic_changed": False,
        "device_cold_boot_tested": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
