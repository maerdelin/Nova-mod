#!/usr/bin/env python3
"""Signed APK on Android 11: OFF ISO percent must appear and spinner must hide.

Actual WebDAV Blu-ray ISO, real Settings checkbox and accessibility hierarchy.
Neither readiness nor result is inferred from disabled NOVA diagnostic logs.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shlex
import time
import xml.etree.ElementTree as ET

from smoke_iso_parallel_994 import serve_iso
from smoke_direct_webdav import adb, logs, PACKAGE, PLAYER
import smoke_global_logs_settings as settings
from smoke_global_logs_native_off import pid_lines, FORBIDDEN

def hierarchy():
    errors=[]
    for attempt in range(3):
        try:
            adb("shell","uiautomator","dump","/sdcard/nova1196-off-iso.xml",timeout=65)
            xml=adb("shell","cat","/sdcard/nova1196-off-iso.xml",timeout=20)
            start=xml.find("<?xml")
            if start<0:raise RuntimeError("uiautomator produced no XML")
            root=ET.fromstring(xml[start:])
            percents=[]
            for node in root.iter():
                if node.get("package")!=PACKAGE or node.get("class")!="android.widget.TextView":
                    continue
                match=re.fullmatch(r"([0-9]{1,3})%",node.get("text","").strip())
                if match and int(match.group(1))<=100:
                    percents.append(int(match.group(1)))
            return percents,xml
        except (RuntimeError,ET.ParseError) as exc:
            errors.append(f"{attempt}: {str(exc)[:400]}")
            time.sleep(0.35)
    raise RuntimeError("OFF ISO UI hierarchy unavailable: "+" | ".join(errors))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--iso",required=True,type=Path)
    parser.add_argument("--reports",required=True,type=Path)
    parser.add_argument("--timeout",type=int,default=125)
    args=parser.parse_args()
    args.reports.mkdir(parents=True,exist_ok=True)
    if not args.iso.is_file() or args.iso.stat().st_size<2097152:
        raise RuntimeError("Genuine Blu-ray ISO media fixture missing")
    report={"status":"FAIL","mode":"OFF real ISO","percent_samples":[],
            "percent_seen":False,"overlay_hidden":False,"checks":[]}
    server=None
    first_xml=None
    last_xml=None
    try:
        screen={"scroll_attempts":[]}
        item=settings.locate_with_scroll(screen)
        if settings.state(item):
            settings.tap(item)
            settings.expect_state(False,"OFF ISO acceptance setup")
        report["checks"].append("Real Settings checkbox OFF")
        # Slow a REAL HTTP fixture only so UiAutomator can see intermediate
        # progress despite its accessibility idle waits. No APK performance
        # constants or playback code are modified.
        server,requests=serve_iso(args.iso.resolve(),throttle_kibps=128)
        adb("reverse",f"tcp:{server.server_port}",f"tcp:{server.server_port}")
        adb("shell","am","force-stop",PACKAGE)
        adb("logcat","-c")
        uri=f"webdav://127.0.0.1:{server.server_port}/{args.iso.name}"
        launched=adb("shell",f"am start -W -n {PLAYER} -a android.intent.action.VIEW "
                             f"-d {shlex.quote(uri)} -t video/x-bluray-iso",timeout=50)
        if "Status: ok" not in launched:
            raise RuntimeError("PlayerActivity did not start real ISO: "+launched[-700:])
        pid=adb("shell","pidof",PACKAGE).strip().split()[0]
        start=time.monotonic()
        positive=False
        empty=0
        while time.monotonic()-start<args.timeout:
            observed,xml=hierarchy()
            if first_xml is None:first_xml=xml
            last_xml=xml
            if observed:
                positive=positive or any(value>0 for value in observed)
                report["percent_samples"].append(observed[-1])
                empty=0
            elif positive:
                empty+=1
                if empty>=3:
                    report["overlay_hidden"]=True
                    break
            time.sleep(0.5)
        report["elapsed_seconds"]=round(time.monotonic()-start,2)
        report["percent_seen"]=positive
        report["http_requests"]=len(requests)
        report["pid"]=pid
        new_pid=adb("shell","pidof",PACKAGE).strip().split()[0]
        if pid!=new_pid:raise RuntimeError("NOVA process restarted during OFF ISO")
        if not requests:raise RuntimeError("OFF ISO was never fetched")
        if not positive:raise RuntimeError("OFF ISO percent never appeared in accessible UI")
        if not report["overlay_hidden"]:
            raise RuntimeError("OFF ISO spinner never disappeared after positive percent")
        capture=logs()
        leaks=[line for line in pid_lines(capture,pid) if any(tag in line for tag in FORBIDDEN)]
        report["forbidden_app_logs"]=leaks[:15]
        if leaks:raise RuntimeError("OFF still emitted app diagnostics: "+"\n".join(leaks[:10]))
        if "FATAL EXCEPTION" in capture or "Fatal signal" in capture:
            raise RuntimeError("OFF ISO playback crashed")
        report["checks"]+=["real Blu-ray ISO fetch","positive displayed percent",
                           "three consecutive valid UI hierarchies with spinner absent",
                           "same running process","diagnostic silence"]
        report["status"]="PASS"
        print("NOVA_1196_OFF_ISO_UI_HIDE=PASS "+json.dumps(report),flush=True)
    finally:
        if first_xml is not None:(args.reports/"off-iso-first-ui.xml").write_text(first_xml)
        if last_xml is not None:(args.reports/"off-iso-last-ui.xml").write_text(last_xml)
        try:(args.reports/"off-iso-logcat.txt").write_text(logs())
        except Exception:pass
        (args.reports/"off-iso-ui.json").write_text(json.dumps(report,indent=2)+"\n")
        if server is not None:
            server.shutdown()
            server.server_close()

if __name__=="__main__":
    main()
