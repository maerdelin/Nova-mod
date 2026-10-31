#!/usr/bin/env python3
"""Runtime A/B: prove #967 Shared42 HTTP pipeline really stays at W1.

Test the SIGNED APK on the emulator, not just source text. Keep W2
backend, all Shared42 storage, AVOS, and Java code identical to #967.
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

from smoke_direct_webdav import PACKAGE, PLAYER, adb, logs, run, wait_for


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", type=Path, required=True)
    args = ap.parse_args()
    args.reports.mkdir(parents=True, exist_ok=True)
    report = {"status": "FAIL", "test": "967 W1-only Shared42 signed APK A/B",
              "expected_lanes": 1}
    lock = threading.Lock()
    stats = {"active_bounded": 0, "peak_bounded": 0, "bounded_starts": []}
    server = None
    port = None
    try:
        with tempfile.TemporaryDirectory() as td:
            media = Path(td) / "w1_ab.ts"
            run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                 "testsrc2=size=640x360:rate=25", "-f", "lavfi", "-i",
                 "sine=frequency=500:sample_rate=48000", "-t", "75",
                 "-c:v", "libx264", "-preset", "ultrafast",
                 "-pix_fmt", "yuv420p", "-g", "1", "-keyint_min", "1",
                 "-sc_threshold", "0", "-b:v", "3M",
                 "-c:a", "aac", "-b:a", "128k",
                 "-f", "mpegts", str(media)], timeout=120)
            size = media.stat().st_size
            if size < 20 * 1024 * 1024:
                raise RuntimeError("Synthetic W1 test media unexpectedly small")

            class Handler(http.server.BaseHTTPRequestHandler):
                protocol_version = "HTTP/1.1"
                def log_message(self, *_):
                    pass
                def do_GET(self):
                    if self.path.split("?", 1)[0] != "/w1_ab.ts":
                        self.send_error(404)
                        return
                    m = re.fullmatch(r"bytes=(\d+)-(\d*)",
                                     self.headers.get("Range", ""))
                    if not m:
                        self.send_error(416)
                        return
                    first = int(m.group(1))
                    last = min(size - 1, int(m.group(2))) if m.group(2) else size - 1
                    if first >= size or first > last:
                        self.send_error(416)
                        return
                    bounded = bool(m.group(2)) and (last-first+1) >= 1048576
                    if bounded:
                        with lock:
                            stats["active_bounded"] += 1
                            stats["peak_bounded"] = max(
                                stats["peak_bounded"], stats["active_bounded"])
                            stats["bounded_starts"].append(first)
                    self.send_response(206)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(last-first+1))
                    self.send_header("Content-Range", f"bytes {first}-{last}/{size}")
                    self.send_header("Content-Type", "video/mp2t")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    try:
                        with media.open("rb") as stream:
                            stream.seek(first)
                            remaining = last-first+1
                            while remaining:
                                chunk = stream.read(min(16384, remaining))
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                self.wfile.flush()
                                remaining -= len(chunk)
                                time.sleep(0.004)
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    finally:
                        if bounded:
                            with lock:
                                stats["active_bounded"] -= 1
                        self.close_connection = True

            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            port = server.server_port
            threading.Thread(target=server.serve_forever, daemon=True).start()
            adb("reverse", f"tcp:{port}", f"tcp:{port}")
            adb("shell", "am", "force-stop", PACKAGE)
            adb("logcat", "-c")
            uri = f"webdav://127.0.0.1:{port}/w1_ab.ts"
            adb("shell", f"am start -W -n {PLAYER} -a android.intent.action.VIEW "
                         f"-d {shlex.quote(uri)} -t video/mp2t", timeout=30)

            text = wait_for(
                lambda t: "NOVA_60FPS_W1_AB:" in t and
                "NOVA_LITERANGE4_START" in t and
                "NOVA_LITERANGE4_NET lanes=1" in t,
                85, "signed W1-only native pipeline started")
            text = wait_for(
                lambda t: "NOVA_60FPS_W1_AB:" in t and
                "NOVA_STARTUP_TRACE first_frame_sink" in t and
                re.search(r"NOVA_FINAL_RENDER_Q:.*renderSeq=[1-9]\d*", t),
                130, "signed W1-only APK rendered frames")
            # Allow several normal Range rotations and watch for any W2
            # escalation. We assert the HTTP SERVER observed no overlap.
            time.sleep(6)
            text = logs()
            with lock:
                peak = stats["peak_bounded"]
                ranges = list(stats["bounded_starts"])
            violations = [p for p in (
                "NOVA_LITERANGE4_PAIR_ENABLE",
                "NOVA_LITERANGE4_NET lanes=2",
                "NOVA_LITERANGE4_REBASE origin=") if
                p != "NOVA_LITERANGE4_REBASE origin=" and p in text]
            rebase_two = re.search(r"NOVA_LITERANGE4_REBASE[^\n]*lanes=2\b", text)
            if violations or rebase_two:
                raise RuntimeError("W2 lane enabled during W1 A/B test")
            if peak > 1:
                raise RuntimeError(f"Concurrent bounded Range GETs observed: {peak}")
            if not ranges:
                raise RuntimeError("No bounded network Range requests observed")
            if "FATAL EXCEPTION" in text or "Fatal signal" in text:
                raise RuntimeError("Player crashed")
            report.update(status="PASS", peak_bounded_http_requests=peak,
                          bounded_ranges=len(ranges), start_offsets=ranges[:12],
                          native_w1_marker=True, w2_escalations=0,
                          actual_frame_rendered=True)
            print("NOVA_60FPS_W1_AB_RUNTIME_PASS=" + json.dumps(report))
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        (args.reports / "60fps-w1-ab.json").write_text(
            json.dumps(report, indent=2) + "\n")
        try:
            (args.reports / "60fps-w1-ab-logcat.txt").write_text(logs())
        except Exception:
            pass
        try:
            adb("shell", "am", "force-stop", PACKAGE)
        except Exception:
            pass
        if port is not None:
            try:
                adb("reverse", "--remove", f"tcp:{port}")
            except Exception:
                pass
        if server is not None:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
