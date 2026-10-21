#!/usr/bin/env python3
"""Final-APK regression: play, seek near EOF, then naturally complete to Nova browser.

The seek is generated through real DPAD input. Completion must be emitted by the
AVOS player itself; the script never sends BACK/STOP after the final seek.
The source is a local HTTP Range server, so this validates player state only,
not cloud/WebDAV/STB transport behavior.
"""
import argparse
import http.server
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import threading
import time

PACKAGE='org.courville.nova'
PLAYER=PACKAGE+'/com.archos.mediacenter.video.player.PlayerActivity'

def run(args,timeout=30):
    r=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=timeout)
    if r.returncode: raise RuntimeError('Command failed: '+str(args[:4])+'\n'+r.stdout+r.stderr)
    return r.stdout

def adb(*args,timeout=30): return run(['adb',*args],timeout=timeout)

def logs(): return adb('logcat','-d','-v','threadtime',timeout=20)

def resumed():
    text=adb('shell','dumpsys activity activities',timeout=20)
    m=re.search(r'mResumedActivity:.*? ([^ ]+/[^ }]+)',text)
    return m.group(1) if m else ''

def launcher():
    for category in ('android.intent.category.LEANBACK_LAUNCHER','android.intent.category.LAUNCHER'):
        out=adb('shell','cmd package resolve-activity --brief -a android.intent.action.MAIN -c '+category+' '+PACKAGE)
        matches=[x.strip() for x in out.splitlines() if x.strip().startswith(PACKAGE+'/')]
        if len(matches)==1:return matches[0]
    raise RuntimeError('No exported launcher activity resolved')

def wait_for(predicate,seconds,label):
    end=time.monotonic()+seconds
    last=''
    while time.monotonic()<end:
        last=logs()
        if predicate(last): return last
        time.sleep(0.35)
    raise RuntimeError('Missing '+label)

def seek_after_marker(text,marker):
    at=text.rfind(marker)
    if at<0:return None
    phase=text[at+len(marker):]
    events=list(re.finditer(r'avos_mp_video_seek current_pos=(\d+) to pos=(\d+)',phase))
    if not events:return None
    m=events[-1]
    if int(m[2])<=int(m[1]):return None
    tail=phase[m.end():]
    if 'NOVA_ISO_TIME_SEEK' not in tail:return None
    return int(m[1]),int(m[2]),phase

def main():
    p=argparse.ArgumentParser();p.add_argument('--reports',type=Path,required=True);a=p.parse_args()
    a.reports.mkdir(parents=True,exist_ok=True)
    report={'status':'FAIL','scope':'final APK DPAD seek-near-EOF then natural player-owned completion on local HTTP Range M2TS'}
    server=None;port=None
    try:
        if adb('shell','getprop ro.kernel.qemu').strip()!='1':raise RuntimeError('Fresh CI emulator required')
        with tempfile.TemporaryDirectory(prefix='nova-seek-eof-') as td:
            root=Path(td);media=root/'seek-eof.m2ts'
            run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=24',
                 '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','30',
                 '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-g','24',
                 '-c:a','aac','-b:a','64k','-mpegts_m2ts_mode','1','-f','mpegts',media],timeout=60)
            duration=float(json.loads(run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',media]))['format']['duration'])
            duration_ms=int(duration*1000);duration_us=int(duration*1000000);size=media.stat().st_size
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self,*_):pass
                def do_GET(self):
                    if self.path.split('?',1)[0]!='/seek-eof.m2ts':self.send_error(404);return
                    start=0;end=size-1;partial=False
                    value=self.headers.get('Range')
                    if value:
                        m=re.fullmatch(r'bytes=(\d+)-(\d*)',value)
                        if not m:self.send_error(416);return
                        start=int(m[1]);end=min(size-1,int(m[2])) if m[2] else size-1;partial=True
                    if start>end or start>=size:self.send_error(416);return
                    self.send_response(206 if partial else 200)
                    self.send_header('Content-Type','video/mp2t');self.send_header('Accept-Ranges','bytes')
                    self.send_header('Content-Length',str(end-start+1));self.send_header('Connection','close')
                    if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
                    self.end_headers()
                    try:
                        with media.open('rb') as f:
                            f.seek(start);left=end-start+1
                            while left:
                                b=f.read(min(left,65536))
                                if not b:break
                                self.wfile.write(b);left-=len(b)
                    except (BrokenPipeError,ConnectionResetError):pass
            server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);port=server.server_port
            threading.Thread(target=server.serve_forever,daemon=True).start()
            adb('reverse',f'tcp:{port}',f'tcp:{port}')
            adb('shell','am force-stop '+PACKAGE)
            home=launcher()
            adb('shell','am start -W -n '+home,timeout=30)
            adb('logcat','-c')
            url=(f'http://127.0.0.1:{port}/seek-eof.m2ts?mpegts&nova_iso=1'
                 f'&nova_iso_duration_us={duration_us}&nova_iso_clip_count=1'
                 f'&nova_iso_title_size={size}&nova_iso_generation=1')
            adb('shell',f'am start -W -n {PLAYER} -a android.intent.action.VIEW -d {shlex.quote(url)} -t video/mp2t',timeout=30)
            wait_for(lambda t:'first_frame_sink' in t,20,'first frame')
            adb('shell','input keyevent 20');time.sleep(0.4)
            adb('shell','input keyevent 20');time.sleep(0.4)

            seeks=[]
            final_marker=''
            for n in range(8):
                marker='NOVA_SEEK_EOF_'+str(n)+'_'+str(time.monotonic_ns())
                final_marker=marker
                adb('shell','log -p i -t NOVA_SEEK_EOF_TEST '+marker)
                adb('shell','input keyevent 22')
                text=wait_for(lambda t:seek_after_marker(t,marker) is not None,15,'forward seek '+str(n))
                before,after,phase=seek_after_marker(text,marker)
                if not 4000 <= after-before <= 6000:
                    raise RuntimeError('Seek step not approximately 5s: '+repr((before,after)))
                seeks.append([before,after])
                if duration_ms-7500 <= after < duration_ms-1000:
                    break
                time.sleep(0.35)
            if not seeks or not (duration_ms-7500 <= seeks[-1][1] < duration_ms-1000):
                raise RuntimeError('Failed to land safely near EOF: '+repr((duration_ms,seeks)))

            start=time.monotonic()
            text=wait_for(lambda t:
                final_marker in t and
                'NOVA_PLAYBACK_COMPLETE' in t[t.rfind(final_marker):] and
                'com.archos.mediacenter.video.browser.MainActivity' in resumed(),
                20,'seek-to-EOF completion and browser return')
            elapsed=time.monotonic()-start
            phase=text[text.rfind(final_marker):]
            if 'Back navigation: OnBackPressedDispatcher callback' in phase:
                raise RuntimeError('Test observed BACK navigation after final seek; completion was not player-owned')
            (a.reports/'seek-eof-completion-logcat.txt').write_text(phase)
            report.update(status='PASS',duration_ms=duration_ms,seeks_ms=seeks,
                          final_remaining_ms=duration_ms-seeks[-1][1],
                          completion_wait_s=elapsed,
                          native_completion=True,returned_to_browser=True,
                          no_back_input=True)
            print('SEEK_EOF_COMPLETION_SMOKE=PASS '+json.dumps(report))
    except Exception as e:
        report['error']=str(e);raise
    finally:
        try:(a.reports/'seek-eof-completion-last-logcat.txt').write_text(logs())
        except Exception:pass
        try:adb('shell','am force-stop '+PACKAGE)
        except Exception:pass
        if port:
            try:adb('reverse','--remove',f'tcp:{port}')
            except Exception:pass
        if server:server.shutdown();server.server_close()
        (a.reports/'seek-eof-completion.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
