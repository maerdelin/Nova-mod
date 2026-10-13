#!/usr/bin/env python3
"""Build four-ABI Universal APK around byte-verified V7.14.1 ARM32 functionality.

No attempt to misrepresent a binary reconstruction as original source compilation.
Only official Nova v6.5.5 extra-architecture native libraries are added to
the known-working V7.14.1 APK. No DEX, resources or assets are altered.
"""
import argparse, hashlib, io, zipfile
from pathlib import Path

OFFICIAL_UNIVERSAL_SHA='f252631680328916ed847c8c0d6711d6a9922373e54f939178c428a9b3c3e1a5'
ABIS={'armeabi-v7a','arm64-v8a','x86','x86_64'}

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def abi(name):
    p=name.split('/')
    return p[1] if len(p)>2 and p[0]=='lib' and p[1] in ABIS else None

def merge(arm32_path,universal_path,out_path):
    if sha(universal_path)!=OFFICIAL_UNIVERSAL_SHA:
        raise RuntimeError('Untrusted official Universal APK: SHA-256 differs')
    with zipfile.ZipFile(arm32_path) as base, zipfile.ZipFile(universal_path) as official:
        if base.testzip() is not None or official.testzip() is not None:
            raise RuntimeError('Corrupt ZIP input')
        original=base.namelist()
        if len(original)<1937 or len(original)>1950:raise RuntimeError('V7.14.1 signed APK entry count unexpected')
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
                o=zipfile.ZipInfo(inf.filename,inf.date_time)
                o.compress_type=inf.compress_type
                o.external_attr=inf.external_attr
                o.create_system=inf.create_system
                out.writestr(o,base.read(inf.filename),compress_type=o.compress_type,compresslevel=6)
            for n in additions:
                inf=official.getinfo(n)
                o=zipfile.ZipInfo(n,inf.date_time)
                o.compress_type=inf.compress_type
                o.external_attr=inf.external_attr
                o.create_system=inf.create_system
                out.writestr(o,official.read(n),compress_type=o.compress_type,compresslevel=6)
    verify(arm32_path,universal_path,out_path)
    print('PASS: Universal four-ABI unsigned build; only native libraries added',out_path.stat().st_size)

def verify(arm32_path,universal_path,candidate_path):
    with zipfile.ZipFile(arm32_path) as base,zipfile.ZipFile(universal_path) as official,zipfile.ZipFile(candidate_path) as candidate:
        if candidate.testzip() is not None:raise RuntimeError('Candidate ZIP CRC failure')
        old=set(base.namelist())
        if not old.issubset(candidate.namelist()):raise RuntimeError('V7.14 assets missing')
        for n in old:
            if n == 'META-INF/MANIFEST.MF' or (n.startswith('META-INF/') and n.rsplit('/',1)[-1].upper().endswith(('.SF','.RSA','.DSA','.EC'))):continue  # v1 signing metadata is expected to change
            if base.read(n)!=candidate.read(n):raise RuntimeError('Modified tested V7.14 entry: '+n)
        expected={n for n in official.namelist() if abi(n) in ABIS-{'armeabi-v7a'}}
        actual=set(candidate.namelist())-old
        if not expected.issubset(actual):raise RuntimeError('Missing additional ABI libraries')
        if any(n not in expected and not n.startswith('META-INF/') for n in actual):
            raise RuntimeError('Unexpected extra files: '+repr(actual-expected))
        for n in expected:
            if official.read(n)!=candidate.read(n):
                raise RuntimeError('Changed official native lib '+n)
        for target in ABIS:
            if not any(abi(n)==target for n in candidate.namelist()):
                raise RuntimeError('ABI missing '+target)
    print('PASS: all prior V7.14.1 files identical; four native ABIs correct')

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['merge','verify'])
    p.add_argument('arm32')
    p.add_argument('official_universal')
    p.add_argument('candidate')
    a=p.parse_args()
    (merge if a.command=='merge' else verify)(a.arm32,a.official_universal,a.candidate)
