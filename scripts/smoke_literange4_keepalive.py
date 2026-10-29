#!/usr/bin/env python3
"""Actual signed APK HTTP/1.1 keep-alive vs forced-close native Range A/B.

Requires at least six curl-completed, validated 206 bounded ranges, from both
native slots, and rendered playback. Reads CURLINFO_NUM_CONNECTS directly
from final APK logcat. No URL, signed query, credential or remote IP is logged.
"""
import argparse, http.server, json, re, shlex, tempfile, threading
from pathlib import Path
from smoke_direct_webdav import adb, logs, run, wait_for, PACKAGE, PLAYER

PATTERN=re.compile(
    r"NOVA_LITERANGE4_CONN slot=([01]) at=(\d+) len=(\d+) "
    r"new=(\d+) reused=([01]) connId=(-?\d+) connectMs=(\d+) "
    r"tlsMs=(\d+) ttfbMs=(\d+) totalMs=(\d+) redirects=(\d+) http=(\d+) curl=(\d+)")

def run_case(media,keepalive):
    size=media.stat().st_size
    lock=threading.Lock()
    counts={"new_connections":0,"get_requests":0,"bounded_requests":0,
            "requests_per_connection":{}}
    server=None
    port=None
    try:
        class Server(http.server.ThreadingHTTPServer):
            daemon_threads=True
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version="HTTP/1.1"
            def log_message(self,*_):
                pass
            def setup(self):
                super().setup()
                with lock:
                    counts["new_connections"]+=1
                    self.cid=counts["new_connections"]
            def do_GET(self):
                if self.path.split("?",1)[0]!="/reuse.ts":
                    self.send_error(404)
                    return
                m=re.fullmatch(r"bytes=(\d+)-(\d*)",self.headers.get("Range",""))
                if not m:
                    self.send_error(416)
                    return
                start=int(m[1])
                end=min(size-1,int(m[2])) if m[2] else size-1
                if start>=size or start>end:
                    self.send_error(416)
                    return
                with lock:
                    counts["get_requests"]+=1
                    if m[2]:
                        counts["bounded_requests"]+=1
                    k=str(self.cid)
                    c=counts["requests_per_connection"]
                    c[k]=c.get(k,0)+1
                self.send_response(206)
                self.send_header("Accept-Ranges","bytes")
                self.send_header("Content-Length",str(end-start+1))
                self.send_header("Content-Range",f"bytes {start}-{end}/{size}")
                self.send_header("Content-Type","video/mp2t")
                self.send_header("Connection","keep-alive" if keepalive else "close")
                self.end_headers()
                self.close_connection=not keepalive
                try:
                    with media.open("rb") as f:
                        f.seek(start)
                        remaining=end-start+1
                        while remaining:
                            block=f.read(min(65536,remaining))
                            if not block:
                                raise OSError("fixture shorter than advertised")
                            self.wfile.write(block)
                            remaining-=len(block)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    # Actual seek may cancel a request; expected in WebDAV.
                    pass

        server=Server(("127.0.0.1",0),Handler)
        port=server.server_port
        threading.Thread(target=server.serve_forever,daemon=True).start()
        adb("reverse",f"tcp:{port}",f"tcp:{port}")
        adb("shell","am","force-stop",PACKAGE)
        adb("logcat","-c")
        uri=f"webdav://127.0.0.1:{port}/reuse.ts"
        adb("shell",f"am start -W -n {PLAYER} "
                    f"-a android.intent.action.VIEW -d {shlex.quote(uri)} -t video/mp2t",
                    timeout=30)

        def complete(log):
            found=PATTERN.findall(log)
            return (len(found)>=6 and
                    "NOVA_LITERANGE4_NET lanes=2" in log and
                    "NOVA_STARTUP_TRACE first_frame_sink" in log)
        output=wait_for(complete,110,"real signed APK pool A/B completed transfers")
        if "FATAL EXCEPTION" in output or "Fatal signal" in output:
            raise RuntimeError("crash while measuring keep-alive")
        rows=PATTERN.findall(output)
        metrics=[{"slot":int(r[0]),"at":int(r[1]),"length":int(r[2]),
                  "new":int(r[3]),"reused":int(r[4]),"conn_id":int(r[5]),
                  "connect_ms":int(r[6]),"tls_ms":int(r[7]),
                  "ttfb_ms":int(r[8]),"total_ms":int(r[9]),
                  "redirects":int(r[10]),"status":int(r[11]),
                  "curl_result":int(r[12])} for r in rows]
        if not all(m["status"]==206 and m["curl_result"]==0 for m in metrics):
            raise RuntimeError("native 206/Content-Range completion failure")
        if {m["slot"] for m in metrics}!={0,1}:
            raise RuntimeError("missing one native slot")
        native_new=sum(m["new"] for m in metrics)
        if keepalive and all(m["new"]>0 for m in metrics):
            raise RuntimeError("native connection pool never reused a connection")
        if not keepalive and any(m["reused"] for m in metrics):
            raise RuntimeError("a closed HTTP/1.1 connection was reported reusable")
        if not keepalive and any(m["new"]==0 for m in metrics):
            raise RuntimeError("forced Connection: close unexpectedly reused TCP")
        with lock:
            server_snapshot=json.loads(json.dumps(counts))
        total=len(metrics)
        def avg(name):
            return round(sum(m[name] for m in metrics)/total,1)
        return {"mode":"keep-alive" if keepalive else "forced-close",
                "native_completed_ranges":total,
                "native_new_connections":native_new,
                "native_new_per_100_ranges":round(100*native_new/total,1),
                "native_reused_requests":sum(m["reused"] for m in metrics),
                "avg_connect_ms":avg("connect_ms"),
                "avg_tls_ms":avg("tls_ms"),
                "avg_ttfb_ms":avg("ttfb_ms"),
                "server_counts":server_snapshot}
    finally:
        try:adb("shell","am","force-stop",PACKAGE)
        except Exception:pass
        if port is not None:
            try:adb("reverse","--remove",f"tcp:{port}")
            except Exception:pass
        if server:
            server.shutdown()
            server.server_close()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--reports",type=Path,required=True)
    args=parser.parse_args()
    args.reports.mkdir(parents=True,exist_ok=True)
    report={"status":"FAIL","test":"final signed APK HTTP1.1 keepalive A/B"}
    try:
        with tempfile.TemporaryDirectory() as temp:
            media=Path(temp)/"reuse.ts"
            run(["ffmpeg","-v","error","-y","-f","lavfi","-i",
                 "testsrc2=size=640x360:rate=25","-f","lavfi","-i",
                 "sine=frequency=490:sample_rate=48000","-t","95",
                 "-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p",
                 "-g","25","-b:v","3M","-c:a","aac","-b:a","128k",
                 "-f","mpegts",str(media)],timeout=180)
            if media.stat().st_size<25*1024*1024:
                raise RuntimeError("synthetic TS file too small")
            persistent=run_case(media,True)
            closing=run_case(media,False)
            if persistent["native_new_per_100_ranges"]>=closing["native_new_per_100_ranges"]:
                raise RuntimeError("Keep-Alive did not reduce new connections")
            report.update(status="PASS",persistent=persistent,closing=closing,
                          fixed_range_seconds=4)
            print("NOVA_LITERANGE4_KEEPALIVE_AB_PASS="+json.dumps(report))
    except Exception as e:
        report["error"]=str(e)
        raise
    finally:
        (args.reports/"literange4-keepalive-ab.json").write_text(
            json.dumps(report,indent=2)+"\n")
        try:(args.reports/"literange4-keepalive-last-logcat.txt").write_text(logs())
        except Exception:pass

if __name__=="__main__":
    main()
