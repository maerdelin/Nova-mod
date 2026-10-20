#!/usr/bin/env python3
"""Final APK/AVOS synthetic single-clip M2TS timeline and real DPAD smoke test.

Runs only after clean CI emulator installation. The local M2TS represents the
bytes emitted by the ISO bridge; this does NOT validate a real ISO, cloud server,
hardware decoder, disc playlist/index or throughput. Never run on a user device.
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

def run(args, timeout=30):
    r=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=timeout)
    if r.returncode:raise RuntimeError('Command failed: '+str(args[:3])+'\n'+r.stdout+r.stderr)
    return r.stdout

def adb(*args,timeout=30):return run(['adb',*args],timeout)

def main():
    p=argparse.ArgumentParser();p.add_argument('--reports',type=Path,required=True);a=p.parse_args()
    a.reports.mkdir(parents=True,exist_ok=True)
    report={'status':'FAIL','scope':'final APK real playback/DPAD of synthetic single-clip M2TS over local Range server; no real ISO/cloud/device acceptance'}
    server=None;port=None
    try:
        if adb('shell','getprop ro.kernel.qemu').strip()!='1':raise RuntimeError('Fresh CI emulator required')
        with tempfile.TemporaryDirectory(prefix='nova-seek-media-')as temp:
            root=Path(temp);media=root/'main.m2ts'
            run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=24','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','60','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-g','24','-c:a','aac','-b:a','64k','-mpegts_m2ts_mode','1','-f','mpegts',media],timeout=60)
            duration=json.loads(run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',media]))['format']['duration']
            duration_us=int(float(duration)*1000000);size=media.stat().st_size
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self,*_):pass
                def do_GET(self):
                    if self.path.split('?',1)[0]!='/main.m2ts':self.send_error(404);return
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
                        with media.open('rb')as f:
                            f.seek(start);left=end-start+1
                            while left:
                                b=f.read(min(left,65536))
                                if not b:break
                                self.wfile.write(b);left-=len(b)
                    except (BrokenPipeError,ConnectionResetError):pass
            server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);port=server.server_port
            threading.Thread(target=server.serve_forever,daemon=True).start()
            adb('reverse',f'tcp:{port}',f'tcp:{port}')
            adb('shell','am force-stop '+PACKAGE);adb('logcat','-c')
            url=f'http://127.0.0.1:{port}/main.m2ts?mpegts&nova_iso=1&nova_iso_duration_us={duration_us}&nova_iso_clip_count=1&nova_iso_title_size={size}&nova_iso_generation=1'
            intent=f'am start -W -n {PACKAGE}/com.archos.mediacenter.video.player.PlayerActivity -a android.intent.action.VIEW -d {shlex.quote(url)} -t video/mp2t'
            runlog=adb('shell',intent,timeout=30)
            report.update(duration_us=duration_us,size=size,start_output=runlog)
            def logs():return adb('logcat','-d','-v','threadtime')
            def wait_for(predicate,seconds,label):
                end=time.monotonic()+seconds
                while time.monotonic()<end:
                    text=logs()
                    if predicate(text):return text
                    time.sleep(0.5)
                raise RuntimeError('Missing '+label)
            wait_for(lambda t:'NOVA_ISO_TIMELINE_READY' in t and 'first_frame_sink' in t,35,'native timeline and first frame')
            # Keep the fixture far from either endpoint. Real input down/up is
            # handled by the shipped PlayerController, not a test seek call.
            time.sleep(2);adb('logcat','-c');adb('shell','input keyevent 22')
            text=wait_for(lambda t:'NOVA_ISO_TIME_SEEK' in t and 'HIDE_DONE' in t,20,'5s seek and automatic control hide')
            matches=re.findall(r'avos_mp_video_seek current_pos=(\d+) to pos=(\d+)',text)
            forward=[(int(x),int(y))for x,y in matches if int(y)>int(x)]
            if not forward or not 4500<=forward[0][1]-forward[0][0]<=5500:
                raise RuntimeError('Short DPAD seek was not approximately +5000ms: '+repr(matches))
            if 'byteMode=0'not in text:raise RuntimeError('Timestamp seek diagnostic absent')
            (a.reports/'seek-playback-forward.txt').write_text(text)
            report['forward_ms']=forward[0];report['hide_after_release']='HIDE_DONE without pause/play input'
            adb('logcat','-c');adb('shell','input keyevent 21')
            text=wait_for(lambda t:'NOVA_ISO_TIME_SEEK' in t and 'HIDE_DONE' in t,20,'backward seek and auto hide')
            matches=re.findall(r'avos_mp_video_seek current_pos=(\d+) to pos=(\d+)',text)
            backward=[(int(x),int(y))for x,y in matches if int(y)<int(x)]
            if not backward or not 4500<=backward[0][0]-backward[0][1]<=5500:
                raise RuntimeError('Short DPAD seek was not approximately -5000ms: '+repr(matches))
            (a.reports/'seek-playback-backward.txt').write_text(text);report['backward_ms']=backward[0]
            report['status']='PASS';print('SEEK_PLAYBACK_SMOKE=PASS '+json.dumps(report))
    except Exception as error:report['error']=str(error);raise
    finally:
        try:(a.reports/'seek-playback-last-logcat.txt').write_text(adb('logcat','-d','-v','threadtime'))
        except Exception:pass
        try:adb('shell','am force-stop '+PACKAGE)
        except Exception:pass
        if port:
            try:adb('reverse','--remove',f'tcp:{port}')
            except Exception:pass
        if server:server.shutdown();server.server_close()
        (a.reports/'seek-playback.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
