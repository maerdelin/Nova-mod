#!/usr/bin/env python3
"""Final signed APK: TWO injected 403s separated by eight verified 206 ranges.

Proof: 8 successful W2 ranges do not erase cooldown history. Second 403
must use 15s, recover canonical single GET and then require two verified
native 206s before promotion to W2. It never changes 4s piece length.
"""
import argparse, http.server, json, re, shlex, tempfile, threading, time
from pathlib import Path
from smoke_direct_webdav import adb, logs, run, wait_for, PACKAGE, PLAYER

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--reports",type=Path,required=True)
    args=ap.parse_args()
    args.reports.mkdir(parents=True,exist_ok=True)
    result={"status":"FAIL","test":"two 403s with eight valid ranges between"}
    guard=threading.Lock()
    phase={"armed":0,"denied":0,"single_after_first":0,
           "single_after_second":0,"bounded_after_second":0}
    server=None
    port=None
    try:
        with tempfile.TemporaryDirectory(prefix="nova-403-history-") as td:
            media=Path(td)/"history.ts"
            run(["ffmpeg","-v","error","-y","-f","lavfi","-i",
                 "testsrc2=size=640x360:rate=25","-f","lavfi","-i",
                 "sine=frequency=550:sample_rate=48000","-t","300",
                 "-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p",
                 "-g","25","-b:v","4M","-c:a","aac","-b:a","128k",
                 "-f","mpegts",str(media)],timeout=300)
            total=media.stat().st_size
            if total<125*1024*1024:
                raise RuntimeError("TS test fixture too short for a 15s cooldown and continued native reads")
            class Handler(http.server.BaseHTTPRequestHandler):
                protocol_version="HTTP/1.1"
                def log_message(self,*_):
                    pass
                def do_GET(self):
                    if self.path.split("?",1)[0]!="/history.ts":
                        self.send_error(404)
                        return
                    m=re.fullmatch(r"bytes=(\d+)-(\d*)",self.headers.get("Range",""))
                    if not m:
                        self.send_error(416)
                        return
                    first=int(m[1])
                    last=min(total-1,int(m[2])) if m[2] else total-1
                    if first>=total or first>last:
                        self.send_error(416)
                        return
                    bounded=bool(m[2]) and last-first+1>=1048576
                    deny=False
                    with guard:
                        if bounded and phase["armed"]>phase["denied"]:
                            phase["denied"]+=1
                            deny=True
                        elif phase["denied"]:
                            if not bounded:
                                if phase["denied"]==1:phase["single_after_first"]+=1
                                else:phase["single_after_second"]+=1
                            elif phase["denied"]==2:
                                phase["bounded_after_second"]+=1
                    if deny:
                        self.send_response(403)
                        self.send_header("Content-Length","6")
                        self.send_header("Connection","close")
                        self.end_headers()
                        try:self.wfile.write(b"denied")
                        except OSError:pass
                        self.close_connection=True
                        return
                    self.send_response(206)
                    self.send_header("Accept-Ranges","bytes")
                    self.send_header("Content-Length",str(last-first+1))
                    self.send_header("Content-Range",f"bytes {first}-{last}/{total}")
                    self.send_header("Connection","close")
                    self.end_headers()
                    self.close_connection=True
                    try:
                        with media.open("rb") as f:
                            f.seek(first)
                            remaining=last-first+1
                            while remaining:
                                data=f.read(min(16384,remaining))
                                if not data:break
                                self.wfile.write(data)
                                self.wfile.flush()
                                remaining-=len(data)
                                time.sleep(.006)
                    except (OSError,BrokenPipeError,ConnectionResetError):
                        pass
            class Server(http.server.ThreadingHTTPServer):
                daemon_threads=True
            server=Server(("127.0.0.1",0),Handler)
            port=server.server_port
            threading.Thread(target=server.serve_forever,daemon=True).start()
            adb("reverse",f"tcp:{port}",f"tcp:{port}")
            adb("shell","am","force-stop",PACKAGE)
            adb("logcat","-c")
            uri=f"webdav://127.0.0.1:{port}/history.ts"
            adb("shell",f"am start -W -n {PLAYER} "
                f"-a android.intent.action.VIEW -d {shlex.quote(uri)} -t video/mp2t",
                timeout=30)
            wait_for(lambda l:"NOVA_LITERANGE4_NET lanes=2" in l
                and "NOVA_STARTUP_TRACE first_frame_sink" in l,
                140,"initial W2 and first video frame")
            marker1="NOVA_HISTORY_403_FIRST_"+str(time.monotonic_ns())
            adb("shell","log","-p","i","-t","NOVA_403_HISTORY_TEST",marker1)
            with guard:phase["armed"]=1
            wait_for(lambda l:marker1 in l
                and "NOVA_LITERANGE4_RANGE_ERROR status=403" in l[l.rfind(marker1):]
                and "NOVA_MULTI_HTTP403_COOLDOWN attempt=1 waitMs=4000" in l[l.rfind(marker1):],
                105,"first 403 and 4s cooldown")
            # Log proves recovery ran through W2 + 8 complete exact-206
            # ranges, not merely a successful initial HTTP connection.
            wait_for(lambda l:marker1 in l
                and re.search(r"NOVA_MULTI_HTTP403_RECOVERED validRanges=8\b",
                              l[l.rfind(marker1):])
                and "NOVA_MULTI_HTTP403_RETRY attempt=1" in l[l.rfind(marker1):],
                130,"first 403 recovered with eight clean W2 ranges")
            marker2="NOVA_HISTORY_403_SECOND_"+str(time.monotonic_ns())
            adb("shell","log","-p","i","-t","NOVA_403_HISTORY_TEST",marker2)
            with guard:phase["armed"]=2
            second=wait_for(lambda l:marker2 in l
                and "NOVA_MULTI_HTTP403_COOLDOWN attempt=2 waitMs=15000" in l[l.rfind(marker2):]
                and "NOVA_LITERANGE4_RANGE_ERROR status=403" in l[l.rfind(marker2):],
                105,"second 403 retains history with 15s cooldown")
            t_second=time.monotonic()
            segment=second[second.rfind(marker2):]
            if "NOVA_MULTI_HTTP403_COOLDOWN attempt=1" in segment:
                raise RuntimeError("history incorrectly reset after eight ranges")
            def verified_again(log):
                if marker2 not in log:return False
                tail=log[log.rfind(marker2):]
                return ("NOVA_MULTI_HTTP403_RETRY attempt=2" in tail
                    and re.search(r"NOVA_MULTI_PAIR_REARM verified=([2-9]|[1-9][0-9]+) required=2 failures=2",
                                  tail)
                    and "NOVA_LITERANGE4_PAIR_ENABLE" in tail
                    and re.search(r"NOVA_LITERANGE4_NET lanes=2[^\n]*pending=2",tail))
            output=wait_for(verified_again,140,
                "second 403 recovers single, then two clean native 206s before W2")
            elapsed=time.monotonic()-t_second
            if elapsed<14:
                raise RuntimeError(f"second cooldown violated: {elapsed:.1f}s")
            with guard:snapshot=dict(phase)
            if snapshot["denied"]!=2 or snapshot["single_after_first"]<1 or snapshot["single_after_second"]<1 or snapshot["bounded_after_second"]<2:
                raise RuntimeError("server-side validation insufficient: "+str(snapshot))
            if "FATAL EXCEPTION" in output[output.rfind(marker1):] or "Fatal signal" in output[output.rfind(marker1):]:
                raise RuntimeError("APK crashed during repeated 403 recovery")
            result.update(status="PASS",server=snapshot,
                          second_cooldown_elapsed_sec=round(elapsed,2),
                          verified_ranges_before_second=8,
                          verified_ranges_before_second_w2=2)
            print("NOVA_HTTP403_HISTORY_V2_PASS="+json.dumps(result))
    except Exception as exc:
        result["error"]=str(exc)
        raise
    finally:
        (args.reports/"literange4-http403-history.json").write_text(
            json.dumps(result,indent=2)+"\n")
        try:(args.reports/"literange4-http403-history-logcat.txt").write_text(logs())
        except Exception:pass
        try:adb("shell","am","force-stop",PACKAGE)
        except Exception:pass
        if port:
            try:adb("reverse","--remove",f"tcp:{port}")
            except Exception:pass
        if server:
            server.shutdown()
            server.server_close()

if __name__=="__main__":
    main()
