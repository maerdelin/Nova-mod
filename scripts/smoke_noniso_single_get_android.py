#!/usr/bin/env python3
"""Android-run *actual Smali* single-GET Range and cross-origin auth smoke.

Uses one-use redirect tokens. A Run687 probe GET consumes the token and
gets HTTP 403 when the data GET follows; the redesigned code must succeed.
Run from GitHub's Android 11 emulator step with adb connected.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOTAL=2509221119
AUTH="TokenDemo"
OFFSETS=(0,468704976,2509203926)

class State:
    def __init__(self):
        self.lock=threading.Lock()
        self.next_token=0
        self.used=set()
        self.records=[]

STATE=State()

class Base(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"
    def log_message(self,*args):pass
    def out(self,status,extra=None,data=b""):
        self.send_response(status)
        for k,v in (extra or {}).items():self.send_header(k,v)
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        if data:self.wfile.write(data)

class Origin(Base):
    def do_GET(self):
        if self.path!="/dav/media.mkv":
            self.out(404);return
        ok=self.headers.get("Authorization")==AUTH
        with STATE.lock:
            STATE.next_token+=1
            token=STATE.next_token
            STATE.records.append({"phase":"origin","token":token,
                "authorized":ok,"range":self.headers.get("Range")})
        if not ok:
            self.out(401);return
        self.out(302,{"Location":f"http://10.0.2.2:{self.server.token_port}/token/{token}"})

class Token(Base):
    def do_GET(self):
        m=re.fullmatch(r"/token/(\d+)",self.path)
        if not m:
            self.out(404);return
        token=int(m[1])
        range_header=self.headers.get("Range","")
        mr=re.fullmatch(r"bytes=(\d+)-",range_header)
        with STATE.lock:
            reused=token in STATE.used
            STATE.used.add(token)
            leaked=bool(self.headers.get("Authorization"))
            STATE.records.append({"phase":"token","token":token,
                "reused":reused,"auth_leaked":leaked,"range":range_header})
        if reused or leaked or not mr:
            self.out(403);return
        off=int(mr[1])
        if off>=TOTAL:
            self.out(416,{"Content-Range":f"bytes */{TOTAL}"});return
        self.out(206,{
            "Accept-Ranges":"bytes",
            "Content-Range":f"bytes {off}-{off}/{TOTAL}"},
            bytes([off%251]))

def run(apk,report):
    origin=ThreadingHTTPServer(("0.0.0.0",0),Origin)
    token=ThreadingHTTPServer(("0.0.0.0",0),Token)
    origin.token_port=token.server_port
    for srv in (origin,token):
        srv.daemon_threads=True
        threading.Thread(target=srv.serve_forever,daemon=True).start()
    try:
        subprocess.run(["adb","push",str(apk),"/data/local/tmp/nova-singleget.apk"],
                       check=True,timeout=120,capture_output=True,text=True)
        # Android 11 emulator memory can retain the prior two-launch player.
        # Keep the Smali verifier isolated from the native RAW128 process.
        subprocess.run(["adb","shell","am","force-stop","org.courville.nova"],
                       capture_output=True,text=True,timeout=20,check=False)
        results=[]
        for offset in OFFSETS:
            url=f"http://10.0.2.2:{origin.server_port}/dav/media.mkv"
            args=["adb","shell","env",
                  "CLASSPATH=/data/local/tmp/nova-singleget.apk",
                  "app_process","/system/bin",
                  "com.archos.mediacenter.video.player.DirectRangeHttp",
                  url,AUTH,str(offset),str(offset%251)]
            r=subprocess.run(args,capture_output=True,text=True,timeout=45)
            if r.returncode==137:
                # Only a SIGKILL may be retried, never HTTP/Smali failures.
                print(f"ANDROID_APP_PROCESS_KILLED: offset={offset}; memory retry once",
                      flush=True)
                subprocess.run(["adb","shell","am","force-stop","org.courville.nova"],
                               capture_output=True,text=True,timeout=20,check=False)
                time.sleep(2.0)
                r=subprocess.run(args,capture_output=True,text=True,timeout=45)
            results.append({"offset":offset,"exit":r.returncode,
                            "stdout":r.stdout[-2000:],"stderr":r.stderr[-2000:]})
            if r.returncode or "NOVA_SINGLE_GET_ANDROID_PASS" not in r.stdout:
                raise AssertionError(f"Live Smali Range at {offset} failed: {results[-1]}")
        assert len(STATE.records)==len(OFFSETS)*2,STATE.records
        for r in STATE.records:
            if r["phase"]=="origin":
                assert r["authorized"] and r["range"].startswith("bytes="),r
            else:
                assert not r["reused"] and not r["auth_leaked"],r
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps({"status":"PASS","offsets":list(OFFSETS),
                           "records":STATE.records,"android":results},indent=2))
        print("NOVA_NONISO_SINGLE_GET_ANDROID_PASS: one-use redirects, 64-bit offsets, credential isolation")
    finally:
        for srv in (origin,token):
            srv.shutdown();srv.server_close()

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("apk",type=Path)
    p.add_argument("--reports",type=Path,default=Path("reports"))
    a=p.parse_args()
    run(a.apk,a.reports/"noniso-single-get-android.json")
