#!/usr/bin/env python3
"""Reject any build that modifies more than the intended V7.14 home-card instruction.

The input may be the zipaligned/signed APK: Android signer-generated META-INF
entries are allowed, but all original ZIP member payloads are compared exactly.
"""
import argparse
from pathlib import Path
import zipfile

from four_cards import h256, patch_dex, REFERENCE_APK_SHA256, REFERENCE_APK_BYTES


def verify(reference: Path, candidate: Path) -> None:
    original=reference.read_bytes()
    if h256(original)!=REFERENCE_APK_SHA256 or len(original)!=REFERENCE_APK_BYTES:
        raise RuntimeError('Wrong V7.14 reference')
    if candidate.stat().st_size < 25_000_000:
        raise RuntimeError('Candidate implausibly small')
    with zipfile.ZipFile(reference) as a,zipfile.ZipFile(candidate) as b:
        if a.testzip() is not None or b.testzip() is not None:
            raise RuntimeError('ZIP integrity check failed')
        original_names=set(a.namelist())
        actual_names=set(b.namelist())
        if not original_names.issubset(actual_names):
            raise RuntimeError(f'V7.14 assets deleted: {original_names-actual_names}')
        extras=actual_names-original_names
        if any(not n.startswith('META-INF/') for n in extras):
            raise RuntimeError(f'Unexpected added assets: {extras}')
        expected=patch_dex(a.read('classes.dex'))
        if b.read('classes.dex')!=expected:
            raise RuntimeError('DEX changes outside one protected method')
        for name in original_names-{'classes.dex'}:
            if a.read(name)!=b.read(name):
                raise RuntimeError(f'Unexpected V7.14 functional asset edit: {name}')
    print('PASS: 1 changed DEX instruction (void return in non-scraped card updater), all other baseline assets identical')
    print('PASS: video, SMB/WebDAV, storage, subtitles, preferences and current fixed four-card layout bytes retained')
    print('Candidate bytes',candidate.stat().st_size,'sha256',h256(candidate.read_bytes()))


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('reference',type=Path)
    p.add_argument('candidate',type=Path)
    args=p.parse_args()
    verify(args.reference,args.candidate)

if __name__=='__main__':main()
