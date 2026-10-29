#!/usr/bin/env python3
"""Require W=2 ordered 4X HTTP ranges, streaming handoff, and seek guard."""
import argparse,http.server,json,re,shlex,tempfile,threading,time
from pathlib import Path
from smoke_direct_webdav import adb,logs,run,wait_for,PACKAGE,PLAYER

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--reports",type=Path,required=True)
    args=ap.parse_args();args.reports.mkdir(parents=True,exist_ok=True)
    report={"status":"FAIL","test":"signed W2 ordered HTTP Range and seek guard"}
    lock=threading.Lock();stats={"active":0,"peak":0,"starts":[]}
    slow=threading.Event();slow.set()
    server=None;port=None
    try:
        with tempfile.TemporaryDirectory() as td:
            media=Path(td)/"slow.ts"
            run(["ffmpeg","-v","error","-y","-f","lavfi","-i",
                "testsrc2=size=640x360:rate=25","-f","lavfi","-i",
                "sine=frequency=500:sample_rate=48000","-t","75",
                "-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p",
                "-g","1","-keyint_min","1","-sc_threshold","0","-b:v","3M","-c:a","aac","-b:a","128k",
                "-f","mpegts",str(media)],timeout=120)
            size=media.stat().st_size
            if size<20*1024*1024:raise RuntimeError("Synthetic TS too small")
            class Handler(http.server.BaseHTTPRequestHandler):
                protocol_version="HTTP/1.1"
                def log_message(self,*_):pass
                def do_GET(self):
                    if self.path.split("?",1)[0]!="/slow.ts":
                        self.send_error(404);return
                    m=re.fullmatch(r"bytes=(\d+)-(\d*)",self.headers.get("Range",""))
                    if not m:self.send_error(416);return
                    first=int(m[1]);last=min(size-1,int(m[2])) if m[2] else size-1
                    if first>=size or first>last:self.send_error(416);return
                    bounded=bool(m[2]) and (last-first+1)>=1048576
                    if bounded:
                        with lock:
                            stats["active"]+=1
                            stats["peak"]=max(stats["peak"],stats["active"])
                            stats["starts"].append(first)
                    self.send_response(206)
                    self.send_header("Accept-Ranges","bytes")
                    self.send_header("Content-Length",str(last-first+1))
                    self.send_header("Content-Range",f"bytes {first}-{last}/{size}")
                    self.send_header("Content-Type","video/mp2t")
                    self.send_header("Connection","close")
                    self.end_headers()
                    try:
                        with media.open("rb") as stream:
                            stream.seek(first);remaining=last-first+1
                            while remaining:
                                data=stream.read(min(16384,remaining))
                                if not data:break
                                self.wfile.write(data);self.wfile.flush()
                                remaining-=len(data)
                                time.sleep(.07 if slow.is_set() else .002)  # Slow only until two-way capability is proved
                    except (OSError,BrokenPipeError,ConnectionResetError):
                        pass
                    finally:
                        if bounded:
                            with lock:stats["active"]-=1
                        self.close_connection=True
            server=http.server.ThreadingHTTPServer(("127.0.0.1",0),Handler)
            port=server.server_port
            threading.Thread(target=server.serve_forever,daemon=True).start()
            adb("reverse",f"tcp:{port}",f"tcp:{port}")
            adb("shell","am","force-stop",PACKAGE);adb("logcat","-c")
            uri=f"webdav://127.0.0.1:{port}/slow.ts"
            adb("shell",f"am start -W -n {PLAYER} -a android.intent.action.VIEW -d {shlex.quote(uri)} -t video/mp2t",timeout=30)
            wait_for(lambda t:"NOVA_LITERANGE4_URL valid=1" in t and
                "NOVA_LITERANGE4_START" in t,40,"native W2 transport start")
            def pair_start(log):
                # v6.6.2 may enable both lanes immediately after probe:
                # in that case there is no 1->2 PAIR_ENABLE event.
                hits=[m.start() for m in re.finditer(
                    r"NOVA_LITERANGE4_REBASE[^\n]*lanes=2\b|NOVA_LITERANGE4_PAIR_ENABLE",log)]
                return max(hits) if hits else -1

            text=wait_for(lambda t:pair_start(t)>=0,155,
                          "real W=2 pipeline enabled")
            def simultaneous_gets(_):
                with lock:
                    return stats["peak"]>=2 and len(stats["starts"])>=2
            wait_for(simultaneous_gets,45,
                     "two overlapping bounded HTTP Range GETs")
            with lock:peak=stats["peak"];starts=stats["starts"][:24]
            # Re-read logcat AFTER concurrency; the earlier 'pair enabled'
            # snapshot predates the pair's PIECE lines on some devices.
            text=wait_for(lambda t:len(re.findall(
                r"NOVA_LITERANGE4_PIECE slot=[01] from=\d+ to=\d+ len=\d+ x=[1-9]\d* window=2",
                t))>=2,25,"two real bitrate-aware 4X piece launches")
            pieces=re.findall(
                r"NOVA_LITERANGE4_PIECE slot=([01]) from=(\d+) to=(\d+) "
                r"len=(\d+) x=(\d+) window=2",text)
            long_pieces=[tuple(map(int,p)) for p in pieces if int(p[4])>0]
            if len(long_pieces)<2 or long_pieces[0][0]!=0 or long_pieces[1][0]!=1:
                raise RuntimeError("Missing paired ordered slot=0/1 4X slices")
            for slot,start,end,length,x in long_pieces[:2]:
                if end-start!=length or length<=0 or length>4*x:
                    raise RuntimeError("Invalid 4X Range byte boundaries")
            if "NOVA_LITERANGE4_RANGE_ERROR" in text:
                raise RuntimeError("Native Range failed before W2 overlap")
            # Require a real rendered first frame AFTER W2 activation.
            text=wait_for(lambda t:
                pair_start(t)>=0 and
                "NOVA_STARTUP_TRACE first_frame_sink" in t[pair_start(t):] and
                re.search(r"NOVA_FINAL_RENDER_Q:.*renderSeq=[1-9][0-9]*",
                          t[pair_start(t):]),
                110,"real rendered frame AFTER W2 two-Range activation")
            # Require fresh live two-lane telemetry before DPAD.
            ready_marker="NOVA_LITE4_READY_"+str(time.monotonic_ns())
            adb("shell","log","-p","i","-t","NOVA_LITE4_TEST",ready_marker)
            wait_for(lambda t:ready_marker in t and
                "NOVA_LITERANGE4_NET lanes=2" in t[t.rfind(ready_marker):],
                10,"live two-lane telemetry immediately before seek")
            adb("shell","input","keyevent","20");time.sleep(.4)
            adb("shell","input","keyevent","20");time.sleep(.4)
            marker="NOVA_LITE4_SEEK_"+str(time.monotonic_ns())
            adb("shell","log","-p","i","-t","NOVA_LITE4_TEST",marker)
            slow.clear()  # Restore speed only after two-way overlap, to make target-frame seek observable
            adb("shell","input","keyevent","22")
            text=wait_for(lambda t:marker in t and
                "NOVA_MULTI_SEEK_GUARD_BEGIN lanes=2" in t[t.rfind(marker):] and
                "NOVA_MULTI_SEEK_GUARD_END success=1" in t[t.rfind(marker):],
                110,"two-lane seek guard and completion")
            if "FATAL EXCEPTION" in text or "Fatal signal" in text:
                raise RuntimeError("Crash during 4-lane seek")
            report.update(status="PASS",strategy="four-second-average-rate-pieces-W2-ordered",peak_active_http_ranges=peak,first_ranges=starts,
                escalations=["1->2"],seek_guard_from_two_lanes=True)
            print("NOVA_LITERANGE4_REAL_CONCURRENCY_PASS="+json.dumps(report))
    except Exception as e:
        report["error"]=str(e);raise
    finally:
        (args.reports/"literange4-concurrency.json").write_text(json.dumps(report,indent=2)+"\n")
        try:(args.reports/"literange4-last-logcat.txt").write_text(logs())
        except Exception:pass
        try:adb("shell","am","force-stop",PACKAGE)
        except Exception:pass
        if port:
            try:adb("reverse","--remove",f"tcp:{port}")
            except Exception:pass
        if server:server.shutdown();server.server_close()
if __name__=="__main__":main()
