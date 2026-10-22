#!/usr/bin/env python3
"""Final-APK direct WebDAV transport smoke.

Uses a local HTTP Range server exposed to the emulator through adb reverse, but
launches Nova with a webdav:// URI. The final APK must translate only control
metadata in Java, open the upstream in libnova_transport, hand AVOS a
novatransport:// source, fill RAW128, and render a frame without StreamOverHttp
or either localhost media proxy.
"""
import argparse
import http.server
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import threading
import time

PACKAGE = "org.courville.nova"
PLAYER = PACKAGE + "/com.archos.mediacenter.video.player.PlayerActivity"

def run(args, timeout=60):
    p = subprocess.run(list(map(str,args)), capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError("Command failed: " + str(args[:5]) + "\n" + p.stdout + p.stderr)
    return p.stdout

def adb(*args, timeout=30):
    return run(["adb", *args], timeout=timeout)

def logs():
    return adb("logcat", "-d", "-v", "threadtime", timeout=20)

def wait_for(pred, seconds, label):
    end = time.monotonic() + seconds
    last = ""
    while time.monotonic() < end:
        last = logs()
        if pred(last):
            return last
        time.sleep(0.35)
    raise RuntimeError("Missing " + label + "\n" + last[-12000:])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", type=Path, required=True)
    args = ap.parse_args()
    args.reports.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "FAIL",
        "scope": "final APK webdav scheme -> native direct transport -> RAW128 -> first frame"
    }
    server = None
    port = None
    try:
        if adb("shell", "getprop", "ro.kernel.qemu").strip() != "1":
            raise RuntimeError("Fresh CI emulator required")
        with tempfile.TemporaryDirectory(prefix="nova-direct-webdav-") as td:
            root = Path(td)
            media = root / "direct.ts"
            run([
                "ffmpeg","-v","error",
                "-f","lavfi","-i","testsrc2=size=640x360:rate=25",
                "-f","lavfi","-i","sine=frequency=550:sample_rate=48000",
                "-t","60","-c:v","libx264","-preset","ultrafast",
                "-pix_fmt","yuv420p","-g","25","-b:v","3M",
                "-c:a","aac","-b:a","128k","-f","mpegts",media
            ], timeout=90)
            size = media.stat().st_size
            requests = []
            class Handler(http.server.BaseHTTPRequestHandler):
                protocol_version = "HTTP/1.1"
                def log_message(self, *_): pass
                def do_GET(self):
                    if self.path.split("?",1)[0] != "/direct.ts":
                        self.send_error(404); return
                    start = 0
                    end = size - 1
                    partial = False
                    value = self.headers.get("Range")
                    if value:
                        m = re.fullmatch(r"bytes=(\d+)-(\d*)", value)
                        if not m:
                            self.send_error(416); return
                        start = int(m.group(1))
                        end = min(size-1, int(m.group(2))) if m.group(2) else size-1
                        partial = True
                    if start > end or start >= size:
                        self.send_error(416); return
                    requests.append(start)
                    self.send_response(206 if partial else 200)
                    self.send_header("Content-Type","video/mp2t")
                    self.send_header("Accept-Ranges","bytes")
                    self.send_header("Content-Length",str(end-start+1))
                    if partial:
                        self.send_header("Content-Range",f"bytes {start}-{end}/{size}")
                    self.send_header("Connection","close")
                    self.end_headers()
                    try:
                        with media.open("rb") as f:
                            f.seek(start)
                            left = end-start+1
                            while left:
                                chunk = f.read(min(left, 65536))
                                if not chunk: break
                                self.wfile.write(chunk)
                                left -= len(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

            server = http.server.ThreadingHTTPServer(("127.0.0.1",0), Handler)
            port = server.server_port
            threading.Thread(target=server.serve_forever, daemon=True).start()
            adb("reverse", f"tcp:{port}", f"tcp:{port}")
            adb("shell", "am", "force-stop", PACKAGE)
            adb("logcat", "-c")
            uri = f"webdav://127.0.0.1:{port}/direct.ts"
            adb("shell",
                f"am start -W -n {PLAYER} -a android.intent.action.VIEW "
                f"-d {shlex.quote(uri)} -t video/mp2t", timeout=30)

            text = wait_for(
                lambda t: (
                    "NovaTransport" in t
                    and "OPEN_READY mode=file" in t
                    and "NOVA_DIRECT_SOURCE_OPEN:" in t
                    and "NOVA_RAW128_OPEN: phase=pre_probe" in t
                    and "first_frame_sink" in t
                ),
                40,
                "direct WebDAV transport open, RAW128 and first frame",
            )
            if "Unable to open direct native transport" in text:
                raise RuntimeError("Direct transport proxy reported open failure")
            if "BlurayIsoProxy" in text or "libnova_iso" in text:
                raise RuntimeError("Legacy ISO transport appeared at runtime")
            if "http://localhost:" in text:
                raise RuntimeError("Legacy localhost media proxy appeared at runtime")

            # Exercise the new data plane itself, not the removed localhost ISO
            # bridge. Establish DPAD focus, then require an actual player seek
            # to reach both RAW generation invalidation and native upstream seek.
            adb("shell", "input", "keyevent", "20")
            time.sleep(0.4)
            adb("shell", "input", "keyevent", "20")
            time.sleep(0.4)
            seek_marker = "NOVA_DIRECT_SEEK_" + str(time.monotonic_ns())
            adb("shell", "log", "-p", "i", "-t", "NOVA_DIRECT_TEST", seek_marker)
            adb("shell", "input", "keyevent", "22")
            text = wait_for(
                lambda t: (
                    seek_marker in t
                    and "NOVA_RAW128_SEEK:" in t[t.rfind(seek_marker):]
                    and "NovaTransport: SEEK generation=" in t[t.rfind(seek_marker):]
                ),
                20,
                "direct WebDAV seek through RAW128 and native upstream",
            )

            # BACK must abort the one native session immediately. No old
            # post-shutdown RAW retry loop is allowed to appear afterwards.
            back_marker = "NOVA_DIRECT_BACK_" + str(time.monotonic_ns())
            adb("shell", "log", "-p", "i", "-t", "NOVA_DIRECT_TEST", back_marker)
            adb("shell", "input", "keyevent", "4")
            text = wait_for(
                lambda t: (
                    back_marker in t
                    and "NovaTransport: ABORT generation=" in t[t.rfind(back_marker):]
                ),
                15,
                "direct transport abort after BACK",
            )
            back_tail = text[text.rfind(back_marker):]
            if "NOVA_RAW_RETRY:" in back_tail:
                raise RuntimeError("RAW retry occurred after direct transport BACK abort")

            report.update(
                status="PASS",
                webdav_uri=True,
                native_transport=True,
                direct_avio=True,
                raw128=True,
                first_frame=True,
                direct_seek=True,
                back_abort=True,
                post_abort_raw_retry=False,
                request_count=len(requests),
                request_starts=requests[:16],
            )
            print("DIRECT_WEBDAV_TRANSPORT_SMOKE=PASS " + json.dumps(report))
            (args.reports / "direct-webdav-logcat.txt").write_text(text)
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        try:
            (args.reports / "direct-webdav-last-logcat.txt").write_text(logs())
        except Exception:
            pass
        try:
            adb("shell","am","force-stop",PACKAGE)
        except Exception:
            pass
        if port:
            try:
                adb("reverse","--remove",f"tcp:{port}")
            except Exception:
                pass
        if server:
            server.shutdown(); server.server_close()
        (args.reports / "direct-webdav.json").write_text(json.dumps(report, indent=2) + "\n")

if __name__ == "__main__":
    main()
