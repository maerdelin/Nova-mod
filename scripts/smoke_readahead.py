#!/usr/bin/env python3
"""Run the final APK's actual main stream loop on ART; loopback is not cloud speed."""
import argparse,json,os,subprocess,tempfile,zipfile
from pathlib import Path
from webdav_fixes_dex import latest
from main_transport_audit import verify_apk_absence
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('apk',type=Path);p.add_argument('--reports',type=Path,required=True);a=p.parse_args()
    report={'status':'FAIL','scope':'actual session-owned FIFO + unchanged main copy + actual WebDAV backend on ART loopback; not real cloud/STB throughput'}
    a.reports.mkdir(parents=True,exist_ok=True)
    try:
        report['absence']=verify_apk_absence(a.apk,True)
        sdk=Path(os.environ['ANDROID_HOME']);tools=latest(sdk/'build-tools','*');jar=latest(sdk/'platforms','android-*')/'android.jar'
        def run(args,timeout=60):subprocess.run(list(map(str,args)),check=True,timeout=timeout)
        with tempfile.TemporaryDirectory(prefix='main-copy-probe-') as tmp:
            td=Path(tmp);classes=td/'classes';classes.mkdir();dex=td/'dex';dex.mkdir()
            run(['javac','-source','8','-target','8','-cp',jar,'-d',classes,ROOT/'tests/android/FourFixApkProbe.java',ROOT/'tests/android/AheadApkProbe.java'])
            run([tools/'d8','--min-api','23','--lib',jar,'--output',dex]+sorted(classes.rglob('*.class')))
            harness=td/'probe.jar'
            with zipfile.ZipFile(harness,'w') as z:z.write(dex/'classes.dex','classes.dex')
            run(['adb','push',harness,'/data/local/tmp/nova-ahead-probe.jar']);run(['adb','push',a.apk,'/data/local/tmp/nova-ahead-final.apk'],90)
            r=subprocess.run(['adb','shell','CLASSPATH=/data/local/tmp/nova-ahead-final.apk:/data/local/tmp/nova-ahead-probe.jar app_process /system/bin nova.test.AheadApkProbe'],capture_output=True,text=True,timeout=180)
            (a.reports/'readahead-apk-probe.txt').write_text(r.stdout+r.stderr);print(r.stdout+r.stderr)
            if r.returncode or 'AHEAD_FINAL_APK_PROBE=PASS' not in r.stdout:raise RuntimeError('Actual main-copy APK probe failed')
        report['status']='PASS'
    finally:(a.reports/'readahead-apk-probe.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
