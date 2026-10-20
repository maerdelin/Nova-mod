#!/usr/bin/env python3
"""Run real patched APK backend classes in ART on a fresh CI emulator.

A loopback server and injected HTTP client are used: not cloud/device playback.
The test harness is separate from the installer, no test classes shipped in APK.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile
from webdav_parallel4_dex import latest
ROOT=Path(__file__).resolve().parents[1]
def run(args,**kwargs):return subprocess.run(list(map(str,args)),check=True,**kwargs)
def main():
    p=argparse.ArgumentParser();p.add_argument('apk',type=Path);p.add_argument('--reports',type=Path,required=True);a=p.parse_args()
    a.reports.mkdir(parents=True,exist_ok=True)
    report={'status':'FAIL','scope':'final APK backend + sidecar classes on Android ART, loopback HTTP; no real cloud/playback'}
    try:
        sdk=Path(os.environ['ANDROID_HOME']);tools=latest(sdk/'build-tools','*')
        jar=latest(sdk/'platforms','android-*')/'android.jar'
        with tempfile.TemporaryDirectory(prefix='fourfix-apk-')as td:
            tmp=Path(td);classes=tmp/'classes';classes.mkdir();dex=tmp/'dex';dex.mkdir()
            run(['javac','-source','8','-target','8','-cp',jar,'-d',classes,ROOT/'tests/android/FourFixApkProbe.java'],timeout=40)
            run([tools/'d8','--min-api','23','--lib',jar,'--output',dex]+sorted(classes.rglob('*.class')),timeout=40)
            harness=tmp/'fourfix-probe.jar'
            with zipfile.ZipFile(harness,'w') as z:z.write(dex/'classes.dex','classes.dex')
            run(['adb','push',harness,'/data/local/tmp/nova-fourfix-probe.jar'],timeout=60)
            run(['adb','push',a.apk,'/data/local/tmp/nova-fourfix-final.apk'],timeout=90)
            r=subprocess.run(['adb','shell','CLASSPATH=/data/local/tmp/nova-fourfix-final.apk:/data/local/tmp/nova-fourfix-probe.jar app_process /system/bin nova.test.FourFixApkProbe'],capture_output=True,text=True,timeout=90)
            (a.reports/'fourfix-apk-probe.txt').write_text(r.stdout+r.stderr)
            print(r.stdout+r.stderr)
            if r.returncode or 'FOURFIX_FINAL_APK_PROBE=PASS'not in r.stdout:raise RuntimeError('Final APK ART/HTTP regression failed')
        report['status']='PASS'
    except Exception as e:report['error']=str(e);raise
    finally:(a.reports/'fourfix-apk-probe.json').write_text(json.dumps(report,indent=2)+'\n')
    from smoke_single_stream import check
    check(a.apk,a.reports)
if __name__=='__main__':main()
