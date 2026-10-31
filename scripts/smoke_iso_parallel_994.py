#!/usr/bin/env python3
"""NOVA 994 real signed APK ISO WebDAV startup acceptance.

Requires a genuinely authored Blu-ray ISO (tsMuxer --blu-ray), not a renamed
MPEG-TS. The test observes physical LBA discovery, parallel W2, real video
first frame, zero-reseed replay and the spinner buffering percentage events.
"""
import argparse
import hashlib
import http.server
import json
from pathlib import Path
import re
import shlex
import socket
import threading
import time

from smoke_direct_webdav import adb, logs, wait_for, PACKAGE, PLAYER


def serve_iso(iso: Path):
    size = iso.stat().st_size
    requests = []
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *unused):
            pass
        def do_PROPFIND(self):
            self.send_error(404)
        def do_HEAD(self):
            if self.path.split("?", 1)[0] != "/" + iso.name:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(size))
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
        def do_GET(self):
            if self.path.split("?", 1)[0] != "/" + iso.name:
                self.send_error(404)
                return
            value = self.headers.get("Range", "")
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", value) if value else None
            if value and not match:
                self.send_error(416)
                return
            start = int(match.group(1)) if match else 0
            end = min(size - 1, int(match.group(2))) if match and match.group(2) else size - 1
            if start >= size or end < start:
                self.send_error(416)
                return
            requests.append({"start": start, "end": end, "range": value})
            self.send_response(206 if match else 200)
            self.send_header("Content-Type", "video/x-bluray-iso")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end-start+1))
            if match:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                with iso.open("rb") as file:
                    file.seek(start)
                    left = end-start+1
                    while left > 0:
                        chunk = file.read(min(left, 64*1024))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except (OSError, BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, requests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iso", required=True, type=Path)
    ap.add_argument("--reports", required=True, type=Path)
    ap.add_argument("--apk", required=True, type=Path)
    args=ap.parse_args()
    args.reports.mkdir(parents=True,exist_ok=True)
    iso=args.iso.resolve()
    apk=args.apk.resolve()
    if not apk.is_file() or apk.stat().st_size < 1000000:
        raise RuntimeError("missing actual signed APK for ISO test")
    apk_digest=hashlib.sha256(apk.read_bytes()).hexdigest()
    if not iso.exists() or iso.stat().st_size < 2 * 1024 * 1024:
        raise RuntimeError("missing genuine Blu-ray ISO fixture")
    server, requests = serve_iso(iso)
    try:
        adb("reverse",f"tcp:{server.server_port}",f"tcp:{server.server_port}")
        adb("shell","am","force-stop",PACKAGE)
        adb("logcat","-c")
        marker="NOVA_994_ISO_" + str(time.monotonic_ns())
        adb("shell","log","-p","i","-t","NOVA_ISO_994_TEST",marker)
        uri=f"webdav://127.0.0.1:{server.server_port}/{iso.name}"
        adb("shell",f"am start -W -n {PLAYER} -a android.intent.action.VIEW "
                    f"-d {shlex.quote(uri)} -t video/x-bluray-iso",timeout=40)
        try:
            log=wait_for(
                lambda t: (
                    marker in t
                    and "OPEN_READY mode=iso" in t[t.rfind(marker):]
                    and "NOVA_STARTUP_TRACE first_frame_sink" in t[t.rfind(marker):]
                ),
                100,"Blu-ray ISO real first frame")
        finally:
            full=logs()
            (args.reports/"994-iso-logcat.txt").write_text(full)
        live=full[full.rfind(marker):]
        def index(label):
            return live.find(label)
        markers={
            "title_scan": "ISO_OPEN_STAGE title_select_info_ms",
            "pump_begin": "NOVA_ISO_PARALLEL_V1: pump_begin",
            "pump_kicked": "NOVA_ISO_PARALLEL_V2: pump_kicked",
            "kickoff_ready": "NOVA_ISO_PARALLEL_V2: kickoff_ready=1",
            "owner_handoff": "NOVA_ISO_PARALLEL_V1: owner_handoff",
            "w2_start": "NOVA_LITERANGE4_START",
            "meta_done": "NOVA_ISO_META_STAIR_V1: done",
            "first_frame": "NOVA_STARTUP_TRACE first_frame_sink",
            "buffer_progress": "NOVA_STARTUP_BUFFER_PERCENT_V1:",
        }
        found={k:index(v) for k,v in markers.items()}
        if "FATAL EXCEPTION" in live or "Fatal signal" in live:
            raise RuntimeError("NOVA 994 ISO crashed during real source open")
        if found["first_frame"]<0:
            raise RuntimeError("no ISO first frame from signed APK")
        if found["meta_done"]<0 or found["meta_done"]>found["first_frame"]:
            raise RuntimeError("ISO metadata scan completion was not recorded before first frame")
        if found["w2_start"]<0 or found["w2_start"]>found["first_frame"]:
            raise RuntimeError("ISO W2 download was not launched before first frame")
        if found["pump_begin"]<0 or found["w2_start"]<0:
            raise RuntimeError("ISO early two-lane source did not start")
        if found["meta_done"]>=0 and (found["pump_begin"]>=found["meta_done"] or
            found["pump_kicked"]>=found["meta_done"] or
            found["kickoff_ready"]>=found["meta_done"]):
            raise RuntimeError("ISO W2 CURLM was not performed before metadata scan finished")
        if found["pump_kicked"]<0 or found["kickoff_ready"]<0:
            raise RuntimeError("ISO dual-lane GETs were never driven before metadata scan")
        lanes=re.findall(r"NOVA_LITERANGE4_START[^\n]*lanes=(\d+)",live)
        if not lanes or "2" not in lanes:
            raise RuntimeError("ISO W2 not confirmed two lanes")
        if found["owner_handoff"]<0:
            raise RuntimeError("ISO CURLM owner handoff missing")
        if "NOVA_ISO_STARTUP_REPLAY_V1: hit" not in live:
            raise RuntimeError("ISO internal FFmpeg probe rewind did not reuse verified bytes")
        # Read actual stop reason; do not infer no-seek from a source guard.
        iso_jump_count=len(re.findall(r"NOVA_LITERANGE4_STOP reason=iso-lba-jump\b",live[:found["first_frame"]]))
        if iso_jump_count != 0:
            raise RuntimeError(f"ISO startup reset W2 via iso-lba-jump {iso_jump_count} times")
        result={
          "status":"PASS",
          "apk_sha256":apk_digest,
          "iso_lba_jump_count":iso_jump_count,
          "w2_before_first_frame":True,
          "media_size":iso.stat().st_size,
          "url_type":"local WebDAV Blu-ray ISO",
          "real_first_frame":True,
          "w2_during_metadata":True,
          "curl_multi_perform_before_meta_end": True,
          "two_lanes":True,
          "startup_prefix_replay":True,
          "owner_handoff":True,
          "buffer_progress_observed":found["buffer_progress"]>=0,
          "events_present":{k:v>=0 for k,v in found.items()},
          "range_requests":len(requests),
          "first_ranges":requests[:20],
          "scope":"synthetic single-clip ISO; does not replace large user ISO acceptance",
        }
        (args.reports/"994-iso-startup.json").write_text(json.dumps(result,indent=2))
        print("NOVA_994_ISO_PARALLEL_SIGNED_APK=PASS",json.dumps(result))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
