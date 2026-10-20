#!/usr/bin/env python3
"""Historical CLI name; production payload is SINGLE continuous stream only.

Keep common verified HTTP/sidecar/ISO/UI helpers. Do not compile or ship the
parallel downloader. Old source remains only for historical regression tests.
"""
import argparse
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / 'parallel_range4/src'
UI_SRC_ROOT = ROOT / 'playback_ui/src'
SINGLE_SRC_ROOT = ROOT / 'single_stream/src'
UI_REQUIRED = {'NovaControlbarAutoHide.java'}
REQUIRED = {'NovaParallelRangeInputStream.java', 'NovaWebdavSidecarPolicy.java',
            'NovaWebdavOpenPolicy.java', 'NovaIsoSessionGuard.java'}
PRODUCTION_REQUIRED = (REQUIRED - {'NovaParallelRangeInputStream.java'}) | {'NovaSingleStreamInputStream.java'}

def latest(folder, glob):
    paths = list(folder.glob(glob))
    if not paths: raise RuntimeError(f'Missing Android SDK tools: {folder}')
    return max(paths, key=lambda p: tuple(int(x) for x in re.findall(r'\d+', p.name)))

def prepare_sources(destination):
    old = sorted(SRC_ROOT.rglob('*.java')); ui = sorted(UI_SRC_ROOT.rglob('*.java'))
    single = sorted(SINGLE_SRC_ROOT.rglob('*.java'))
    if {p.name for p in old} != REQUIRED or {p.name for p in ui} != UI_REQUIRED:
        raise RuntimeError('Unexpected historical/common source set')
    if {p.name for p in single} != {'NovaSingleStreamInputStream.java'}:
        raise RuntimeError('Unexpected single-stream source set')
    target = destination / 'com/archos/filecorelibrary'; target.mkdir(parents=True, exist_ok=True)
    for p in old:
        if p.name == 'NovaParallelRangeInputStream.java': continue
        text = p.read_text().replace('NovaParallelRangeInputStream', 'NovaSingleStreamInputStream')
        (target / p.name).write_text(text)
    for p in single + ui: (target / p.name).write_text(p.read_text())
    files = sorted(target.glob('*.java'))
    if {p.name for p in files} != PRODUCTION_REQUIRED | UI_REQUIRED:
        raise RuntimeError('Unexpected production source set')
    for p in files:
        if 'NovaParallelRangeInputStream' in p.read_text():
            raise RuntimeError('Parallel dependency leaked into production: ' + str(p))
    return files

def append(source, target, dex):
    if not dex.startswith(b'dex\n') or len(dex) < 100: raise RuntimeError('Invalid DEX payload')
    with zipfile.ZipFile(source) as original:
        names = original.namelist()
        if len(names) != len(set(names)): raise RuntimeError('Duplicate APK entries')
        indexes = [1 if n == 'classes.dex' else int(re.fullmatch(r'classes(\d+)\.dex', n).group(1))
                   for n in names if n == 'classes.dex' or re.fullmatch(r'classes(\d+)\.dex', n)]
        if not indexes or sorted(indexes) != list(range(1, max(indexes) + 1)):
            raise RuntimeError('Non-contiguous multidex sequence')
        added = f'classes{max(indexes) + 1}.dex'
        with zipfile.ZipFile(target, 'w') as output:
            output.comment = original.comment
            for entry in original.infolist(): output.writestr(entry, original.read(entry.filename))
            output.writestr(added, dex, compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target) as check:
        if check.testzip() or check.read(added) != dex: raise RuntimeError('DEX injection verification failed')
        if set(check.namelist()) - set(names) != {added}: raise RuntimeError('Unexpected entry delta')
        for name in names:
            if check.read(name) != original.read(name): raise RuntimeError('Existing entry changed: ' + name)
    return added

def verify_single_apk(apk):
    with zipfile.ZipFile(apk) as z:
        dexes = [z.read(n) for n in z.namelist() if re.fullmatch(r'classes(?:[0-9]+)?\.dex', n)]
    if not dexes: raise RuntimeError('No DEX in final APK')
    for data in dexes:
        for token in (b'NovaParallelRangeInputStream', b'novaWrapRange4', b'publishRange4'):
            if token in data: raise RuntimeError('Parallel code/reference still in APK: ' + token.decode())
    if not any(b'NovaSingleStreamInputStream;' in d for d in dexes):
        raise RuntimeError('Single stream helper missing from APK')

def build(source, target, report=None):
    sdk = Path(os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT') or '/no-sdk')
    jar = latest(sdk / 'platforms', 'android-*') / 'android.jar'
    d8 = latest(sdk / 'build-tools', '*') / 'd8'
    if not jar.is_file() or not d8.is_file(): raise RuntimeError('Missing Android SDK tools')
    with tempfile.TemporaryDirectory(prefix='nova-single-') as tmp:
        td = Path(tmp); classes = td / 'classes'; classes.mkdir(); dexdir = td / 'dex'; dexdir.mkdir()
        sources = prepare_sources(td / 'src')
        subprocess.run(['javac', '-source', '8', '-target', '8', '-cp', str(jar),
                        '-d', str(classes)] + [str(p) for p in sources], check=True)
        files = sorted(str(p) for p in classes.rglob('*.class'))
        for name in ('NovaSingleStreamInputStream.class', 'NovaSingleStreamInputStream$ManagedSource.class',
                     'NovaWebdavSidecarPolicy.class', 'NovaWebdavOpenPolicy.class', 'NovaIsoSessionGuard.class',
                     'NovaControlbarAutoHide.class', 'NovaControlbarAutoHide$Host.class'):
            if not (classes / 'com/archos/filecorelibrary' / name).is_file():
                raise RuntimeError('Compiled helper missing: ' + name)
        subprocess.run([str(d8), '--min-api', '23', '--lib', str(jar), '--output', str(dexdir)] + files, check=True)
        dex = (dexdir / 'classes.dex').read_bytes(); name = append(source, target, dex)
    verify_single_apk(target)
    result = {'status': 'PASS', 'mode': 'single-continuous', 'additional_dex': name,
              'byte_count': len(dex), 'compiled_classes': len(files),
              'sources': sorted(PRODUCTION_REQUIRED | UI_REQUIRED), 'parallel_helper_shipped': False,
              'existing_entries_untouched': True}
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + '\n')
    return result

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True); p.add_argument('--report', type=Path)
    a = p.parse_args(); print(json.dumps(build(a.source, a.output, a.report), indent=2))
