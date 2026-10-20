#!/usr/bin/env python3
"""Append compiled Java Range4 helper as a new DEX to final unsigned APK."""
import argparse
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / 'parallel_range4/src/com/archos/filecorelibrary/NovaParallelRangeInputStream.java'

def latest(folder, glob):
    paths = list(folder.glob(glob))
    if not paths: raise RuntimeError(f'Missing Android SDK tools: {folder}')
    return max(paths, key=lambda p: tuple(int(x) for x in re.findall(r'\d+', p.name)))

def append(source, target, dex):
    if not dex.startswith(b'dex\n') or len(dex) < 100:
        raise RuntimeError('Invalid DEX payload')
    with zipfile.ZipFile(source) as original:
        names=original.namelist()
        if len(names) != len(set(names)): raise RuntimeError('Duplicate APK entries')
        indexes=[1 if n=='classes.dex' else int(re.fullmatch(r'classes(\d+)\.dex',n).group(1))
                 for n in names if n=='classes.dex' or re.fullmatch(r'classes(\d+)\.dex',n)]
        if sorted(indexes) != list(range(1,max(indexes)+1)):
            raise RuntimeError('Non-contiguous multidex sequence')
        added=f'classes{max(indexes)+1}.dex'
        with zipfile.ZipFile(target,'w') as output:
            output.comment=original.comment
            for entry in original.infolist():
                output.writestr(entry,original.read(entry.filename))
            output.writestr(added,dex,compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(target) as check:
        if check.testzip() or check.read(added)!=dex:
            raise RuntimeError('DEX injection verification failed')
        if set(check.namelist())-set(names)!={added}:
            raise RuntimeError('Unexpected entry delta')
    return added

def build(source,target,report=None):
    sdk=Path(os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT') or '/no-sdk')
    jar=latest(sdk/'platforms','android-*')/'android.jar'
    d8=latest(sdk/'build-tools','*')/'d8'
    if not SRC.is_file() or not jar.is_file() or not d8.is_file():
        raise RuntimeError('Missing source/android.jar/d8')
    with tempfile.TemporaryDirectory(prefix='nova4-') as tmp:
        td=Path(tmp); classes=td/'classes'; classes.mkdir()
        dexdir=td/'dex'; dexdir.mkdir()
        subprocess.run(['javac','-source','8','-target','8','-cp',str(jar),
                        '-d',str(classes),str(SRC)],check=True)
        files=sorted(str(p) for p in classes.rglob('*.class'))
        if len(files)<2: raise RuntimeError('Compiled classes missing')
        subprocess.run([str(d8),'--min-api','23','--lib',str(jar),
                        '--output',str(dexdir)]+files,check=True)
        dex=(dexdir/'classes.dex').read_bytes()
        name=append(source,target,dex)
    result={'status':'PASS','additional_dex':name,'byte_count':len(dex),
            'compiled_classes':len(files),'existing_entries_untouched':True}
    if report:
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--report',type=Path)
    a=p.parse_args()
    print(json.dumps(build(a.source,a.output,a.report),indent=2))
