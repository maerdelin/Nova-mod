#!/usr/bin/env python3
"""Release gate: real signed APK Sardine PUT on Android ART, loopback only."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
PACKAGE="org.courville.nova"

def run(args,timeout=90):
    p=subprocess.run([str(x) for x in args],capture_output=True,text=True,timeout=timeout)
    if p.returncode:raise RuntimeError(f"command failed ({p.returncode}): {args[:3]}\n{p.stdout}\n{p.stderr}")
    return p.stdout

def latest(root,pattern):
    found=sorted(root.glob(pattern))
    if not found:raise RuntimeError("Missing SDK component "+str(root))
    return found[-1]

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("apk",type=Path)
    ap.add_argument("--reports",type=Path,required=True)
    args=ap.parse_args();args.reports.mkdir(parents=True,exist_ok=True)
    report={"status":"FAIL","scope":"actual final signed APK Sardine put(String,File,String), Android ART loopback only; not real cloud","expected_resume_remote_requests":0,"expected_normal_webdav_puts":1,"local_database_code_changed":False}
    try:
        if run(["adb","shell","getprop","ro.kernel.qemu"]).strip()!="1":
            raise RuntimeError("Only a clean CI emulator is supported")
        paths=run(["adb","shell","pm","path",PACKAGE]).splitlines()
        bases=[x[len("package:"):] for x in paths if x.startswith("package:") and x.endswith("/base.apk")]
        if len(bases)!=1:raise RuntimeError("Expected installed base.apk: "+repr(paths))
        sdk=Path(os.environ["ANDROID_HOME"]);build=latest(sdk/"build-tools","*")
        android=latest(sdk/"platforms","android-*")/"android.jar"
        with tempfile.TemporaryDirectory(prefix="nova-resume-local-") as tmp:
            root=Path(tmp);classes=root/"classes";dex=root/"dex";classes.mkdir();dex.mkdir()
            run(["javac","-source","8","-target","8","-cp",android,"-d",classes,ROOT/"tests/android/ResumeLocalOnlyApkProbe.java"],45)
            run([build/"d8","--min-api","23","--lib",android,"--output",dex]+sorted(classes.rglob("*.class")),60)
            jar=root/"nova-resume-probe.jar"
            with zipfile.ZipFile(jar,"w") as archive:archive.write(dex/"classes.dex","classes.dex")
            run(["adb","push",jar,"/data/local/tmp/nova-resume-probe.jar"],60)
            cmd=(f"CLASSPATH={shlex.quote(bases[0])}:/data/local/tmp/nova-resume-probe.jar "
                 "app_process /system/bin nova.test.ResumeLocalOnlyApkProbe")
            p=subprocess.run(["adb","shell",cmd],capture_output=True,text=True,timeout=120)
            combined=p.stdout+p.stderr
            (args.reports/"resume-local-only-art.txt").write_text(combined)
            print(combined,flush=True)
            for phrase in ("RESUME_REMOTE_REQUESTS=0","NORMAL_WEBDAV_PUT_REQUESTS=1",
                           "LOCAL_INPUT_INTACT=1","RESUME_LOCAL_ONLY_FINAL_APK_PROBE=PASS"):
                if p.returncode!=0 or phrase not in combined:
                    raise RuntimeError(f"ART signed-APK local-only check failed ({phrase}): {combined[-1800:]}")
            report.update({"status":"PASS","remote_resume_requests":0,
                           "ordinary_webdav_put_requests":1,"local_test_file_intact":True})
    except Exception as e:report["error"]=str(e);raise
    finally:
        (args.reports/"resume-local-only-art.json").write_text(json.dumps(report,indent=2)+"\n")
        print("RESUME_LOCAL_ONLY_ART_REPORT="+report["status"])

if __name__=="__main__":main()
