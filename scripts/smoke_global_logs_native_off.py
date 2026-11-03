#!/usr/bin/env python3
"""Android 11: prove native AVOS/Transport/Java log silence during real OFF playback.

Uses the same real signed APK as the WebDAV ON smoke. No root, preference
writes, artificial log filtering, or mocked AVOS playback. Restores ON using
the real Settings checkbox, so subsequent smoke_direct_webdav proves ON.
"""
import argparse
import http.server
import json
import re
import shlex
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import smoke_global_logs_settings as ui

PACKAGE = "org.courville.nova"
PLAYER = PACKAGE + "/com.archos.mediacenter.video.player.PlayerActivity"
FORBIDDEN = ("NOVA_", "NovaTransport", "avos_player", "libavos", "LibAvos",
             "SubEngineRegistry", "SubEngineJNI")


def adb(*args, timeout=40):
    return ui.adb(*args, timeout=timeout)


def run(*args, timeout=80):
    proc = subprocess.run(list(map(str, args)), stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(f"Command {args[:4]} failed: {proc.stdout[-2000:]}")
    return proc.stdout


def off_ui(result):
    item = ui.locate_with_scroll(result)
    if not ui.state(item):
        return
    ui.tap(item)
    ui.expect_state(False, "native OFF playback setup")


def on_ui(result):
    item = ui.locate_with_scroll(result)
    if ui.state(item):
        return
    ui.tap(item)
    ui.expect_state(True, "native OFF playback cleanup")


def pid_lines(data, pid):
    # threadtime: MM-DD HH:MM:SS.mmm PID TID L TAG: message
    for line in data.splitlines():
        parts = re.match(r"^\d\d-\d\d\s+\d\d:\d\d:\d\d\.\d+\s+(\d+)\s+\d+\s+[VDIWEF]\s+", line)
        if parts and parts.group(1) == str(pid):
            yield line


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", required=True, type=Path)
    a = ap.parse_args()
    a.reports.mkdir(parents=True, exist_ok=True)
    report = {"status": "FAIL", "native_off": "NOT_TESTED",
              "runtime": "signed APK + actual local WebDAV TS playback", "scroll_attempts": []}
    server = None
    should_restore = False
    try:
        with tempfile.TemporaryDirectory(prefix="nova-gate-off-") as d:
            media = Path(d) / "off.ts"
            run("ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
                "-f", "lavfi", "-i", "sine=frequency=550:sample_rate=48000",
                "-t", "16", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-g", "24", "-b:v", "1M",
                "-c:a", "aac", "-b:a", "64k", "-f", "mpegts", media, timeout=90)
            if media.stat().st_size < 200000:
                raise RuntimeError("Synthetic video unexpectedly small")
            size = media.stat().st_size
            requests = []
            class Handler(http.server.BaseHTTPRequestHandler):
                protocol_version = "HTTP/1.1"
                def log_message(self, *_): pass
                def do_HEAD(self):
                    self.send_response(200)
                    self.send_header("Content-Length", str(size))
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Connection", "close")
                    self.end_headers()
                def do_GET(self):
                    if self.path.split("?",1)[0] != "/off.ts":
                        self.send_error(404)
                        return
                    header = self.headers.get("Range", "")
                    match = re.fullmatch(r"bytes=(\d+)-(\d*)", header) if header else None
                    if header and not match:
                        self.send_error(416)
                        return
                    start = int(match.group(1)) if match else 0
                    end = min(size-1,int(match.group(2))) if match and match.group(2) else size-1
                    if start > end or start >= size:
                        self.send_error(416)
                        return
                    requests.append({"range":header,"start":start})
                    self.send_response(206 if match else 200)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Type", "video/mp2t")
                    self.send_header("Content-Length", str(end-start+1))
                    if match:
                        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    try:
                        with media.open("rb") as source:
                            source.seek(start)
                            left = end-start+1
                            while left:
                                block = source.read(min(left,65536))
                                if not block: break
                                self.wfile.write(block)
                                left-=len(block)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
            server = http.server.ThreadingHTTPServer(("127.0.0.1",0),Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            port=server.server_port
            adb("reverse",f"tcp:{port}",f"tcp:{port}")
            off_ui(report)
            should_restore = True
            adb("shell","am","force-stop",PACKAGE)
            adb("logcat","-c")
            uri=f"webdav://127.0.0.1:{port}/off.ts"
            opened=adb("shell",f"am start -W -n {PLAYER} -a android.intent.action.VIEW -d {shlex.quote(uri)} -t video/mp2t",timeout=40)
            if "Status: ok" not in opened:
                raise RuntimeError("PlayerActivity did not launch: " + opened)
            time.sleep(13)
            pid = adb("shell","pidof",PACKAGE).strip().split()[0]
            logcat=adb("logcat","-d","-v","threadtime",timeout=30)
            (a.reports/"global-logs-off-playback.txt").write_text(logcat)
            active=any(("Displayed " + PLAYER) in line or
                       "wm_on_resume_called" in line and "PlayerActivity" in line
                       for line in logcat.splitlines())
            if not active or not requests:
                raise RuntimeError(f"OFF video not proven active (activity={active}, GETs={len(requests)})")
            leaks=[line for line in pid_lines(logcat,pid)
                   if any(tag in line for tag in FORBIDDEN)]
            report["pid"]=pid
            report["requests"]=requests
            report["application_log_leaks"]=leaks[:30]
            if leaks:
                raise RuntimeError("Application diagnostics still emitted while OFF: " + "\n".join(leaks[:10]))
            report["native_off"]="PASS"
            adb("shell","am","force-stop",PACKAGE)
            on_ui(report)
            should_restore = False
            report["status"]="PASS"
            print("NOVA_GLOBAL_LOGS_NATIVE_OFF_REAL_PLAYBACK=PASS")
    finally:
        if should_restore:
            try:
                adb("shell","am","force-stop",PACKAGE)
                on_ui(report)
            except Exception as exc:
                report["restore_error"]=str(exc)
        if server:
            server.shutdown()
            server.server_close()
        (a.reports/"global-logs-native-off.json").write_text(
            json.dumps(report,ensure_ascii=False,indent=2)+"\n")


if __name__ == "__main__":
    main()
