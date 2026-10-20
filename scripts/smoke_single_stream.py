#!/usr/bin/env python3
"""Load the shipped single copier + WebdavFileEditor in ART, not a helper substitute."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile
from webdav_parallel4_dex import latest, verify_single_apk
ROOT=Path(__file__).resolve().parents[1]

def check(apk, reports):
    reports=Path(reports);reports.mkdir(parents=True,exist_ok=True)
    report={'status':'FAIL','scope':'final APK single copier and actual HTTP backend on Android ART; synthetic loopback only'}
    try:
        verify_single_apk(apk)
        sdk=Path(os.environ['ANDROID_HOME']);tools=latest(sdk/'build-tools','*');jar=latest(sdk/'platforms','android-*')/'android.jar'
        with tempfile.TemporaryDirectory(prefix='single-apk-') as td:
            root=Path(td);classes=root/'classes';classes.mkdir();dex=root/'dex';dex.mkdir()
            subprocess.run(['javac','-source','8','-target','8','-cp',str(jar),'-d',str(classes),
                str(ROOT/'single_stream/src/com/archos/filecorelibrary/NovaSingleStreamInputStream.java'),
                str(ROOT/'tests/android/SingleStreamHarness.java'),
                str(ROOT/'tests/android/FourFixApkProbe.java')],check=True,timeout=45)
            # Compile-time helper is EXCLUDED. Every helper call resolves to final APK DEX in ART.
            tests=sorted((classes/'nova/test').rglob('*.class'))
            subprocess.run([str(tools/'d8'),'--min-api','23','--lib',str(jar),'--output',str(dex)]+list(map(str,tests)),check=True,timeout=45)
            data=(dex/'classes.dex').read_bytes()
            harness=root/'single-probe.jar'
            with zipfile.ZipFile(harness,'w') as z:z.writestr('classes.dex',data)
            subprocess.run(['adb','push',str(harness),'/data/local/tmp/nova-single-probe.jar'],check=True,timeout=60)
            subprocess.run(['adb','push',str(apk),'/data/local/tmp/nova-single-final.apk'],check=True,timeout=90)
            result=subprocess.run(['adb','shell','CLASSPATH=/data/local/tmp/nova-single-final.apk:/data/local/tmp/nova-single-probe.jar app_process /system/bin nova.test.SingleStreamHarness --apk'],capture_output=True,text=True,timeout=120)
            (reports/'single-stream-apk-probe.txt').write_text(result.stdout+result.stderr)
            print(result.stdout+result.stderr)
            if result.returncode or 'SINGLE_STREAM_PROBE=PASS' not in result.stdout:raise RuntimeError('single final-APK probe failed')
            report['status']='PASS'
            report['parallel_class_shipped']=False
            report['continuous_http_case']={'bytes':33554469,'get_requests':1,'uses_final_apk_WebdavFileEditor':True}
    except Exception as e:report['error']=str(e);raise
    finally:(reports/'single-stream-apk-probe.json').write_text(json.dumps(report,indent=2)+'\n')
