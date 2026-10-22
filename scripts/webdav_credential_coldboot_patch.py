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

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_uleb(data: bytes | bytearray, off: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for _ in range(5):
        if off >= len(data):
            raise RuntimeError("DEX ULEB128 out of range")
        b = data[off]
        off += 1
        value |= (b & 0x7f) << shift
        if not (b & 0x80):
            return value, off
        shift += 7
    raise RuntimeError("DEX ULEB128 too long")


def dex_strings(data: bytes | bytearray) -> list[str]:
    size, off = struct.unpack_from("<II", data, 0x38)
    out: list[str] = []
    for i in range(size):
        (s_off,) = struct.unpack_from("<I", data, off + 4 * i)
        _, p = read_uleb(data, s_off)
        end = data.find(b"\0", p)
        if end < 0:
            raise RuntimeError("Unterminated DEX string")
        out.append(bytes(data[p:end]).decode("utf-8", errors="replace"))
    return out


def dex_types(data: bytes | bytearray, strings: list[str]) -> list[str]:
    size, off = struct.unpack_from("<II", data, 0x40)
    out = []
    for i in range(size):
        (string_idx,) = struct.unpack_from("<I", data, off + 4 * i)
        out.append(strings[string_idx])
    return out


def dex_methods(data: bytes | bytearray, strings: list[str], types: list[str]):
    size, off = struct.unpack_from("<II", data, 0x58)
    out = []
    for i in range(size):
        class_idx, proto_idx, name_idx = struct.unpack_from("<HHI", data, off + 8 * i)
        out.append({
            "class": types[class_idx],
            "proto_idx": proto_idx,
            "name": strings[name_idx],
        })
    return out


def find_method_idx(methods, class_suffix: str, name: str) -> int:
    hits = [
        i for i, m in enumerate(methods)
        if m["class"].endswith(class_suffix) and m["name"] == name
    ]
    if len(hits) != 1:
        raise RuntimeError(
            f"Expected one {class_suffix}.{name}, found {len(hits)}"
        )
    return hits[0]


def iter_class_methods(data: bytes | bytearray, methods, types, class_suffix: str):
    class_count, class_off = struct.unpack_from("<II", data, 0x60)
    matching_class_data = []
    for i in range(class_count):
        fields = struct.unpack_from("<IIIIIIII", data, class_off + 32 * i)
        class_idx, class_data_off = fields[0], fields[6]
        if types[class_idx].endswith(class_suffix):
            matching_class_data.append(class_data_off)
    if len(matching_class_data) != 1 or matching_class_data[0] == 0:
        raise RuntimeError(
            f"Expected one concrete class {class_suffix}, found {len(matching_class_data)}"
        )

    p = matching_class_data[0]
    static_fields, p = read_uleb(data, p)
    instance_fields, p = read_uleb(data, p)
    direct_methods, p = read_uleb(data, p)
    virtual_methods, p = read_uleb(data, p)

    for _ in range(static_fields + instance_fields):
        _, p = read_uleb(data, p)
        _, p = read_uleb(data, p)

    for count in (direct_methods, virtual_methods):
        method_idx = 0
        for _ in range(count):
            diff, p = read_uleb(data, p)
            _, p = read_uleb(data, p)  # access_flags
            code_off, p = read_uleb(data, p)
            method_idx += diff
            yield method_idx, code_off


def find_target_code_off(
    data: bytes | bytearray, methods, types
) -> tuple[int, int]:
    candidates = []
    for method_idx, code_off in iter_class_methods(
        data, methods, types, "/WebdavUtils;"
    ):
        if methods[method_idx]["name"] != "getSardine" or not code_off:
            continue
        if code_off + 16 > len(data):
            continue
        regs, ins, outs, tries, debug, size = struct.unpack_from(
            "<HHHHII", data, code_off
        )
        if (regs, ins, tries, size) == (13, 2, 2, 256):
            candidates.append((method_idx, code_off))
    if len(candidates) != 1:
        raise RuntimeError(
            f"Expected one reviewed WebdavUtils.getSardine code item, found {len(candidates)}"
        )
    return candidates[0]


def patch_dex(original: bytes) -> bytes:
    # Locate the reviewed method structurally. Unrelated smali additions may
    # move code_items and reorder method_ids, but they may not weaken this
    # target-method shape check.
    b = bytearray(original)
    strings = dex_strings(b)
    types = dex_types(b, strings)
    methods = dex_methods(b, strings, types)
    target_method_idx, code_off = find_target_code_off(b, methods, types)
    insns_off = code_off + 16

    regs, ins, outs, tries, debug, size = struct.unpack_from("<HHHHII", b, code_off)
    if (regs, ins, tries, size) != (13, 2, 2, 256):
        raise RuntimeError("Unexpected WebdavUtils.getSardine method layout")

    db_get_instance = find_method_idx(
        methods, "/NetworkCredentialsDatabase;", "getInstance"
    )
    webdav_get_context = find_method_idx(
        methods, "/WebdavUtils;", "getContext"
    )
    db_load_credentials = find_method_idx(
        methods, "/NetworkCredentialsDatabase;", "loadCredentials"
    )

    def words(pc: int, n: int = 1) -> list[int]:
        return list(struct.unpack_from(
            "<" + "H" * n, b, insns_off + 2 * pc
        ))

    def put(pc: int, values: list[int]) -> None:
        struct.pack_into(
            "<" + "H" * len(values), b, insns_off + 2 * pc, *values
        )

    entry = words(1, 3)
    if entry[0] != 0x0071 or entry[1] != db_get_instance or entry[2] != 0:
        raise RuntimeError(
            "Credential getter changed or method-id resolution mismatch"
        )
    if words(4) != [0x000c]:
        raise RuntimeError("Credential getter move-result changed")
    if words(70, 2) != [0x0038, 43] or words(72)[0] & 0xff != 0x22:
        raise RuntimeError("Expected trace-only region changed")

    # Branch from original method entry into trace-only code space.
    put(1, [0x002a, 71, 0])  # goto/32 -> pc72
    put(4, [0])
    put(70, [0x0029, 43])  # skip old trace region -> pc113

    # Load saved credentials before the existing getCredential(path).
    # Method ids are resolved from this exact DEX, never hard-coded.
    put(72, [
        0x0071, db_get_instance, 0x0000,
        0x000c,
        0x0071, webdav_get_context, 0x0000,
        0x010c,
        0x0138, 8,
        0x206e, db_load_credentials, 0x0010,
        0x002a, 0xffb0, 0xffff,
        0x002a, 0xffad, 0xffff,
    ])
    put(91, [0] * 22)

    b[12:32] = hashlib.sha1(b[32:]).digest()
    b[8:12] = struct.pack("<I", zlib.adler32(b[12:]) & 0xffffffff)
    patched = bytes(b)

    if len(patched) != len(original):
        raise RuntimeError("Credential patch unexpectedly changed DEX length")
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
        "baseline": "Structurally located WebdavUtils.getSardine reviewed method shape; unrelated DEX offsets/method-id ordering may differ",
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
