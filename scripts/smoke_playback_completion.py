#!/usr/bin/env python3
"""Natural-end playback smoke on the final APK using a short local H264/AAC M2TS.

This validates player-owned EOF -> completion -> PlayerActivity finish on the CI
emulator only. It is not a real WebDAV/cloud/STB acceptance test.
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
BROWSER=PACKAGE+'/com.archos.mediacenter.video.browser.MainActivity'

def run(args,timeout=30):
    r=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=timeout)
    if r.returncode: raise RuntimeError('Command failed: '+str(args[:4])+'\n'+r.stdout+r.stderr)
    return r.stdout

def adb(*args,timeout=30): return run(['adb',*args],timeout=timeout)

def resumed():
    text=adb('shell','dumpsys activity activities',timeout=20)
    m=re.search(r'mResumedActivity:.*? ([^ ]+/[^ }]+)',text)
    return m.group(1) if m else ''

def main():
    p=argparse.ArgumentParser();p.add_argument('--reports',type=Path,required=True);a=p.parse_args()
    a.reports.mkdir(parents=True,exist_ok=True)
    report={'status':'FAIL','scope':'final APK natural EOF on synthetic local H264/AAC M2TS; no real WebDAV/cloud/STB acceptance'}
    server=None;port=None
    try:
        if adb('shell','getprop ro.kernel.qemu').strip()!='1': raise RuntimeError('Fresh CI emulator required')
        with tempfile.TemporaryDirectory(prefix='nova-eof-') as td:
            root=Path(td);media=root/'end.m2ts'
            run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=24',
                 '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','7',
                 '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-g','24',
                 '-c:a','aac','-b:a','64k','-mpegts_m2ts_mode','1','-f','mpegts',media],timeout=60)
            size=media.stat().st_size
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self,*_): pass
                def do_GET(self):
                    if self.path.split('?',1)[0]!='/end.m2ts': self.send_error(404);return
                    start=0;end=size-1;partial=False
                    value=self.headers.get('Range')
                    if value:
                        m=re.fullmatch(r'bytes=(\d+)-(\d*)',value)
                        if not m: self.send_error(416);return
                        start=int(m[1]);end=min(size-1,int(m[2])) if m[2] else size-1;partial=True
                    if start>end or start>=size: self.send_error(416);return
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
                    except (BrokenPipeError,ConnectionResetError): pass
            server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);port=server.server_port
            threading.Thread(target=server.serve_forever,daemon=True).start()
            adb('reverse',f'tcp:{port}',f'tcp:{port}')
            adb('shell','am force-stop '+PACKAGE)
            adb('shell','am start -W -n '+BROWSER,timeout=30)
            adb('logcat','-c')
            url=f'http://127.0.0.1:{port}/end.m2ts'
            adb('shell',f'am start -W -n {PLAYER} -a android.intent.action.VIEW -d {shlex.quote(url)} -t video/mp2t',timeout=30)
            deadline=time.monotonic()+35
            first=False;complete=False;returned=False
            last=''
            while time.monotonic()<deadline:
                last=adb('logcat','-d','-v','threadtime',timeout=20)
                first=first or 'first_frame_sink' in last
                complete=complete or 'NOVA_PLAYBACK_COMPLETE' in last
                top=resumed()
                if first and complete and 'video.browser.MainActivity' in top:
                    returned=True;break
                time.sleep(0.5)
            (a.reports/'playback-completion-logcat.txt').write_text(last)
            if not first: raise RuntimeError('No first frame before EOF')
            if not complete: raise RuntimeError('Native player completion was not emitted')
            if not returned: raise RuntimeError('PlayerActivity did not finish back to MainActivity')
            report.update(status='PASS',first_frame=True,native_completion=True,returned_to_browser=True)
            print('PLAYBACK_COMPLETION_SMOKE=PASS '+json.dumps(report))
    except Exception as e:
        report['error']=str(e);raise
    finally:
        try:(a.reports/'playback-completion-last-logcat.txt').write_text(adb('logcat','-d','-v','threadtime'))
        except Exception:pass
        try:adb('shell','am force-stop '+PACKAGE)
        except Exception:pass
        if port:
            try:adb('reverse','--remove',f'tcp:{port}')
            except Exception:pass
        if server:server.shutdown();server.server_close()
        (a.reports/'playback-completion.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
