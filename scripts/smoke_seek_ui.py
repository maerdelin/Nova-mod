#!/usr/bin/env python3
"""Run final APK UI controller hooks and timer in ART with an injected clock.
The test harness is separate from the installer; no test classes ship in APK.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile
ROOT=Path(__file__).resolve().parents[1]
def latest(root, pattern):
    items=sorted(root.glob(pattern))
    if not items: raise RuntimeError('SDK path missing')
    return items[-1]
def run(args,**kwargs):return subprocess.run(list(map(str,args)),check=True,**kwargs)
def main():
    p=argparse.ArgumentParser();p.add_argument('apk',type=Path);p.add_argument('--reports',type=Path,required=True);a=p.parse_args()
    a.reports.mkdir(parents=True,exist_ok=True)
    report={'status':'FAIL','scope':'final APK UI controller hooks + production timer on Android ART, injected clock; not real device playback'}
    try:
        sdk=Path(os.environ['ANDROID_HOME']);tools=latest(sdk/'build-tools','*')
        jar=latest(sdk/'platforms','android-*')/'android.jar'
        with tempfile.TemporaryDirectory(prefix='seek-ui-apk-')as td:
            tmp=Path(td);classes=tmp/'classes';classes.mkdir();dex=tmp/'dex';dex.mkdir()
            run(['javac','-source','8','-target','8','-cp',jar,'-d',classes,ROOT/'tests/android/SeekUiApkProbe.java'],timeout=40)
            run([tools/'d8','--min-api','23','--lib',jar,'--output',dex]+sorted(classes.rglob('*.class')),timeout=40)
            harness=tmp/'seek-ui-probe.jar'
            with zipfile.ZipFile(harness,'w') as z:z.write(dex/'classes.dex','classes.dex')
            run(['adb','push',harness,'/data/local/tmp/nova-seek-ui-probe.jar'],timeout=60)
            run(['adb','push',a.apk,'/data/local/tmp/nova-seek-ui-final.apk'],timeout=90)
            r=subprocess.run(['adb','shell','CLASSPATH=/data/local/tmp/nova-seek-ui-final.apk:/data/local/tmp/nova-seek-ui-probe.jar app_process /system/bin nova.test.SeekUiApkProbe'],capture_output=True,text=True,timeout=90)
            (a.reports/'seek-ui-apk-probe.txt').write_text(r.stdout+r.stderr)
            print(r.stdout+r.stderr)
            if r.returncode or 'SEEK_UI_FINAL_APK_PROBE=PASS'not in r.stdout:raise RuntimeError('Final APK ART UI regression failed')
        report['status']='PASS'
    except Exception as e:report['error']=str(e);raise
    finally:(a.reports/'seek-ui-apk-probe.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
