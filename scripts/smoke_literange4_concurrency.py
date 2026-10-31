#!/usr/bin/env python3
"""Require W=2 ordered 4X HTTP ranges, streaming handoff, and seek guard."""
import argparse,http.server,json,re,shlex,tempfile,threading,time
from pathlib import Path
from smoke_direct_webdav import adb,logs,run,wait_for,PACKAGE,PLAYER

# Restrict all runtime assertions to the newly launched player. Android
# logcat -c can retain already queued records from the prior WebDAV smoke.
THREADTIME_PID = re.compile(r"^\d\d-\d\d +\d\d:\d\d:\d\d\.\d+ +(\d+) +\d+ ")
PAIR_ANCHOR = re.compile(r"NOVA_LITERANGE4_REBASE[^\n]*lanes=2\b|NOVA_LITERANGE4_PAIR_ENABLE")
PIECE = re.compile(
    r"NOVA_LITERANGE4_PIECE slot=([01]) from=(\d+) to=(\d+) "
    r"len=(\d+) x=(\d+) window=2")


def player_log_after_marker(text, marker, pid):
    """Never compare a previous app process's transport records to this run."""
    start = text.rfind(marker)
    if start < 0:
        return ""
    scoped = []
    for line in text[start:].splitlines():
        m = THREADTIME_PID.match(line)
        if m and int(m.group(1)) == pid:
            scoped.append(line)
    return "\n".join(scoped)


def real_w2_pair(player_log):
    """Require ordered, contiguous slot=0/1 slices in the same W2 epoch."""
    for anchor in reversed(list(PAIR_ANCHOR.finditer(player_log))):
        epoch = player_log[anchor.end():]
        # Never join PIECEs from separate transport generations/seek resets.
        end = re.search(r"NOVA_LITERANGE4_(?:REBASE|STOP|PAIR_ENABLE)", epoch)
        if end:
            epoch = epoch[:end.start()]
        pieces = [tuple(map(int,m.groups())) for m in PIECE.finditer(epoch)]
        if len(pieces) >= 2 and pieces[0][0] == 0 and pieces[1][0] == 1:
            a, b = pieces[:2]
            if a[2] == b[1] and all(
                end-start == length and 0 < length <= 4*x
                for _,start,end,length,x in (a,b)):
                return [a,b]
    return None

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
            launch_marker="NOVA_LITE4_LAUNCH_"+str(time.monotonic_ns())
            adb("shell","log","-p","i","-t","NOVA_LITE4_TEST",launch_marker)
            uri=f"webdav://127.0.0.1:{port}/slow.ts"
            adb("shell",f"am start -W -n {PLAYER} -a android.intent.action.VIEW -d {shlex.quote(uri)} -t video/mp2t",timeout=30)
            pids=adb("shell","pidof",PACKAGE).strip().split()
            if len(pids)!=1 or not pids[0].isdigit():
                raise RuntimeError("Cannot identify one active player PID: "+repr(pids))
            current_pid=int(pids[0])
            def active_log(t):
                return player_log_after_marker(t,launch_marker,current_pid)
            wait_for(lambda t:"NOVA_LITERANGE4_URL valid=1" in active_log(t) and
                "NOVA_LITERANGE4_START" in active_log(t),40,"current-process W2 transport start")
            def pair_start(log):
                # v6.6.2 may enable W2 immediately after probe; PAIR_ENABLE
                # is not obligatory when the rebase already says lanes=2.
                hits=[m.start() for m in PAIR_ANCHOR.finditer(log)]
                return max(hits) if hits else -1

            text=wait_for(lambda t:pair_start(active_log(t))>=0,155,
                          "current-process W=2 pipeline enabled")
            def simultaneous_gets(_):
                with lock:
                    return stats["peak"]>=2 and len(stats["starts"])>=2
            wait_for(simultaneous_gets,45,
                     "two overlapping bounded HTTP Range GETs")
            with lock:peak=stats["peak"];starts=stats["starts"][:24]
            # Re-read logcat AFTER concurrency. Require the ordered 0/1
            # pair AFTER a W2 rebase in the SAME PID and transport epoch;
            # #1004 failed falsely by reading stale slot=0 records first.
            text=wait_for(lambda t:real_w2_pair(active_log(t)) is not None,
                          25,"current-process paired ordered 4X slot=0/1 pieces")
            long_pieces=real_w2_pair(active_log(text))
            if long_pieces is None:
                raise RuntimeError("Missing paired ordered slot=0/1 4X slices")
            if "NOVA_LITERANGE4_RANGE_ERROR" in active_log(text):
                raise RuntimeError("Native Range failed before W2 overlap")
            # Require a real rendered first frame AFTER W2 activation.
            def rendered_after_w2(t):
                scoped=active_log(t)
                first=pair_start(scoped)
                return (first>=0 and
                    "NOVA_STARTUP_TRACE first_frame_sink" in scoped[first:] and
                    bool(re.search(r"NOVA_FINAL_RENDER_Q:.*renderSeq=[1-9][0-9]*",
                                   scoped[first:])))
            text=wait_for(rendered_after_w2,110,
                          "real rendered frame AFTER W2 two-Range activation")
            # Require fresh live two-lane telemetry before DPAD.
            ready_marker="NOVA_LITE4_READY_"+str(time.monotonic_ns())
            adb("shell","log","-p","i","-t","NOVA_LITE4_TEST",ready_marker)
            wait_for(lambda t:ready_marker in t and
                "NOVA_LITERANGE4_NET lanes=2" in player_log_after_marker(
                    t,ready_marker,current_pid),
                10,"live two-lane telemetry immediately before seek")
            adb("shell","input","keyevent","20");time.sleep(.4)
            adb("shell","input","keyevent","20");time.sleep(.4)
            marker="NOVA_LITE4_SEEK_"+str(time.monotonic_ns())
            adb("shell","log","-p","i","-t","NOVA_LITE4_TEST",marker)
            slow.clear()  # Restore speed only after two-way overlap, to make target-frame seek observable
            adb("shell","input","keyevent","22")
            text=wait_for(lambda t:marker in t and
                "NOVA_MULTI_SEEK_GUARD_BEGIN lanes=2" in player_log_after_marker(t,marker,current_pid) and
                "NOVA_MULTI_SEEK_GUARD_END success=1" in player_log_after_marker(t,marker,current_pid),
                110,"two-lane seek guard and completion")
            if "FATAL EXCEPTION" in active_log(text) or "Fatal signal" in active_log(text):
                raise RuntimeError("Crash during 4-lane seek")
            report.update(status="PASS",strategy="four-second-average-rate-pieces-W2-ordered",peak_active_http_ranges=peak,first_ranges=starts,
                current_player_pid=current_pid,verified_pair=long_pieces,
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
