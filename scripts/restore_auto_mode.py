#!/usr/bin/env python3
"""Restore the *original* Nova 6.5.5 automatic TV/tablet UI selector.

Only UiChoiceDialog.applicationIsInLeanbackMode(Context)Z is modified. All
115 code units below match the original Nova 6.5.5 APK and R16 baseline.
This is a pinned binary edit; it is NOT a runtime/emulator test.
"""
import base64
import hashlib
import struct
import zlib

INPUT_DEX_SHA = '8f4c363d26747747644faf46b6eb3e7eb6fa373fdbb975c8c4fc0fd483f92a1a'
OUTPUT_DEX_SHA = 'be158200a3070bf13f31f7bbc4c7a1ed667e42a8b221a6e027ebd0122f5ce636'
SOURCE_METHOD_SHA = '43dc5c66737144b7be485456235e7c4c023cfe1ae95e3e01aea889fd35a408cd'
LOCKED_METHOD_SHA = '9da306889daba39e691b720439cce9fcb1111b90c3ac5cfdec9ac7afc62b0f1d'
MODE_METHOD_ID = 15899
MODE_CODE_ITEM = 3841932
MODE_CODE_UNITS = 115

# Original unforced method from multiple independently preserved Nova APKs.
ORIGINAL_MODE_CODE = base64.b64decode(
    'cRCZzwUADABuEM0DBQAMBRoBwIxuIH8EFQAKBRIRGgLFehoDEYw4BRgAciBPBDAACgQ5BBIAGgSOJ3EgVQtC'
    'AHIQUAQAAAwEcjBIBDQBDARyEEYEBAA4BRgAcjBRBDABCgUiACsZGgEwEHAgmaQQAG4gpqRQAG4QsaQAAAwAc'
    'SBVCwIADwUbBZoZAQAbAdsUAQByMFUEUAEMBRsA2xgBAG4gW6RQAAoAIgErGRoDMmVwIJmkMQBuIKSkUQAaBa0A'
    'biCkpFEAbiCmpAEAGgWhBm4gpKRRAG4QsaQBAAwFcSBVC1IADwA='
)

# Fail if dual launch paths, tablet prompt or settings controls regressed.
EXPECTED_UNCHANGED = {
    (15872, 3826968, 109): 'aac9a622c5c98cecedeca62db815f46f44d0e0df74c88ab29617563b65e93977',
    (16961, 3922276, 135): '6dfc23cba338b5c27b4521b49e834a35324d6bf96c03824eb1e42a3cba8fd88b',
    (25610, 4683156, 2475): '22e605bc394256866aaf64687a611ac896c83f36accfec58d2cfd18d4fc7a5dc',
}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def method_value(dex, idx):
    """Resolve a method's owner and name from the DEX ID tables."""
    def string_at(index):
        count, off = struct.unpack_from('<II', dex, 56)
        if not (0 <= index < count):
            raise ValueError('DEX string index out of range')
        at = struct.unpack_from('<I', dex, off + index * 4)[0]
        for _ in range(5):
            b = dex[at]
            at += 1
            if b < 128:
                break
        else:
            raise ValueError('Invalid DEX UTF8 length')
        return dex[at:dex.index(b'\0', at)].decode('utf-8')
    type_count, type_off = struct.unpack_from('<II', dex, 64)
    method_count, method_off = struct.unpack_from('<II', dex, 88)
    if not (0 <= idx < method_count):
        raise ValueError('DEX method index out of range')
    owner, _proto, name = struct.unpack_from('<HHI', dex, method_off + idx * 8)
    if owner >= type_count:
        raise ValueError('DEX owner out of range')
    type_str = struct.unpack_from('<I', dex, type_off + owner * 4)[0]
    return string_at(type_str), string_at(name)

def verify_original_mode_guards(dex):
    if sha(dex) != INPUT_DEX_SHA:
        raise ValueError('Unexpected V7.14 no-header DEX baseline; abort')
    if len(ORIGINAL_MODE_CODE) != MODE_CODE_UNITS * 2 or sha(ORIGINAL_MODE_CODE) != SOURCE_METHOD_SHA:
        raise ValueError('Original Nova mode code was corrupted')
    if method_value(dex, MODE_METHOD_ID) != (
        'Lcom/archos/mediacenter/video/UiChoiceDialog;', 'applicationIsInLeanbackMode'
    ):
        raise ValueError('Wrong UiChoiceDialog method identity')
    head = struct.unpack_from('<4H2I', dex, MODE_CODE_ITEM)
    if head[:4] != (6, 1, 3, 0) or head[5] != MODE_CODE_UNITS:
        raise ValueError('Unexpected mode code header')
    pos = MODE_CODE_ITEM + 16
    original = dex[pos:pos + len(ORIGINAL_MODE_CODE)]
    if sha(original) != LOCKED_METHOD_SHA or original != bytes.fromhex('12100f00') + bytes(len(original) - 4):
        raise ValueError('Expected force-TRUE UI selector not present')
    for (method_idx, off, units), expected_hash in EXPECTED_UNCHANGED.items():
        if sha(dex[off+16:off+16+units*2]) != expected_hash:
            raise ValueError('Routing or settings not original: method ' + str(method_idx))
    entry = struct.unpack_from('<109H', dex, 3826968 + 16)
    if (entry[0x27], entry[0x2a]) != (0x0ad6, 0x094e):
        raise ValueError('TV/tablet launch routes modified')
    return pos

def patch(dex):
    pos = verify_original_mode_guards(dex)
    result = bytearray(dex)
    result[pos:pos+len(ORIGINAL_MODE_CODE)] = ORIGINAL_MODE_CODE
    result[12:32] = hashlib.sha1(result[32:]).digest()
    struct.pack_into('<I', result, 8, zlib.adler32(result[12:]) & 0xffffffff)
    result = bytes(result)
    if len(result) != len(dex) or sha(result) != OUTPUT_DEX_SHA:
        raise ValueError('Auto-mode output DEX digest mismatch')
    if result[32:pos] != dex[32:pos] or result[pos+len(ORIGINAL_MODE_CODE):] != dex[pos+len(ORIGINAL_MODE_CODE):]:
        raise ValueError('Unexpected extra DEX change')
    return result
