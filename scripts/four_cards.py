#!/usr/bin/env python3
"""Surgical 14TV V7.14 home fix: never add the fifth Non-Scraped Videos card.

Takes ONLY the byte-for-byte authenticated 14TV V7.14 reference APK. Changes
only the two bytes of the existing if-lez decision in MainFragment.updateNonScrapedVideosVisibility to an unconditional goto/16 with the same target (the original remove-card code path),
recomputes DEX header SHA-1 and Adler-32, and repacks an UNSIGNED APK for
fresh Android signing. All other DEX instruction bytes, APK entry payloads,
resources and network/storage behaviors are preserved.

The patched APK cannot reuse the original test APK v2 signing block. CI MUST
zipalign, re-sign and apksigner-verify before uploading any installable APK.
"""
from __future__ import annotations
import argparse
import hashlib
import io
from pathlib import Path
import struct
import zipfile
import zlib

REFERENCE_APK_SHA256 = 'c9977d28e57b6a58e2f4d09da959a1b41db2028020d3175facfe792e108e77ff'
REFERENCE_APK_BYTES = 29767890
REFERENCE_DEX_SHA256 = '8e29be5b361d21256f7c32e33b35d9ddfe3916454713762573440f3043da4a3d'
METHOD_ID = 19531
METHOD_NAME = 'updateNonScrapedVideosVisibility'
METHOD_CLASS = 'Lcom/archos/mediacenter/video/leanback/MainFragment;'
CODE_ITEM_OFFSET = 4139156
INSTRUCTION_OFFSET = CODE_ITEM_OFFSET + 16
EXPECTED_CODE_HEADER = (7, 2, 4, 0, 97)
EXPECTED_INSTRUCTIONS_PREFIX = bytes.fromhex('7110db4706000a065450f95e54510a5f')
BRANCH_CODE_UNIT = 36
EXPECTED_IF_LEZ = bytes.fromhex('3d 06 29 00')  # if-lez v6, +41 code units
HIDE_BY_GOTO = bytes.fromhex('29 00 29 00')    # goto/16 +41, targets the same existing removal block
REMOVE_BLOCK_UNIT = 77
REMOVE_BLOCK_PREFIX = bytes.fromhex('72 10 7e db 01 00')  # original logger call at start of removal block


def h256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def verify_method_identity(data: bytes) -> None:
    """Bind the pinned code offset to the actual DEX class/method ID."""
    string_count, string_off = struct.unpack_from('<II', data, 56)
    type_count, type_off = struct.unpack_from('<II', data, 64)
    method_count, method_off = struct.unpack_from('<II', data, 88)
    assert method_count > METHOD_ID and string_count > 0 and type_count > 0
    class_idx, _, name_idx = struct.unpack_from('<HHI', data, method_off + METHOD_ID * 8)

    def str_value(idx: int) -> str:
        assert idx < string_count
        offset = struct.unpack_from('<I', data, string_off + idx * 4)[0]
        # DEX starts with ULEB128 UTF-16 length, followed by a NUL-terminated MUTF8 string
        for _ in range(5):
            byte = data[offset]
            offset += 1
            if byte < 128:
                break
        end = data.index(b'\0', offset)
        return data[offset:end].decode('utf-8')

    assert str_value(name_idx) == METHOD_NAME
    assert class_idx < type_count
    class_string = struct.unpack_from('<I', data, type_off + class_idx * 4)[0]
    assert str_value(class_string) == METHOD_CLASS


def patch_dex(dex: bytes) -> bytes:
    assert h256(dex) == REFERENCE_DEX_SHA256, 'Wrong V7.14 DEX; REFUSE TO PATCH'
    assert dex[:8] == b'dex\n035\0'
    verify_method_identity(dex)
    reg,ins,outs,tries,_,units = struct.unpack_from('<4H2I',dex,CODE_ITEM_OFFSET)
    assert (reg,ins,outs,tries,units) == EXPECTED_CODE_HEADER
    assert dex[INSTRUCTION_OFFSET:INSTRUCTION_OFFSET + len(EXPECTED_INSTRUCTIONS_PREFIX)] == EXPECTED_INSTRUCTIONS_PREFIX

    fixed = bytearray(dex)
    branch_at = INSTRUCTION_OFFSET + BRANCH_CODE_UNIT * 2
    remove_at = INSTRUCTION_OFFSET + REMOVE_BLOCK_UNIT * 2
    assert dex[branch_at:branch_at+4] == EXPECTED_IF_LEZ, 'Unexpected original non-scraped count branch'
    assert BRANCH_CODE_UNIT + struct.unpack('<h', EXPECTED_IF_LEZ[2:4])[0] == REMOVE_BLOCK_UNIT
    assert dex[remove_at:remove_at+len(REMOVE_BLOCK_PREFIX)] == REMOVE_BLOCK_PREFIX, 'Removal target has changed'
    fixed[branch_at:branch_at+4] = HIDE_BY_GOTO
    fixed[12:32] = hashlib.sha1(fixed[32:]).digest()
    struct.pack_into('<I', fixed, 8, zlib.adler32(fixed[12:]) & 0xffffffff)
    result = bytes(fixed)
    assert result[branch_at:branch_at + 4] == HIDE_BY_GOTO
    # All other method/DEX data is byte-identical to V7.14.
    assert result[32:branch_at] == dex[32:branch_at]
    assert result[branch_at+4:] == dex[branch_at+4:]
    assert hashlib.sha1(result[32:]).digest() == result[12:32]
    assert zlib.adler32(result[12:]) & 0xffffffff == struct.unpack_from('<I',result,8)[0]
    return result


def rebuild_unsigned(reference:Path, output:Path) -> None:
    blob=reference.read_bytes()
    assert len(blob)==REFERENCE_APK_BYTES and h256(blob)==REFERENCE_APK_SHA256, 'Wrong 14TV-tested V7.14 reference APK'
    with zipfile.ZipFile(io.BytesIO(blob)) as original:
        names=original.namelist()
        assert len(names)==1937 and len(names)==len(set(names))
        output.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(output,'w',allowZip64=False) as target:
            for item in original.infolist():
                contents=original.read(item.filename)
                if item.filename=='classes.dex':
                    contents=patch_dex(contents)
                info=zipfile.ZipInfo(item.filename,item.date_time)
                info.compress_type=item.compress_type
                info.external_attr=item.external_attr
                info.create_system=item.create_system
                info.flag_bits=item.flag_bits
                info.comment=item.comment
                target.writestr(info, contents, compress_type=info.compress_type, compresslevel=6)
    with zipfile.ZipFile(output) as test,zipfile.ZipFile(io.BytesIO(blob)) as ref:
        assert test.namelist()==ref.namelist()
        assert test.testzip() is None
        for name in names:
            if name!='classes.dex':
                assert test.read(name)==ref.read(name),f'Unexpected change to {name}'
        assert test.read('classes.dex')==patch_dex(ref.read('classes.dex'))
    print('PASS: original V7.14 contents retained; only MainFragment non-scraped card's conditional switches to the pre-existing removal branch')
    print('PASS: count check, adapter setup, and existing remove-card method are preserved')
    print('UNSIGNED OUTPUT:',output,'bytes=',output.stat().st_size,'sha256=',h256(output.read_bytes()))


def main()->None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('tested_v714_apk',type=Path)
    p.add_argument('unsigned_output_apk',type=Path)
    args=p.parse_args()
    rebuild_unsigned(args.tested_v714_apk,args.unsigned_output_apk)

if __name__=='__main__':main()
