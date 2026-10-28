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
    # Show player-specific evidence rather than only noisy emulator logcat tail.
    interesting = [line for line in last.splitlines() if any(marker in line for marker in (
        "NovaTransport", "NOVA_", "AvosMediaPlayer", "PlayerActivity",
        "ActivityTaskManager", "FATAL EXCEPTION", "Fatal signal",
        "libavos", "libnova_transport", "AndroidRuntime"))]
    raise RuntimeError("Missing " + label + "\nAPP_LOG_FILTERED:\n" +
                       "\n".join(interesting[-120:]) + "\nRAW_TAIL:\n" + last[-3000:])

def action_tail(text, marker):
    return text[text.rfind(marker):] if marker in text else ""

def back_close_complete(text, marker, generation):
    tail = action_tail(text, marker)
    abort = re.search(rf"NovaTransport: ABORT generation={generation}(?!\d)", tail)
    close = re.search(rf"NovaTransport: CLOSE generation={generation} complete=1", tail)
    return bool(abort and close and abort.start() < close.start())

def reopened_frame(text, marker, previous_generation):
    tail = action_tail(text, marker)
    opened = re.search(r"OPEN_READY mode=file generation=(\d+)", tail)
    if not opened or int(opened[1]) <= previous_generation:
        return False
    tail = tail[opened.end():]
    return ("NOVA_DIRECT_SOURCE_OPEN:" in tail
            and "NOVA_RAW128_OPEN: phase=pre_probe" in tail
            and "first_frame_sink" in tail)

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
            if ("java.lang.VerifyError" in text
                    or "Verifier rejected class" in text
                    or "FATAL EXCEPTION: main" in text):
                raise RuntimeError("PlayerActivity VerifyError or FATAL during playback")

            # The signed APK must actually emit the new cold-start trace from
            # its native hardware rendering path, not merely compile the text.
            trace = wait_for(
                lambda t: (
                    "NOVA_SYNC_BOOT:" in t
                    and "NOVA_SYNC_RENDER_CLOCK:" in t
                ),
                20, "new startup timebase trace and renderer clock snapshot",
            )
            report["native_clock_trace"] = True
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
                    and "NOVA_SYNC_SEEK_RESET:" in t[t.rfind(seek_marker):]
                ),
                20,
                "direct WebDAV seek through RAW128 and native upstream",
            )
            # Old smoke passed despite #890/#891 precise-seek error 1001.
            # A valid roundtrip requires actual target presentation and zero
            # fatal errors before testing BACK and same-process reopen.
            text = wait_for(
                lambda t: ("NOVA_PRECISE_SEEK_DONE_V1:" in t[t.rfind(seek_marker):]
                           or "NOVA_PRECISE_SEEK_GAP_V1:" in t[t.rfind(seek_marker):]
                           or "Error (1001,1000)" in t[t.rfind(seek_marker):]),
                35, "precise Seek completion or failure event")
            seek_tail = text[text.rfind(seek_marker):]
            if ("NOVA_PRECISE_SEEK_GAP_V1:" in seek_tail or
                    "Error (1001,1000)" in seek_tail or
                    "NOVA_PRECISE_SEEK_DONE_V1:" not in seek_tail):
                raise RuntimeError("Precise WebDAV seek failed, even if transport later reopens")
            # Scope both BACK presses to one action window: an asynchronous
            # close from the first press must not be discarded at the second.
            generation = int(re.findall(
                r"OPEN_READY mode=file generation=(\d+)", text)[-1])
            back_marker = "NOVA_DIRECT_BACK_" + str(time.monotonic_ns())
            adb("shell", "log", "-p", "i", "-t", "NOVA_DIRECT_TEST", back_marker)
            back_presses = 0
            for _ in range(2):
                adb("shell", "input", "keyevent", "4")
                back_presses += 1
                time.sleep(1.0)
                text = logs()
                if back_close_complete(text, back_marker, generation):
                    break
            text = wait_for(
                lambda t: back_close_complete(t, back_marker, generation),
                15, "direct transport abort AND completed close after BACK",
            )
            # Observe after close too, rather than passing on the first log.
            time.sleep(2.0)
            text = logs()
            back_tail = text[text.rfind(back_marker):]
            if "NOVA_RAW_RETRY:" in back_tail:
                raise RuntimeError("RAW retry occurred after direct transport BACK abort")
            if "FATAL EXCEPTION" in back_tail or "Fatal signal" in back_tail:
                raise RuntimeError("Player crashed during BACK teardown")

            if "Error (1001,1000)" in text[text.rfind(seek_marker):]:
                raise RuntimeError("Fatal seek error before direct transport re-open")
            # A second video open in the same process catches stale closed
            # generations that a one-shot first-frame smoke cannot detect.
            reopen_marker = "NOVA_DIRECT_REOPEN_" + str(time.monotonic_ns())
            adb("shell", "log", "-p", "i", "-t", "NOVA_DIRECT_TEST", reopen_marker)
            adb("shell",
                f"am start -W -n {PLAYER} -a android.intent.action.VIEW "
                f"-d {shlex.quote(uri)} -t video/mp2t", timeout=30)
            text = wait_for(
                lambda t: reopened_frame(t, reopen_marker, generation),
                40, "second WebDAV open and first frame after completed close",
            )

            report.update(
                status="PASS",
                webdav_uri=True,
                native_transport=True,
                direct_avio=True,
                raw128=True,
                first_frame=True,
                direct_seek=True,
                back_abort=True,
                back_close_complete=True,
                reopen_first_frame=True,
                first_frame_trace=True,
                seek_reset_trace=True,
                back_presses=back_presses,
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
