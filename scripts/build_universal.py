#!/usr/bin/env python3
"""Build four-ABI Universal APK from exact user-confirmed working V7.14 three-button ARM32 APK.

No attempt to misrepresent a binary reconstruction as original source compilation.
Only official Nova v6.5.5 extra-architecture native libraries are added to
the SHA-256-pinned user-confirmed V7.14 three-button APK. Only the pinned local-root listing method in classes.dex is patched; resources and other assets are not altered.
"""
import argparse, hashlib, io, zipfile
from pathlib import Path

OFFICIAL_UNIVERSAL_SHA='f252631680328916ed847c8c0d6711d6a9922373e54f939178c428a9b3c3e1a5'
USER_CONFIRMED_ARM32_SHA='b48c77f62c265b9da979010a1e88829773cd82a3b900f479584f0f0aa752786d'
USER_CONFIRMED_DEX_SHA='a69ea18e18ced34514adf1fe11c62023c9bb60de3c34809119da64ad9e49c78f'
ABIS={'armeabi-v7a','arm64-v8a','x86','x86_64'}
USB_GUARD_OFFSET=6496480
USB_GUARD_OLD=bytes.fromhex('20a09b0b')
USB_GUARD_NEW=bytes.fromhex('20b01d1a')
USB_FIXED_DEX_SHA='beb6979f8d68b401f0968a3f4f7d6837fbb58000771d941e6d1fdfc9d096a519'

def fix_usb_guard(dex):
    import struct, zlib
    if hashlib.sha256(dex).hexdigest()!=USER_CONFIRMED_DEX_SHA:
        raise RuntimeError('Incorrect three-button DEX input')
    if dex[USB_GUARD_OFFSET:USB_GUARD_OFFSET+4]!=USB_GUARD_OLD:
        raise RuntimeError('Unexpected USB root guard instruction')
    patched=bytearray(dex)
    patched[USB_GUARD_OFFSET:USB_GUARD_OFFSET+4]=USB_GUARD_NEW
    patched[12:32]=hashlib.sha1(patched[32:]).digest()
    struct.pack_into('<I',patched,8,zlib.adler32(patched[12:]) & 0xffffffff)
    result=bytes(patched)
    if hashlib.sha256(result).hexdigest()!=USB_FIXED_DEX_SHA:
        raise RuntimeError('USB-fixed DEX digest unexpected')
    return result


REMOVABLE_CODE_OFFSET=6496464+16
REMOVABLE_CODE_UNITS=88
REMOVABLE_METHOD_CODE=bytes.fromhex(
    '20a09b0b38004c0055a0fd6138004800380b46007100ab2e00000c0007086e10a92e08000c006e10aa2e08000c09722094a890006e10ac2e08000c09722094a890002202011a702098a7b20072109ca800000c03120472106ba803000a0138011e0072106ca803000c053805f6ff1f0529192206c918702062a256006e1077a206000a073807e9ff22073e077020113267006e3099a7420728df080b5babfe6112105ca0fb617010b2500a0000000e00'
)
REMOVABLE_METHOD_SHA='ee37f720d41edba53c6504c6f429c2fcb5befbc9b25bfef0ad6d1735c46dbd8a'
REMOVABLE_FIXED_DEX_SHA='e4902f10e4329bf39302bf1b001cff2e72fe953f1185e19a3ff8b4bad01d2999'

def patch_local_root_removable(dex):
    """Retain the original 88-unit onListingUpdate method layout.

    Add SD/USB/OTHER volumes at the beginning of *local* root browsing only.
    The original local root callback still supplies its existing internal folders;
    network and child directories are left untouched. The getter results are
    modifiable ArrayList copies in pinned ExtStorageManager.
    """
    import struct, zlib
    if hashlib.sha256(dex).hexdigest()!=USB_FIXED_DEX_SHA:
        raise RuntimeError('Wrong input DEX for local-root removable patch')
    if struct.unpack_from('<4H2I',dex,6496464)!=(12,2,4,0,0,88):
        raise RuntimeError('Unexpected onListingUpdate code layout')
    if dex[REMOVABLE_CODE_OFFSET:REMOVABLE_CODE_OFFSET+4]!=USB_GUARD_NEW:
        raise RuntimeError('Unexpected prior USB guard instruction')
    if len(REMOVABLE_METHOD_CODE)!=REMOVABLE_CODE_UNITS*2 or hashlib.sha256(REMOVABLE_METHOD_CODE).hexdigest()!=REMOVABLE_METHOD_SHA:
        raise RuntimeError('Incorrect removable-storage replacement method')
    patched=bytearray(dex)
    patched[REMOVABLE_CODE_OFFSET:REMOVABLE_CODE_OFFSET+2*REMOVABLE_CODE_UNITS]=REMOVABLE_METHOD_CODE
    patched[12:32]=hashlib.sha1(patched[32:]).digest()
    struct.pack_into('<I',patched,8,zlib.adler32(patched[12:]) & 0xffffffff)
    result=bytes(patched)
    if len(result)!=len(dex) or hashlib.sha256(result).hexdigest()!=REMOVABLE_FIXED_DEX_SHA:
        raise RuntimeError('Patched local-root removable DEX digest mismatch')
    return result

def final_dex(dex):
    return patch_local_root_removable(fix_usb_guard(dex))

def signature_metadata(n):
    n=n.upper()
    return n=='META-INF/MANIFEST.MF' or (n.startswith('META-INF/') and n.endswith(('.SF','.RSA','.DSA','.EC')))

def check_base(arm32_path,universal_path):
    if sha(arm32_path)!=USER_CONFIRMED_ARM32_SHA:
        raise RuntimeError('Wrong source: this is not the user-confirmed working three-button ARM32 APK')
    if sha(universal_path)!=OFFICIAL_UNIVERSAL_SHA:
        raise RuntimeError('Untrusted official Nova 6.5.5 Universal APK: SHA-256 differs')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def abi(name):
    p=name.split('/')
    return p[1] if len(p)>2 and p[0]=='lib' and p[1] in ABIS else None

def merge(arm32_path,universal_path,out_path):
    check_base(arm32_path,universal_path)
    with zipfile.ZipFile(arm32_path) as base, zipfile.ZipFile(universal_path) as official:
        if base.testzip() is not None or official.testzip() is not None:
            raise RuntimeError('Corrupt ZIP input')
        original=base.namelist()
        if len(original)<1937 or len(original)>1950:raise RuntimeError('V7.14.1 signed APK entry count unexpected')
        if hashlib.sha256(base.read('classes.dex')).hexdigest()!=USER_CONFIRMED_DEX_SHA:
            raise RuntimeError('Three-button code hash changed')
        source=set(official.namelist())
        b32={n for n in original if abi(n)=='armeabi-v7a'}
        o32={n for n in source if abi(n)=='armeabi-v7a'}
        if b32!=o32:
            raise RuntimeError('ARM32 libraries differ between V7.14 and pinned official Universal')
        for n in b32:
            if base.read(n)!=official.read(n):
                raise RuntimeError('ARM32 library mismatch: '+n)
        additions=[n for n in official.namelist() if abi(n) in ABIS-{'armeabi-v7a'}]
        if not additions or {abi(n) for n in additions}!=ABIS-{'armeabi-v7a'}:
            raise RuntimeError('Official APK did not contain all three additional ABIs')
        extras=[n for n in original if abi(n) not in ABIS and n in source and
                n not in {'classes.dex','resources.arsc'} and not n.startswith('res/')]
        # Preserve every V7.14 functional file unchanged; do not silently merge
        # other upstream resources, assets, code or UI into the tested baseline.
        for n in extras:
            if n.startswith('META-INF/'):continue
            if base.read(n)!=official.read(n):
                raise RuntimeError('Unexpected non-ABI upstream difference: '+n)
        out_path=Path(out_path);out_path.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(out_path,'w',allowZip64=False) as out:
            for inf in base.infolist():
                if signature_metadata(inf.filename): continue  # fresh v1/v2/v3 signatures must be generated by apksigner
                o=zipfile.ZipInfo(inf.filename,inf.date_time)
                o.compress_type=inf.compress_type
                o.external_attr=inf.external_attr
                o.create_system=inf.create_system
                data=base.read(inf.filename)
                if inf.filename=='classes.dex':data=final_dex(data)
                out.writestr(o,data,compress_type=o.compress_type,compresslevel=6)
            for n in additions:
                inf=official.getinfo(n)
                o=zipfile.ZipInfo(n,inf.date_time)
                o.compress_type=inf.compress_type
                o.external_attr=inf.external_attr
                o.create_system=inf.create_system
                out.writestr(o,official.read(n),compress_type=o.compress_type,compresslevel=6)
    verify(arm32_path,universal_path,out_path)
    print('PASS: Three-button Universal four-ABI unsigned build; only native libraries added',out_path.stat().st_size)

def verify(arm32_path,universal_path,candidate_path):
    check_base(arm32_path,universal_path)
    with zipfile.ZipFile(arm32_path) as base, zipfile.ZipFile(universal_path) as official, zipfile.ZipFile(candidate_path) as candidate:
        if base.testzip() or official.testzip() or candidate.testzip():
            raise RuntimeError('APK ZIP CRC failure')
        if hashlib.sha256(base.read('classes.dex')).hexdigest()!=USER_CONFIRMED_DEX_SHA:
            raise RuntimeError('User-confirmed three-button DEX SHA-256 mismatch')
        original={n for n in base.namelist() if not signature_metadata(n)}
        expected_extra={n for n in official.namelist() if abi(n) in ABIS-{'armeabi-v7a'}}
        actual={n for n in candidate.namelist() if not signature_metadata(n)}
        expected=original | expected_extra
        if actual != expected or len(candidate.namelist())!=len(set(candidate.namelist())):
            raise RuntimeError('Unexpected missing/extra/duplicate functional APK entries: '+repr((expected-actual,actual-expected)))
        for n in original:
            data=base.read(n)
            if n=='classes.dex':data=final_dex(data)
            if data!=candidate.read(n):
                raise RuntimeError('Modified functional asset outside USB-only patch: '+n)
        for n in expected_extra:
            if official.read(n)!=candidate.read(n):
                raise RuntimeError('Modified official Nova 6.5.5 native library: '+n)
        for target in sorted(ABIS):
            n=sum(1 for item in actual if abi(item)==target)
            if n==0:raise RuntimeError('Missing native ABI '+target)
            print('PASS: ABI',target,n,'libraries')
    print('PASS: three-button baseline retained except targeted local-root removable-storage listing patch')
    print('PASS: official SHA-pinned Nova 6.5.5 native libraries added for other three ABIs')

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['merge','verify'])
    p.add_argument('arm32')
    p.add_argument('official_universal')
    p.add_argument('candidate')
    a=p.parse_args()
    (merge if a.command=='merge' else verify)(a.arm32,a.official_universal,a.candidate)
