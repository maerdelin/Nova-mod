#!/usr/bin/env python3
"""Final signed APK weak-WebDAV first-frame acceptance for MKV and MP4.

This intentionally exercises webdav:// -> Java redirect resolution -> native
DirectTransport -> RAW128 -> FFmpeg -> actual video render, rather than testing
plain HTTP playback or a mocked C helper.

Faults per format:
  1) first Range 0-0 probe returns HTTP 503 (Java background retry)
  2) first real media Range response closes early (native reconnect/resume)
Both faults MUST be observed on the server and a frame MUST be rendered.
"""
import argparse
import http.server
import json
from pathlib import Path
import re
import shlex
import socket
import subprocess
import tempfile
import threading
import time

from smoke_direct_webdav import adb, logs, wait_for, PACKAGE, PLAYER, run


def create_video(media, fmt):
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=740:sample_rate=48000",
        "-t", "14", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-g", "25", "-b:v", "5M",
        "-c:a", "aac", "-b:a", "128k",
    ]
    if fmt == "mp4":
        cmd += ["-f", "mp4", str(media)]
    else:
        cmd += ["-f", "matroska", str(media)]
    run(cmd, timeout=110)
    if media.stat().st_size < 1024 * 1024:
        raise RuntimeError("Generated media is unexpectedly small")


def test_one(fmt, root, report_dir):
    media = root / ("weak." + fmt)
    create_video(media, fmt)
    size = media.stat().st_size
    lock = threading.Lock()
    requests = []
    all_requests = []
    faults = {"probe_503": 0, "short_body": 0}
    # MKV: issuing two GETs on one signed URL must produce HTTP 403.
    # DirectRangeHttp must follow the redirect within the SAME data GET.
    oneuse_next = 0
    oneuse_used = set()
    oneuse_records = []
    server = None
    port = None

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def do_HEAD(self):
            with lock:
                all_requests.append({"method": "HEAD", "path": self.path, "range": self.headers.get("Range", "")})
            if self.path.split("?", 1)[0] != "/" + media.name:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

        def do_PROPFIND(self):
            with lock:
                all_requests.append({"method": "PROPFIND", "path": self.path, "range": self.headers.get("Range", "")})
            self.send_error(404)

        def do_GET(self):
            nonlocal oneuse_next
            with lock:
                all_requests.append({"method": "GET", "path": self.path, "range": self.headers.get("Range", "")})
            path = self.path.split("?",1)[0]
            if fmt == "mkv" and path == "/" + media.name:
                with lock:
                    oneuse_next += 1
                    ticket = oneuse_next
                # One newly issued URL per GET, never reusable after a GET.
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{port}/ticket/{ticket}")
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                return
            if fmt == "mkv" and path.startswith("/ticket/"):
                try:
                    ticket = int(path.split("/",2)[-1])
                except ValueError:
                    self.send_error(404)
                    return
                with lock:
                    reused = ticket in oneuse_used
                    oneuse_used.add(ticket)
                    oneuse_records.append({"ticket":ticket,"reused":reused,
                                          "range":self.headers.get("Range","")})
                if reused:
                    self.send_error(403)
                    return
            elif path != "/" + media.name:
                self.send_error(404)
                return
            value = self.headers.get("Range", "")
            is_probe = value.strip() == "bytes=0-0"
            start = 0
            end = size - 1
            partial = bool(value)
            if value:
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", value)
                if match is None:
                    self.send_error(416)
                    return
                start = int(match[1])
                if match[2]:
                    end = min(end, int(match[2]))
            if start >= size or end < start:
                self.send_error(416)
                return
            with lock:
                requests.append({"range": value, "offset": start})
                # Run687 MP4 probe behavior unchanged; MKV starts at real byte
                # zero and must recover an initial 503 plus a truncated body.
                first_mkv = fmt == "mkv" and start == 0
                inject_503 = (is_probe or first_mkv) and not faults["probe_503"]
                if inject_503:
                    faults["probe_503"] += 1
                inject_short = (not inject_503) and (not is_probe) and not faults["short_body"]
                if inject_short:
                    faults["short_body"] += 1
            if inject_503:
                self.send_response(503)
                self.send_header("Connection", "close")
                self.send_header("Content-Length", "0")
                self.end_headers()
                self.close_connection = True
                return

            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", "video/mp4" if fmt == "mp4" else "video/x-matroska")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                with media.open("rb") as f:
                    f.seek(start)
                    left = end - start + 1
                    if inject_short:
                        # Send a valid header plus some video payload, then
                        # close mid-range so read/seek resume is necessary.
                        chunk = f.read(min(left, 65536))
                        if chunk:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        try:
                            self.connection.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                        self.close_connection = True
                        return
                    while left:
                        chunk = f.read(min(left, 65536))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_port
        threading.Thread(target=server.serve_forever, daemon=True).start()
        adb("reverse", f"tcp:{port}", f"tcp:{port}")
        adb("shell", "am", "force-stop", PACKAGE)
        adb("logcat", "-c")
        marker = "NOVA_WEAKNET_" + fmt.upper() + "_" + str(time.monotonic_ns())
        adb("shell", "log", "-p", "i", "-t", "NOVA_WEAKNET_TEST", marker)
        uri = f"webdav://127.0.0.1:{port}/{media.name}"
        adb("shell",
            f"am start -W -n {PLAYER} -a android.intent.action.VIEW "
            f"-d {shlex.quote(uri)} -t "
            + ("video/mp4" if fmt == "mp4" else "video/x-matroska"),
            timeout=30)

        log = wait_for(
            lambda t: (
                marker in t
                and "NovaTransport: OPEN_READY mode=file" in t[t.rfind(marker):]
                and "NOVA_DIRECT_SOURCE_OPEN:" in t[t.rfind(marker):]
                and "NOVA_RAW128_OPEN: phase=pre_probe" in t[t.rfind(marker):]
                and "NOVA_STARTUP_TRACE first_frame_sink" in t[t.rfind(marker):]
                and "NOVA_NONISO_DUP_ZERO_SKIP_V1:" in t[t.rfind(marker):]
            ),
            95,
            fmt + " WebDAV weak-network first rendered frame",
        )
        if "FATAL EXCEPTION" in log or "Fatal signal" in log:
            raise RuntimeError(fmt + " crashed despite a first-frame marker")
        # Final signed APK must skip the redundant Java 0-to-0 Seek AFTER
        # the native parser initialized the MKV/MP4. Not a mock/proxy test.
        startup = log[log.rfind(marker):]
        if "NOVA_NONISO_DUP_ZERO_SKIP_V1:" not in startup:
            raise RuntimeError(fmt + " startup prepared-zero guard did not run")
        if "avos_mp_video:avos_mp_video_seek current_pos=0 to pos=0" in startup:
            raise RuntimeError(fmt + " still sent a native duplicate zero Seek")
        if fmt == "mkv":
            frame_lines = [x for x in startup.splitlines()
                           if "NOVA_STARTUP_TRACE first_frame_sink" in x]
            if not frame_lines:
                raise RuntimeError("MKV produced no first video frame")
            pts_match = re.search(r"pts=(-?\d+)", frame_lines[0])
            if not pts_match or int(pts_match.group(1)) != 0:
                raise RuntimeError("MKV time-zero keyframe lost: " + frame_lines[0])
        print("NOVA_NONISO_DUP_ZERO_STARTUP_ART=PASS " + fmt
              + " (real signed APK, no 0-to-0 seek, MKV first PTS=0)")
        with lock:
            snapshot = list(requests)
            all_snapshot = list(all_requests)
            fault_counts = dict(faults)
        if fault_counts != {"probe_503": 1, "short_body": 1}:
            raise RuntimeError(fmt + " faults not both exercised: " + str(fault_counts)
                               + " all_requests=" + repr(all_snapshot[:16]))
        if len(snapshot) < 3:
            raise RuntimeError(fmt + " did not generate recovery reads")
        if fmt == "mkv":
            with lock:
                oneuse_snapshot = list(oneuse_records)
            if len(oneuse_snapshot) < 3 or any(e["reused"] for e in oneuse_snapshot):
                raise RuntimeError("one-use MKV redirected GET was reused: "
                                   + repr(oneuse_snapshot[:12]))
            if any(e["range"].strip() == "bytes=0-0" for e in oneuse_snapshot):
                raise RuntimeError("MKV still performs sacrificial GET bytes=0-0")
            if "NOVA_NONISO_SINGLE_GET_V1:" not in log:
                raise RuntimeError("MKV did not use live one-GET Android JNI transport")
            # The remote MKV must actually seek through its Cues, rather than
            # merely open/first-frame. Match direct WebDAV DPAD focus strategy.
            adb("shell","input","keyevent","20")
            time.sleep(0.4)
            adb("shell","input","keyevent","20")
            time.sleep(0.4)
            seek_marker = "NOVA_MKV_BBC_TEST_" + str(time.monotonic_ns())
            adb("shell","log","-p","i","-t","NOVA_MKV_BBC_TEST",seek_marker)
            adb("shell","input","keyevent","22")
            seeklog = wait_for(
                lambda t: (
                    seek_marker in t and
                    "NOVA_MKV_BBC_CUE_SEEK_V1:" in t[t.rfind(seek_marker):] and
                    "NOVA_RAW128_SEEK:" in t[t.rfind(seek_marker):]
                ),40,"actual MKV Cues Seek on redirected WebDAV")
            log = seeklog
            print("NOVA_MKV_ONEUSE_WEBDAV_SEEK_SMOKE=PASS: "
                  "single-use redirects, 503, short body, indexed seek")
        result = {
            "status": "PASS",
            "format": fmt,
            "media_size": size,
            "webdav_source": True,
            "real_first_frame": True,
            "noniso_startup_zero_skip": True,
            "redundant_native_seek_zero": False,
            "mkv_first_pts_zero": fmt == "mkv",
            "faults": fault_counts,
            "request_count": len(snapshot),
            "ranges_first_16": snapshot[:16],
            "native_retry_log": "NOVA_WEAKNET_RETRY" in log,
            "java_retry_log": "NOVA_WEAKNET" in log,
            "native_open_ready": True,
            "one_use_redirects": len(oneuse_records) if fmt=="mkv" else None,
            "mkv_indexed_seek": fmt=="mkv",
        }
        (report_dir / ("weaknet-" + fmt + "-logcat.txt")).write_text(log)
        print("WEAKNET_WEBDAV_FORMAT_PASS " + json.dumps(result))
        return result
    finally:
        with lock:
            (report_dir / ("weaknet-" + fmt + "-request-debug.json")).write_text(
                json.dumps({"faults": faults, "valid_requests": requests,
                            "all_requests": all_requests}, indent=2) + "\n")
        try:
            (report_dir / ("weaknet-" + fmt + "-last-logcat.txt")).write_text(logs())
        except Exception:
            pass
        try:
            adb("shell", "am", "force-stop", PACKAGE)
        except Exception:
            pass
        if port:
            try:
                adb("reverse", "--remove", f"tcp:{port}")
            except Exception:
                pass
        if server:
            server.shutdown()
            server.server_close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports", type=Path, required=True)
    args = parser.parse_args()
    args.reports.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "FAIL",
        "scope": "signed APK actual weak WebDAV, HTTP 503 + truncated body, MKV/MP4 first frame",
        "formats": [],
    }
    try:
        if adb("shell", "getprop", "ro.kernel.qemu").strip() != "1":
            raise RuntimeError("Fresh Android emulator required")
        with tempfile.TemporaryDirectory(prefix="nova-weak-formats-") as td:
            for fmt in ("mkv", "mp4"):
                report["formats"].append(test_one(fmt, Path(td), args.reports))
        report["status"] = "PASS"
    finally:
        (args.reports / "weaknet-webdav-formats.json").write_text(
            json.dumps(report, indent=2) + "\n")
    print("WEAKNET_WEBDAV_FORMATS=" + report["status"])


if __name__ == "__main__":
    main()
