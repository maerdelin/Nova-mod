#!/usr/bin/env python3
"""Real signed APK: MKV first frame must not wait on a stalled 4MiB CDN Range.

Canonical open-ended GET is fast; bounded speculative CURL GET intentionally
stalls for 18 seconds (matching the failed redirect-after-302 pattern in the
2026-10-30 TV log). The correct early RAW/probe path uses canonical Java 206
until the *first video frame* and only then permits W2.
"""
import argparse
import http.server
import json
import re
import shlex
import tempfile
import threading
import time
from pathlib import Path

from smoke_direct_webdav import adb, logs, run, wait_for, PACKAGE, PLAYER

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--reports",type=Path,required=True)
    args=ap.parse_args()
    args.reports.mkdir(parents=True,exist_ok=True)
    report={"status":"FAIL","scope":"signed APK MKV first-frame while bounded CDN GET stalls"}
    server=None
    port=None
    try:
        if adb("shell","getprop","ro.kernel.qemu").strip()!="1":
            raise RuntimeError("Fresh Android emulator required")
        with tempfile.TemporaryDirectory(prefix="nova-startup-mkv-") as td:
            media=Path(td)/"startup.mkv"
            run(["ffmpeg","-y","-v","error",
                 "-f","lavfi","-i","testsrc2=size=640x360:rate=25",
                 "-f","lavfi","-i","sine=frequency=600:sample_rate=48000",
                 "-t","12","-c:v","libx264","-preset","ultrafast",
                 "-pix_fmt","yuv420p","-g","25","-b:v","3M",
                 "-c:a","aac","-b:a","128k","-f","matroska",media],timeout=90)
            size=media.stat().st_size
            if size<1048576:raise AssertionError("MKV fixture too small")
            lock=threading.Lock()
            requests=[]
            class Handler(http.server.BaseHTTPRequestHandler):
                protocol_version="HTTP/1.1"
                def log_message(self,*_):pass
                def do_GET(self):
                    if self.path.split("?",1)[0]!="/startup.mkv":
                        self.send_error(404);return
                    m=re.fullmatch(r"bytes=(\d+)-(\d*)",self.headers.get("Range",""))
                    if not m:
                        self.send_error(416);return
                    start=int(m[1])
                    end=min(size-1,int(m[2])) if m[2] else size-1
                    if start>=size or start>end:
                        self.send_error(416);return
                    bounded=bool(m[2])
                    with lock:
                        requests.append({"at":start,"end":end,"bounded":bounded,
                                         "monotonic":time.monotonic()})
                    # Simulates a CDN which never serves the speculative
                    # short request, while the canonical Java GET is healthy.
                    if bounded:time.sleep(18.0)
                    self.send_response(206)
                    self.send_header("Accept-Ranges","bytes")
                    self.send_header("Content-Length",str(end-start+1))
                    self.send_header("Content-Range",f"bytes {start}-{end}/{size}")
                    self.send_header("Content-Type","video/x-matroska")
                    self.send_header("Connection","close")
                    self.end_headers()
                    self.close_connection=True
                    try:
                        with media.open("rb") as f:
                            f.seek(start)
                            remaining=end-start+1
                            while remaining:
                                b=f.read(min(65536,remaining))
                                if not b:break
                                self.wfile.write(b)
                                remaining-=len(b)
                    except (BrokenPipeError,ConnectionResetError,OSError):
                        pass

            class Server(http.server.ThreadingHTTPServer):
                daemon_threads=True
            server=Server(("127.0.0.1",0),Handler)
            port=server.server_port
            threading.Thread(target=server.serve_forever,daemon=True).start()
            adb("reverse",f"tcp:{port}",f"tcp:{port}")
            adb("shell","am","force-stop",PACKAGE)
            adb("logcat","-c")
            marker="NOVA_MKV_FIRST_FRAME_"+str(time.monotonic_ns())
            adb("shell","log","-p","i","-t","NOVA_MKV_FIRST_FRAME_TEST",marker)
            uri=f"webdav://127.0.0.1:{port}/startup.mkv"
            adb("shell",f"am start -W -n {PLAYER} -a android.intent.action.VIEW "
                f"-d {shlex.quote(uri)} -t video/x-matroska",timeout=30)
            output=wait_for(lambda t:marker in t and
                "NOVA_STARTUP_MKV_FIRST_FRAME_READY" in t[t.rfind(marker):] and
                "NOVA_STARTUP_TRACE first_frame_sink" in t[t.rfind(marker):],
                40,"real MKV decoded first frame and native generation callback")
            tail=output[output.rfind(marker):]
            # Preserve the real test log on both success and failure.
            # AVOS serprintf can flush after native LOGI even when the native
            # callback is synchronous in the first-frame code path.
            (args.reports/"startup-mkv-canonical-first-logcat.txt").write_text(tail)
            if "FATAL EXCEPTION" in tail or "Fatal signal" in tail:
                raise RuntimeError("Startup APK crashed")
            if "NOVA_STARTUP_MKV_CANONICAL_FIRST_V1" not in tail:
                raise AssertionError("Canonical startup route was not exercised")
            if "NOVA_BOOT_RAW_SOURCE" not in tail:
                raise AssertionError("RAW did not download during startup")
            # Mandatory runtime acceptance: compiled string is NOT evidence.
            # This signed APK must execute staged MKV logic in the actual player.
            begin=re.search(r"NOVA_STAGED_DECODE_BEGIN first=65536\\b",tail)
            if not begin:
                raise AssertionError("MKV staged 64KB FIRST ROUND NOT EXECUTED by signed APK")
            endst=re.search(r"NOVA_STAGED_DECODE_(?:SUCCESS|HANDOFF)\\b",tail)
            if not endst or endst.start()<=begin.start():
                raise AssertionError("MKV staged decode has no real SUCCESS/HANDOFF")
            stage_events=re.findall(r"NOVA_STAGED_DECODE_RETRY threshold=(\\d+)",tail)
            for i in range(1,len(stage_events)):
                if int(stage_events[i])<=int(stage_events[i-1]):
                    raise AssertionError("MKV stage thresholds not increasing")
            # The original video renderer must STILL produce the real first frame.
            if tail.find("NOVA_STARTUP_TRACE first_frame_sink")<=endst.start():
                raise AssertionError("Actual first frame must follow staged packet handoff")
            probe=tail.find("NOVA_STARTUP_TRACE probe_done")
            first=tail.find("NOVA_STARTUP_TRACE first_frame_sink")
            ready=tail.find("NOVA_STARTUP_MKV_FIRST_FRAME_READY")
            if not (probe>=0 and probe<first and ready>=0):
                raise AssertionError(
                    f"Missing probe/first/native callback: probe={probe} first={first} ready={ready}"
                )
            curl=tail.find("NOVA_BOOT_CURL_BEGIN")
            if curl>=0 and curl<ready:
                raise AssertionError("The old stalled 4MiB CURL path ran before first frame")
            start=re.search(r"NOVA_STARTUP_TRACE open_begin t=(\d+)",tail)
            end=re.search(r"NOVA_STARTUP_TRACE first_frame_sink t=(\d+)",tail)
            if not start or not end:raise AssertionError("Native startup timestamps absent")
            elapsed=int(end[1])-int(start[1])
            if elapsed<0 or elapsed>12000:
                raise AssertionError(f"MKV first frame {elapsed} ms despite fast canonical GET")
            with lock:captured=list(requests)
            if not any(not x["bounded"] for x in captured):
                raise AssertionError("No real open-ended Java Range was served")
            report={"status":"PASS","media_bytes":size,"native_first_frame_ms":elapsed,
                    "first_frame_before_stalled_bounded_get":True,
                    "native_first_frame_signal":True,
                    "raw_source_observed":True,
                    "staged_decode_runtime":True,
                    "staged_decode_stage_events":stage_events,
                    "staged_decode_outcome":"SUCCESS" if "NOVA_STAGED_DECODE_SUCCESS" in tail else "HANDOFF",
                    "request_count":len(captured),"requests":captured[:16]}
            print("NOVA_STARTUP_MKV_FIRST_FRAME_PASS "+json.dumps(report),flush=True)
    finally:
        (args.reports/"startup-mkv-canonical-first.json").write_text(json.dumps(report,indent=2)+"\n")
        if port:
            try:adb("reverse","--remove",f"tcp:{port}")
            except Exception:pass
        if server:
            server.shutdown()
            server.server_close()

if __name__=="__main__":main()
