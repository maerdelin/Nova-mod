#!/usr/bin/env python3
"""Actual signed APK: one HTTP 429 + Retry-After must recover W2 after validated 206."""
import argparse,http.server,json,re,shlex,tempfile,threading,time
from pathlib import Path
from smoke_direct_webdav import adb,logs,run,wait_for,PACKAGE,PLAYER

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--reports",type=Path,required=True)
    args=ap.parse_args()
    args.reports.mkdir(parents=True,exist_ok=True)
    result={"status":"FAIL","test":"injected HTTP429 Retry-After=6 and W2 recovery"}
    arm=threading.Event()
    lock=threading.Lock()
    counts={"denied":0,"single_after":0,"bounded_after":0}
    server=None;port=None
    try:
        with tempfile.TemporaryDirectory() as td:
            media=Path(td)/"recovery.ts"
            run(["ffmpeg","-v","error","-y","-f","lavfi","-i","testsrc2=size=640x360:rate=25",
                 "-f","lavfi","-i","sine=frequency=550:sample_rate=48000","-t","115",
                 "-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p",
                 "-g","25","-b:v","4M","-c:a","aac","-b:a","128k","-f","mpegts",str(media)],
                timeout=150)
            total=media.stat().st_size
            assert total>45*1024*1024,total
            class Handler(http.server.BaseHTTPRequestHandler):
                protocol_version="HTTP/1.1"
                def log_message(self,*_):pass
                def do_GET(self):
                    if self.path.split("?",1)[0]!="/recovery.ts":
                        self.send_error(404);return
                    m=re.fullmatch(r"bytes=(\d+)-(\d*)",self.headers.get("Range",""))
                    if not m:self.send_error(416);return
                    first=int(m[1]);last=min(total-1,int(m[2])) if m[2] else total-1
                    if first>=total or first>last:self.send_error(416);return
                    bounded=bool(m[2]) and last-first+1>=1048576
                    deny=False
                    with lock:
                        if bounded and arm.is_set() and not counts["denied"]:
                            counts["denied"]+=1;deny=True
                        elif counts["denied"]:
                            if bounded:counts["bounded_after"]+=1
                            else:counts["single_after"]+=1
                    if deny:
                        self.send_response(429);self.send_header("Content-Length","6")
                        self.send_header("Retry-After","6")
                        self.send_header("Connection","close");self.end_headers()
                        try:self.wfile.write(b"denied")
                        except OSError:pass
                        self.close_connection=True;return
                    self.send_response(206)
                    self.send_header("Accept-Ranges","bytes")
                    self.send_header("Content-Length",str(last-first+1))
                    self.send_header("Content-Range",f"bytes {first}-{last}/{total}")
                    self.send_header("Connection","close");self.end_headers()
                    try:
                        with media.open("rb") as f:
                            f.seek(first);remaining=last-first+1
                            while remaining:
                                b=f.read(min(16384,remaining))
                                if not b:break
                                self.wfile.write(b);self.wfile.flush()
                                remaining-=len(b)
                                time.sleep(.005)
                    except (OSError,BrokenPipeError,ConnectionResetError):pass
                    finally:self.close_connection=True
            server=http.server.ThreadingHTTPServer(("127.0.0.1",0),Handler)
            port=server.server_port
            threading.Thread(target=server.serve_forever,daemon=True).start()
            adb("reverse",f"tcp:{port}",f"tcp:{port}")
            adb("shell","am","force-stop",PACKAGE);adb("logcat","-c")
            uri=f"webdav://127.0.0.1:{port}/recovery.ts"
            adb("shell",f"am start -W -n {PLAYER} -a android.intent.action.VIEW -d {shlex.quote(uri)} -t video/mp2t",timeout=30)
            wait_for(lambda t:"NOVA_LITERANGE4_NET lanes=2" in t
                     and "NOVA_STARTUP_TRACE first_frame_sink" in t,140,"initial native W2 playback")
            marker="NOVA_429_INJECT_"+str(time.monotonic_ns())
            adb("shell","log","-p","i","-t","NOVA_429_TEST",marker)
            arm.set()
            wait_for(lambda t:marker in t and
                "NOVA_LITERANGE4_RANGE_ERROR status=429" in t[t.rfind(marker):] and
                re.search(r"NOVA_MULTI_RANGE_BACKOFF http=429 curl=\d+ attempt=1 waitMs=6000",t[t.rfind(marker):]),
                110,"injected 429 and cooldown")
            # This test plays TS (FFmpeg AVIO fallback), not MKV (Java
            # DirectRangeHttp). Both must prove open-ended 206 against the
            # actual HTTP server; requiring an MKV-only log tag is invalid.
            def recovered(logcat):
                if marker not in logcat:
                    return False
                tail=logcat[logcat.rfind(marker):]
                with lock:
                    verified_single=counts["single_after"]>=1
                    verified_pair=counts["bounded_after"]>=2
                return (verified_single and verified_pair
                    and "NOVA_MULTI_RANGE_RETRY http=429 attempt=1" in tail
                    and "NOVA_LITERANGE4_PAIR_ENABLE" in tail
                    and re.search(r"NOVA_LITERANGE4_NET lanes=2[^\n]*pending=2",tail))
            text=wait_for(recovered,95,
                "server-verified single HTTP 206 and native paired Range reactivation")
            section=text[text.rfind(marker):]
            with lock:snapshot=dict(counts)
            if snapshot["denied"]!=1 or snapshot["single_after"]<1 or snapshot["bounded_after"]<2:
                raise RuntimeError("real server request trace inadequate: "+str(snapshot))
            if "FATAL EXCEPTION" in section or "Fatal signal" in section:
                raise RuntimeError("app crashed during HTTP429 recovery")
            result.update(status="PASS",requests=snapshot,single_fallback_http206=True,w2_restored=True)
            print("NOVA_HTTP429_REAL_RECOVERY_PASS="+json.dumps(result))
    except Exception as exc:
        result["error"]=str(exc);raise
    finally:
        (args.reports/"literange4-http429.json").write_text(json.dumps(result,indent=2)+"\n")
        try:(args.reports/"literange4-http429-logcat.txt").write_text(logs())
        except Exception:pass
        try:adb("shell","am","force-stop",PACKAGE)
        except Exception:pass
        if port:
            try:adb("reverse","--remove",f"tcp:{port}")
            except Exception:pass
        if server:server.shutdown();server.server_close()

if __name__=="__main__":main()
