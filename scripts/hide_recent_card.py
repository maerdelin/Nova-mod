#!/usr/bin/env python3
"""Hide only the Recent Plays home tile in the pinned V7.14 ARM32 four-card APK.
This does not modify Rows Fragment, WebDAV/SMB, network shortcuts, or the
previous non-scraped-card removal branch. Re-sign the output before installing.
"""
import hashlib
import struct
import sys
import zipfile
import zlib
from pathlib import Path

SOURCE_DEX_SHA = "f7b4d15c3f5930e7a4bac04a51245616b0f633199b50eb5fa94e65c3512568df"
CODE_ITEM = 4128208
TARGET = CODE_ITEM + 16 + 2 * 784
ORIGINAL_ADD = bytes.fromhex("6e 20 75 e9 21 00")
BEFORE = struct.pack("<15H", 0x0222,0x0af5,0x0462,0x5f80,0x0560,
    0x4394,0x206e,0x17f3,0x005b,0x050c,0x0660,0x34ad,
    0x4070,0x4cd7,0x6542)
AFTER = bytes.fromhex("54 b1 f9 5e 22 02 f5 0a 62 04 78 5f")
def sha(b):
    return hashlib.sha256(b).hexdigest()

def dex_patch(d):
    if sha(d) != SOURCE_DEX_SHA:
        raise ValueError("Wrong V7.14 four-card base DEX")
    if struct.unpack_from("<4H2I", d, CODE_ITEM)[:4] != (12,1,7,0):
        raise ValueError("loadRows header mismatch")
    if struct.unpack_from("<I",d,CODE_ITEM+12)[0] != 1096:
        raise ValueError("loadRows code size mismatch")
    if d[TARGET-len(BEFORE):TARGET] != BEFORE:
        raise ValueError("Recent Plays Box construction mismatch")
    if d[TARGET:TARGET+6] != ORIGINAL_ADD or d[TARGET+6:TARGET+18] != AFTER:
        raise ValueError("Recent Plays add() or next NETWORK Box mismatched")
    out=bytearray(d)
    out[TARGET:TARGET+6]=b"\x00"*6
    out[12:32]=hashlib.sha1(out[32:]).digest()
    struct.pack_into("<I",out,8,zlib.adler32(out[12:]) & 0xffffffff)
    result=bytes(out)
    if result[32:TARGET]!=d[32:TARGET] or result[TARGET+6:]!=d[TARGET+6:]:
        raise ValueError("Changes outside exact 6-byte invoke")
    if hashlib.sha1(result[32:]).digest()!=result[12:32]:
        raise ValueError("DEX checksum invalid")
    return result

def signer_metadata(n):
    n=n.upper()
    return n=="META-INF/MANIFEST.MF" or (n.startswith("META-INF/") and n.endswith((".SF",".RSA",".DSA",".EC")))

def verify(source,candidate):
    with zipfile.ZipFile(source) as a,zipfile.ZipFile(candidate) as b:
        if a.testzip() or b.testzip():
            raise ValueError("Corrupt APK ZIP")
        original={n for n in a.namelist() if not signer_metadata(n)}
        newer={n for n in b.namelist() if not signer_metadata(n)}
        if original!=newer:
            raise ValueError("Unexpected APK entries")
        if b.read("classes.dex")!=dex_patch(a.read("classes.dex")):
            raise ValueError("DEX differs from precise hide-only patch")
        for n in original-{"classes.dex"}:
            if a.read(n)!=b.read(n):
                raise ValueError("Modified baseline file "+n)
    print("PASS: only Recent Plays Box add call replaced by 3 NOPs; other assets unchanged")

def build(source,candidate):
    candidate.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(source) as a,zipfile.ZipFile(candidate,"w",allowZip64=False) as b:
        if a.testzip():
            raise ValueError("Corrupt source APK")
        for item in a.infolist():
            if signer_metadata(item.filename):
                continue
            data=a.read(item.filename)
            if item.filename=="classes.dex":
                data=dex_patch(data)
            info=zipfile.ZipInfo(item.filename,item.date_time)
            info.compress_type=item.compress_type
            info.external_attr=item.external_attr
            info.create_system=item.create_system
            info.flag_bits=item.flag_bits
            info.comment=item.comment
            b.writestr(info,data,compress_type=info.compress_type,compresslevel=6)
    verify(source,candidate)
    print("UNSIGNED candidate sha256",sha(candidate.read_bytes()))

if __name__=="__main__":
    if len(sys.argv)!=4 or sys.argv[1] not in ("build","verify"):
        raise SystemExit("Usage: hide_recent_card.py build|verify fourcard.apk threecard.apk")
    src,dst=Path(sys.argv[2]),Path(sys.argv[3])
    (build if sys.argv[1]=="build" else verify)(src,dst)
