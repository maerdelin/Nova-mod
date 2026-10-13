#!/usr/bin/env python3
"""Verify every functional APK entry against the previous signed V7.14 Release.

Exactly one DEX method may differ. Android signing is independently checked
with apksigner; this validator is NOT a claim of Android UI runtime testing.
"""
import sys
import zipfile
from pathlib import Path
from restore_auto_mode import patch, sha, OUTPUT_DEX_SHA

RELEASED_PREVIOUS_SHA = 'e37276b501c41f4be7286fd432d1fb42d6997cb273269845fc90b16af19bf244'
KNOWN_ABIS = {'armeabi-v7a','arm64-v8a','x86','x86_64'}

def signing_file(name):
    s = name.upper()
    return s == 'META-INF/MANIFEST.MF' or (s.startswith('META-INF/') and s.endswith(('.SF','.RSA','.DSA','.EC')))

def validate(previous_apk, candidate_apk):
    previous_apk, candidate_apk = Path(previous_apk), Path(candidate_apk)
    if sha(previous_apk.read_bytes()) != RELEASED_PREVIOUS_SHA:
        raise ValueError('Wrong reference: must be the SHA-pinned previously released signed V7.14')
    with zipfile.ZipFile(previous_apk) as a, zipfile.ZipFile(candidate_apk) as b:
        if a.testzip() or b.testzip():
            raise ValueError('Corrupt APK ZIP')
        a_files = [n for n in a.namelist() if not signing_file(n)]
        b_files = [n for n in b.namelist() if not signing_file(n)]
        if len(a_files)!=len(set(a_files)) or len(b_files)!=len(set(b_files)):
            raise ValueError('Duplicate ZIP entries')
        if set(a_files)!=set(b_files):
            raise ValueError('Unexpected new/deleted APK functional member')
        expected_dex = patch(a.read('classes.dex'))
        if sha(expected_dex) != OUTPUT_DEX_SHA or b.read('classes.dex') != expected_dex:
            raise ValueError('DEX is not exactly the one-method original-selector restore')
        changed = [n for n in a_files if a.read(n) != b.read(n)]
        if changed != ['classes.dex']:
            raise ValueError('Unexpected changed APK functional files: '+repr(changed))
        libs={name:0 for name in KNOWN_ABIS}
        for name in b_files:
            x=name.split('/')
            if len(x)>=3 and x[0]=='lib' and x[1] in libs:
                libs[x[1]]+=1
        if any(v!=22 for v in libs.values()):
            raise ValueError('Four-ABI parity regression: '+repr(libs))
        for name in ('AndroidManifest.xml','resources.arsc','res/Am.xml'):
            if a.read(name)!=b.read(name):
                raise ValueError('Unexpected TV manifest, resources or home layout modification')
    print('PASS: exact original 115-unit mode selector restored')
    print('PASS: Only classes.dex changes; all other TV UI/14TV/network functional assets retained')
    print('PASS: 22 native libraries for each of 4 architectures')
    print('PASS: ZIP integrity; APK signing separately enforced by apksigner')
    print('NOTE: Hardware or emulator mode switching requires separate run')

if __name__=='__main__':
    if len(sys.argv)!=3:
        print('Usage: verify_auto_mode_apk.py previous-signed.apk candidate-signed.apk')
        sys.exit(2)
    validate(sys.argv[1],sys.argv[2])
