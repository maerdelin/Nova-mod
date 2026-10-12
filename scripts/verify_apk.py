#!/usr/bin/env python3
"""Reject corrupt, empty, unsigned or unexpected release APKs."""
import argparse
from pathlib import Path
import subprocess
import zipfile

p = argparse.ArgumentParser()
p.add_argument('apk', type=Path)
p.add_argument('--apksigner', required=True)
a = p.parse_args()
assert a.apk.is_file() and a.apk.stat().st_size > 1_000_000, 'APK missing or implausibly small'
with zipfile.ZipFile(a.apk) as z:
    assert z.testzip() is None, 'Corrupt APK ZIP'
    names = set(z.namelist())
    assert 'AndroidManifest.xml' in names and 'classes.dex' in names and 'resources.arsc' in names
subprocess.run([a.apksigner, 'verify', '--verbose', str(a.apk)], check=True)
print('PASS: one signed and structurally valid APK:', a.apk)
