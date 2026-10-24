#!/usr/bin/env python3
"""Final-APK MP4 RAW producer/seek concurrency regression.

Runs a real MP4 over a throttled local HTTP Range server so the RAW producer
remains active while repeated player seeks occur. Success requires repeated
native RAW seek callbacks with the player still alive and decoding afterward.
This is not a substitute for the user's WebDAV/STB acceptance test.
"""
import argparse,http.server,json,re,shlex,subprocess,tempfile,threading,time
from pathlib import Path

PACKAGE='org.courville.nova'
PLAYER=PACKAGE+'/com.archos.mediacenter.video.player.PlayerActivity'

def run(args,timeout=60):
    r=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=timeout)
    if r.returncode:
        raise RuntimeError('Command failed: '+str(args[:5])+'\n'+r.stdout+r.stderr)
    return r.stdout
def adb(*args,timeout=30): return run(['adb',*args],timeout=timeout)
def logs(): return adb('logcat','-d','-v','threadtime',timeout=20)
def resumed():
    return adb('shell','dumpsys activity activities | grep -m1 mResumedActivity || true')
def wait_for(pred,seconds,label):
    end=time.monotonic()+seconds
    last=''
    while time.monotonic()<end:
        last=logs()
        if pred(last): return last
        time.sleep(.25)
    raise RuntimeError('Missing '+label)

def seek_action_result(text, marker, direction):
    """Require scoped seek, successful RAW seek, restart and subsequent reads."""
    at = text.rfind(marker)
    if at < 0:
        return None
    phase = text[at:]
    m = re.search(r'avos_mp_video_seek current_pos=(-?\d+) to pos=(-?\d+)', phase)
    if not m:
        return None
    prior, target = int(m[1]), int(m[2])
    if (direction > 0 and target <= prior) or (direction < 0 and target >= prior):
        return None
    tail = phase[m.end():]
    # A locally retained RAW128 history hit is a valid seek too. Verify
    # the exact cache position transition and resumed decoding afterward.
    raw = re.search(r'NOVA_RAW128_SEEK: target=(\d+) result=(-?\d+) generation=(\d+)', tail)
    cached = re.search(
        r'NOVA_RAW_CACHE_SEEK_V1: from=(\d+) to=(\d+) move=(-?\d+) history=(\d+) unread=(\d+)', tail)
    if cached and (not raw or cached.start() < raw.start()):
        if int(cached[2]) - int(cached[1]) != int(cached[3]):
            return None
        mode = 'cache'
        raw_generation = -1
        post = tail[cached.end():]
    elif raw and raw[1] == raw[2]:
        mode = 'network'
        raw_generation = int(raw[3])
        post = tail[raw.end():]
    else:
        return None
    started = post.find('avos_mp_start:')
    if started < 0:
        return None
    consumed = [int(x) for x in re.findall(r'NOVA_RAW128: produced=\d+ consumed=(\d+)', post[started:])]
    if len(consumed) < 2 or consumed[-1] <= consumed[0]:
        return None
    # Real post-seek presentation, not merely a byte pointer / RAW movement.
    # The renderer may be paused for buffering; the 20s test limit accounts
    # for the existing unchanged 2X/5X refill contract.
    renders = [int(v) for v in re.findall(r'NOVA_FINAL_HEARTBEAT:[^\n]* rendered=(\d+)', post[started:])]
    if len(renders) < 2 or renders[-1] <= renders[0]:
        return None
    if 'NOVA_RAW_RETRY: error=-1414092869' in post[started:]:
        return None
    return {'from': prior, 'to': target, 'raw_generation': raw_generation,
            'mode': mode,
            'post_seek_consumed_delta': consumed[-1] - consumed[0]}


def main():
    p=argparse.ArgumentParser();p.add_argument('--reports',type=Path,required=True);a=p.parse_args()
    a.reports.mkdir(parents=True,exist_ok=True)
    report={'status':'FAIL','scope':'final APK MP4 repeated runtime seeks while RAW128 producer is active over throttled local HTTP Range'}
    server=None;port=None
    try:
        if adb('shell','getprop ro.kernel.qemu').strip()!='1':
            raise RuntimeError('Fresh CI emulator required')
        with tempfile.TemporaryDirectory(prefix='nova-mp4-seek-race-') as td:
            root=Path(td);media=root/'seek-race.mp4'
            run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=30',
                 '-f','lavfi','-i','sine=frequency=660:sample_rate=48000','-t','90',
                 '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-g','60',
                 '-b:v','3M','-maxrate','3M','-bufsize','6M',
                 '-c:a','aac','-b:a','128k','-movflags','+faststart',media],timeout=120)
            size=media.stat().st_size
            starts=[];lock=threading.Lock()
            class H(http.server.BaseHTTPRequestHandler):
                protocol_version='HTTP/1.1'
                def log_message(self,*_): pass
                def do_GET(self):
                    if self.path.split('?',1)[0]!='/seek-race.mp4':
                        self.send_error(404);return
                    start=0;end=size-1;partial=False
                    v=self.headers.get('Range')
                    if v:
                        m=re.fullmatch(r'bytes=(\d+)-(\d*)',v)
                        if not m:self.send_error(416);return
                        start=int(m[1]);end=min(size-1,int(m[2])) if m[2] else size-1;partial=True
                    if start>end or start>=size:self.send_error(416);return
                    with lock: starts.append(start)
                    self.send_response(206 if partial else 200)
                    self.send_header('Content-Type','video/mp4')
                    self.send_header('Accept-Ranges','bytes')
                    self.send_header('Content-Length',str(end-start+1))
                    if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
                    self.send_header('Connection','close');self.end_headers()
                    try:
                        with media.open('rb') as f:
                            f.seek(start);left=end-start+1
                            while left:
                                b=f.read(min(left,32768))
                                if not b:break
                                self.wfile.write(b);self.wfile.flush();left-=len(b)
                                time.sleep(.012)  # Keep producer in flight during first seek.
                    except (BrokenPipeError,ConnectionResetError): pass

            server=http.server.ThreadingHTTPServer(('127.0.0.1',0),H);port=server.server_port
            threading.Thread(target=server.serve_forever,daemon=True).start()
            adb('reverse',f'tcp:{port}',f'tcp:{port}')
            adb('shell','am force-stop '+PACKAGE);adb('logcat','-c')
            url=f'http://127.0.0.1:{port}/seek-race.mp4'
            adb('shell',f'am start -W -n {PLAYER} -a android.intent.action.VIEW -d {shlex.quote(url)} -t video/mp4',timeout=30)

            base=wait_for(lambda t:
                'ETYPE_MP4' in t and
                'NOVA_RAW128_OPEN: phase=pre_probe' in t and
                'NOVA_STARTUP_TRACE first_frame_sink' in t,
                35,'MP4 first frame with pre-probe RAW128')
            if 'moov atom not found' in base or 'error opening parser' in base:
                raise RuntimeError('MP4 failed before runtime-seek stress')

            # Catch the exact Run466 class of regression before any test input:
            # the RAW producer must survive beyond first frame without a native
            # crash or spontaneous PlayerActivity exit.
            time.sleep(3)
            stable=logs()
            if 'Fatal signal 11' in stable or 'SIGSEGV' in stable:
                raise RuntimeError('MP4 RAW producer crashed before user seek')
            if PLAYER not in resumed():
                raise RuntimeError('PlayerActivity exited before MP4 seek stress')
            # Fail if the fixture fully downloaded before we exercised any seek.
            metrics = re.findall(r'NOVA_RAW128: produced=(\d+) consumed=(\d+)[^\n]*eof=(\d+)', stable)
            if not metrics or metrics[-1][2] != '0':
                raise RuntimeError('RAW producer reached EOF before first seek; throttle fixture more')

            # Establish controller focus without seeking.
            adb('shell','input keyevent 20');time.sleep(.35)
            adb('shell','input keyevent 20');time.sleep(.35)

            events=[]
            for i in range(8):
                for label,key,direction in [('fwd',22,1),('back',21,-1)]:
                    marker='NOVA_MP4_RAW_SEEK_'+str(i)+'_'+label+'_'+str(time.monotonic_ns())
                    adb('shell','log -p i -t NOVA_MP4_RAW_SEEK_TEST '+marker)
                    adb('shell','input keyevent '+str(key))
                    # Direct-transport APK does not contain the optional
                    # controlbar timer; require real RAW reads after each seek.
                    text=wait_for(lambda t: seek_action_result(t,marker,direction) is not None,
                                  20,'MP4 '+label+' native RAW seek and resumed reads '+str(i))
                    phase=text[text.rfind(marker):]
                    event=seek_action_result(text,marker,direction)
                    if event is None:raise RuntimeError('Scoped seek evidence lost')
                    events.append({'direction':label,**event})
                    if 'moov atom not found' in phase or 'error opening parser' in phase:
                        raise RuntimeError('MP4 parser failed during runtime seek stress')
                    if 'NOVA_PLAYBACK_COMPLETE' in phase:
                        raise RuntimeError('Unexpected completion during MP4 seek stress')
                    if PLAYER not in resumed():
                        raise RuntimeError('PlayerActivity exited during MP4 seek stress')

            final=wait_for(lambda t:'NOVA_RAW128:' in t and PLAYER in resumed(),
                           5,'MP4 still active after RAW seek stress')
            if 'error opening parser' in final or 'moov atom not found' in final:
                raise RuntimeError('MP4 parser failure after seek stress')
            raw_seek_count=final.count('NOVA_RAW128_SEEK:')
            cache_seek_count=final.count('NOVA_RAW_CACHE_SEEK_V1:')
            if 'NOVA_SEEK_SAFE_SERIAL_V2: seek_finish' not in final:
                raise RuntimeError('Safe serialized seek did not execute; wrong APK?')
            if 'NOVA_RAW_RETRY: error=-1414092869' in final:
                raise RuntimeError('Seek cancellation poisoned AVIO: AVERROR_EXIT retry observed')
            if raw_seek_count + cache_seek_count < 8:
                raise RuntimeError('Too few validated native seeks: network='+str(raw_seek_count)+
                                   ' cached='+str(cache_seek_count))
            with lock:ranges=list(starts)
            report.update(status='PASS',size=size,seek_events=events,
                          raw_seek_count=raw_seek_count,cache_seek_count=cache_seek_count,
                          range_starts=ranges,
                          player_alive=True)
            (a.reports/'mp4-raw-seek-race-logcat.txt').write_text(final)
            print('MP4_RAW_SEEK_RACE_SMOKE=PASS '+json.dumps(report))
    except Exception as e:
        report['error']=str(e);raise
    finally:
        try:(a.reports/'mp4-raw-seek-race-last-logcat.txt').write_text(logs())
        except Exception:pass
        try:adb('shell','am force-stop '+PACKAGE)
        except Exception:pass
        if port:
            try:adb('reverse','--remove',f'tcp:{port}')
            except Exception:pass
        if server:server.shutdown();server.server_close()
        (a.reports/'mp4-raw-seek-race.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
