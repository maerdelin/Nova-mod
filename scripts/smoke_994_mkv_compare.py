#!/usr/bin/env python3
"""Compare signed #993 and candidate startup on the SAME fixture/server/emulator.

Do not infer speed from a source marker. Both APKs actually launch and render
their first video frame, measured by native monotonic startup timestamps.
"""
import argparse
import hashlib
import http.server
import json
from pathlib import Path
import re
import statistics
import subprocess
import tempfile
import threading
import time
from smoke_direct_webdav import adb, run, logs, wait_for, PACKAGE, PLAYER


def install(apk):
    subprocess.run(["adb", "shell", "am", "force-stop", PACKAGE], capture_output=True)
    subprocess.run(["adb", "uninstall", PACKAGE], capture_output=True)
    # Match the proven clean-install smoke: -g grants runtime storage
    # permissions. Without it #993 opens GrantPermissionsActivity and the
    # benchmark waits for a frame that can never arrive.
    run(["adb", "install", "--no-streaming", "-r", "-g", str(apk)], timeout=180)
    if PACKAGE not in adb("shell", "pm", "list", "packages", PACKAGE):
        raise RuntimeError("APK installation not confirmed")


def build_fixture(root):
    srt = root / "tracks.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:03,000\nSubtitle track probe\n"
                   "\n2\n00:00:05,000 --> 00:00:08,000\nTrack still available\n")
    asset = root / "embedded-notes.txt"
    asset.write_text("NOVA 994 Matroska attachment probe\n")
    media = root / "benchmark.mkv"
    run(["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25",
         "-f", "lavfi", "-i", "sine=frequency=600:sample_rate=48000",
         "-i", str(srt), "-map", "0:v:0", "-map", "1:a:0", "-map", "2:s:0",
         "-t", "14", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-g", "25", "-b:v", "3M",
         "-c:a", "aac", "-b:a", "128k", "-c:s", "srt",
         "-attach", str(asset), "-metadata:s:t:0", "mimetype=text/plain",
         "-f", "matroska", str(media)], timeout=150)
    check = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(media)],
                           text=True, capture_output=True, timeout=20)
    parsed = check.stderr
    tracks = {
        "video": bool(re.search(r"Video:\s*h264", parsed, re.I)),
        "audio": bool(re.search(r"Audio:\s*aac", parsed, re.I)),
        "subtitle": bool(re.search(r"Subtitle:\s*subrip", parsed, re.I)),
        "attachment": "Attachment:" in parsed,
    }
    if not all(tracks.values()) or media.stat().st_size <= 1048576:
        raise RuntimeError("MKV four-stream fixture not verified: " + str(tracks))
    return media, tracks


def serve(media):
    size = media.stat().st_size
    counts = []
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *unused): pass
        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(size))
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
        def do_PROPFIND(self): self.send_error(404)
        def do_GET(self):
            if self.path.split("?", 1)[0] != "/benchmark.mkv":
                self.send_error(404)
                return
            value = self.headers.get("Range", "")
            m = re.fullmatch(r"bytes=(\d+)-(\d*)", value) if value else None
            if value and not m:
                self.send_error(416)
                return
            start = int(m[1]) if m else 0
            end = min(size-1, int(m[2])) if m and m[2] else size-1
            if start >= size or end < start:
                self.send_error(416)
                return
            # Identical bounded-Range stall for BOTH APKs: a CDN pattern
            # that penalizes speculative pre-frame downloads.
            bounded = bool(m and m[2])
            counts.append({"range":value, "bounded":bounded})
            if bounded: time.sleep(8.0)
            self.send_response(206 if m else 200)
            self.send_header("Content-Length", str(end-start+1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Type", "video/x-matroska")
            if m: self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                with media.open("rb") as f:
                    f.seek(start)
                    remaining=end-start+1
                    while remaining:
                        chunk=f.read(min(65536, remaining))
                        if not chunk:break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (OSError, BrokenPipeError, ConnectionResetError):
                pass
    class Server(http.server.ThreadingHTTPServer):
        daemon_threads=True
    server=Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, counts


def one_play(port, label, iteration, reports):
    adb("shell", "am", "force-stop", PACKAGE)
    adb("logcat", "-c")
    marker=f"NOVA_994_MKV_COMPARE_{label}_{iteration}_{time.monotonic_ns()}"
    adb("shell", "log", "-p", "i", "-t", "NOVA_MKV_COMPARE", marker)
    uri=f"webdav://127.0.0.1:{port}/benchmark.mkv"
    adb("shell", f"am start -W -n {PLAYER} -a android.intent.action.VIEW "
                 f"-d '{uri}' -t video/x-matroska", timeout=35)
    text=wait_for(lambda t: marker in t and
                  "NOVA_STARTUP_TRACE first_frame_sink" in t[t.rfind(marker):],
                  40, f"{label} signed APK real MKV first frame")
    scoped=text[text.rfind(marker):]
    opened=re.search(r"NOVA_STARTUP_TRACE open_begin t=(\d+)",scoped)
    frame=re.search(r"NOVA_STARTUP_TRACE first_frame_sink t=(\d+)",scoped)
    probe=re.search(r"NOVA_STARTUP_TRACE probe_done t=\d+ streams=(\d+)",scoped)
    if not (opened and frame and probe):
        raise RuntimeError(f"{label} missing actual open/frame/probe telemetry")
    elapsed=int(frame[1])-int(opened[1])
    if not 0<=elapsed<=40000:
        raise RuntimeError(f"{label} invalid native startup measurement {elapsed}")
    if "FATAL EXCEPTION" in scoped or "Fatal signal" in scoped:
        raise RuntimeError(f"{label} crashed")
    # FFmpeg reports playable streams (video/audio/subtitle); MKV attachments
    # may be exposed separately and should be validated from the container.
    if int(probe[1])<3:
        raise RuntimeError(f"{label} lost playable MKV streams: {probe[1]}")
    (reports/f"mkv-compare-{label}-{iteration}.log").write_text(scoped)
    return {"startup_ms":elapsed,"probed_streams":int(probe[1]),
            "first_frame":True,"real_signed_apk":True}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--apk",required=True,type=Path)
    ap.add_argument("--baseline-apk",required=True,type=Path)
    ap.add_argument("--reports",required=True,type=Path)
    args=ap.parse_args()
    args.reports.mkdir(parents=True, exist_ok=True)
    for path in (args.apk,args.baseline_apk):
        if not path.is_file() or path.stat().st_size<1000000:
            raise RuntimeError("Baseline and candidate signed APKs required")
    digest=hashlib.sha256(args.apk.read_bytes()).hexdigest()
    bdigest=hashlib.sha256(args.baseline_apk.read_bytes()).hexdigest()
    if digest==bdigest:
        raise RuntimeError("Benchmark baseline and candidate must be distinct")
    if adb("shell","getprop","ro.kernel.qemu").strip()!="1":
        raise RuntimeError("CI Android emulator required")
    with tempfile.TemporaryDirectory(prefix="nova-994-mkv-compare-") as td:
        media,streams=build_fixture(Path(td))
        server,requests=serve(media)
        port=server.server_port
        try:
            adb("reverse",f"tcp:{port}",f"tcp:{port}")
            measurements={"baseline":[],"candidate":[]}
            try:
                for label,apk in (("baseline",args.baseline_apk),
                                  ("candidate",args.apk)):
                    install(apk)
                    for idx in range(3):
                        measurements[label].append(one_play(port,label,idx,args.reports))
            finally:
                # Leave the exact candidate installed for later CI checks.
                install(args.apk)
            old=statistics.median(m["startup_ms"] for m in measurements["baseline"])
            new=statistics.median(m["startup_ms"] for m in measurements["candidate"])
            precision=args.reports/"precise-seek-signed-apk.json"
            if not precision.exists():
                raise RuntimeError("Missing independent signed candidate Seek regression")
            seek=json.loads(precision.read_text())
            seek_ok=(seek.get("status")=="PASS" and
                     seek.get("actual_renderer_submission") is True and
                     len(seek.get("checks",[]))>=3)
            if not seek_ok:
                raise RuntimeError("Signed candidate renderer-confirmed Seek regression absent")
            report={
                "status":"PASS" if old>new else "FAIL",
                "apk_sha256":digest,
                "baseline_apk_sha256":bdigest,
                "same_media_and_network_conditions":True,
                "mkv_stream_probe_and_seek_regression":seek_ok and all(streams.values()),
                "streams_in_fixture":streams,
                "actual_candidate_probe_streams":min(m["probed_streams"] for m in measurements["candidate"]),
                "baseline_median_startup_ms":old,
                "candidate_median_startup_ms":new,
                "samples":measurements,
                "media_bytes":media.stat().st_size,
                "same_emulator":True,
                "same_http_range_server":True,
                "bounded_range_fixed_delay_ms":8000,
                "scope":"real 4-stream MKV first frame and renderer-confirmed seek; not UI track-selection testing"
            }
            (args.reports/"994-mkv-startup-compare.json").write_text(json.dumps(report,indent=2)+"\n")
            if report["status"]!="PASS":
                raise RuntimeError("New signed APK did not beat #993 MKV startup under identical conditions: "+json.dumps({"baseline":old,"new":new}))
            print("NOVA_994_MKV_BASELINE_COMPARE=PASS "+json.dumps(report),flush=True)
        finally:
            try:adb("reverse","--remove",f"tcp:{port}")
            except Exception:pass
            server.shutdown()
            server.server_close()


if __name__=="__main__":
    main()
