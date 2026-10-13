#!/usr/bin/env python3
"""Reproduce the exact 14TV-tested V7.14 Rows Fragment patch on V7.13.

Only the original, SHA-pinned V7.13 APK is accepted. Produces an UNSIGNED APK.
Sign with the original private certificate, never with a randomly generated key.
"""
import argparse
import hashlib
from pathlib import Path
import struct
import zlib
from zipfile import ZipFile, ZipInfo, ZIP_STORED

BASE_SHA256 = "2ec3db435d35c2daf245dec9198e5adcfdfab1adc2e52a224fd60d854520e044"
TESTED_V714_SHA256 = "c9977d28e57b6a58e2f4d09da959a1b41db2028020d3175facfe792e108e77ff"
OLD = bytes.fromhex("07 35 28 18 38 05 5b 00")
NEW = bytes.fromhex("07 35 28 18 38 05 fe ff")


def patch(source: Path, output: Path) -> None:
    if hashlib.sha256(source.read_bytes()).hexdigest() != BASE_SHA256:
        raise ValueError("Unexpected input: V7.14 patch requires exact V7.13 base APK")
    with ZipFile(source) as src:
        old_dex = src.read("classes.dex")
        if old_dex.count(OLD) != 1:
            raise ValueError("Expected exactly one Leanback null-adapter branch")
        dex = bytearray(old_dex.replace(OLD, NEW))
        dex[12:32] = hashlib.sha1(dex[32:]).digest()
        struct.pack_into("<I", dex, 8, zlib.adler32(dex[12:]) & 0xffffffff)
        with ZipFile(output, "w", allowZip64=False) as dst:
            dst.comment = src.comment
            for entry in src.infolist():
                name = entry.filename
                if name.startswith("META-INF/") and name.upper().endswith((".SF", ".RSA", ".DSA", ".EC", ".MF")):
                    continue
                content = bytes(dex) if name == "classes.dex" else src.read(name)
                item = ZipInfo(name, entry.date_time)
                item.compress_type = entry.compress_type
                item.external_attr = entry.external_attr
                item.internal_attr = entry.internal_attr
                item.create_system = entry.create_system
                item.comment = entry.comment
                item.flag_bits = entry.flag_bits & ~0x08
                if item.compress_type == ZIP_STORED:
                    offset = dst.fp.tell() + 30 + len(name.encode("utf-8"))
                    pad = (-offset - 4) % 4
                    item.extra = struct.pack("<HH", 0xfffe, pad) + b"\x00" * pad
                dst.writestr(item, content, compresslevel=6)
    with ZipFile(output) as dst:
        if dst.testzip() is not None:
            raise AssertionError("ZIP CRC check failed")
    print("V7.14 Rows Fragment patch verified. UNSIGNED APK:", output)
    print("SHA-256 of user-tested signed V7.14 APK:", TESTED_V714_SHA256)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("v713_apk", type=Path)
    parser.add_argument("unsigned_output", type=Path)
    args = parser.parse_args()
    patch(args.v713_apk, args.unsigned_output)
