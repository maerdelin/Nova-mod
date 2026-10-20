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
import xml.etree.ElementTree as ET

PACKAGE='org.courville.nova'

def run(args, timeout=30):
    r=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=timeout)
    if r.returncode:raise RuntimeError('Command failed: '+str(args[:3])+'\n'+r.stdout+r.stderr)
    return r.stdout

def adb(*args,timeout=30):return run(['adb',*args],timeout)

def action_result(text, marker, direction):
    """Require this action's real seek and later ready/hide, never an old log line."""
    at = text.rfind(marker)
    if at < 0: return None
    phase = text[at + len(marker):]
    events = list(re.finditer(r'avos_mp_video_seek current_pos=(\d+) to pos=(\d+)', phase))
    relevant = [m for m in events if (int(m[2])-int(m[1]))*direction > 0]
    if not relevant: return None
    seek = relevant[-1]
    tail = phase[seek.end():]
    if 'NOVA_ISO_TIME_SEEK' not in tail or 'byteMode=0' not in tail: return None
    ready = tail.rfind('HIDE_READY')
    hide = tail.rfind('HIDE_DONE')
    if ready < 0 or hide < ready: return None
    return (int(seek[1]), int(seek[2]), phase)

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
            # A fresh phone emulator starts in touch mode. Establish DPAD focus
            # and dismiss the one-time help overlay with a non-seek direction.
            # This does not move playback; the measured seek still uses real keys.
            (a.reports/'seek-playback-start-logcat.txt').write_text(logs())
            adb('shell','input keyevent 20');time.sleep(0.5)
            adb('shell','input keyevent 20');time.sleep(0.5)
            try:
                adb('shell','uiautomator dump /data/local/tmp/nova-seek-before.xml',timeout=15)
                (a.reports/'seek-playback-before.xml').write_text(adb('shell','cat /data/local/tmp/nova-seek-before.xml'))
            except Exception as diag:
                report['ui_diagnostic_warning']=str(diag)
            report['input_setup']='DPAD_DOWN establishes focus; no pause/play or seek issued'
            # logcat -c does not necessarily clear every buffer. Isolate each
            # action with a unique marker and require HIDE_DONE AFTER its seek.
            # No startup/other-process/previous-action hide can satisfy the gate.
            results = {}
            for label, key, direction in [('forward',22,1),('backward',21,-1)]:
                marker = 'NOVA_ACTION_' + label.upper() + '_' + str(time.monotonic_ns())
                adb('shell', 'log -p i -t NOVA_SEEK_TEST ' + marker)
                adb('shell', 'input keyevent ' + str(key))
                text=wait_for(lambda t:action_result(t,marker,direction) is not None,20,label+' 5s seek and same-action auto hide')
                before,after,phase=action_result(text,marker,direction)
                if not 4500 <= (after-before)*direction <= 5500:
                    raise RuntimeError('Short '+label+' seek not approximately 5000ms: '+repr((before,after)))
                (a.reports/('seek-playback-'+label+'.txt')).write_text(phase)
                results[label+'_ms']=[before,after]
                # Verify actual view disappearance, not only that the timer fired.
                target='/data/local/tmp/nova-seek-'+label+'-hidden.xml'
                adb('shell','uiautomator dump '+target,timeout=15)
                xml=adb('shell','cat '+target)
                (a.reports/('seek-playback-'+label+'-hidden.xml')).write_text(xml)
                hierarchy=ET.fromstring(xml[xml.index('<?xml'):])
                visible_ids={n.attrib.get('resource-id','') for n in hierarchy.iter('node')}
                if PACKAGE+':id/control_bar' in visible_ids or PACKAGE+':id/seek_progress' in visible_ids:
                    raise RuntimeError('Controller remains visible after '+label+' HIDE_DONE')
                results[label+'_controls_hidden']=True
            report.update(results)
            report['hide_after_release']='same-action HIDE_DONE plus actual controller absent from UI hierarchy; no pause/play input'
            report['status']='PASS';print('SEEK_PLAYBACK_SMOKE=PASS '+json.dumps(report))
    except Exception as error:
        report['error']=str(error)
        try:
            adb('shell','uiautomator dump /data/local/tmp/nova-seek-failure.xml',timeout=15)
            (a.reports/'seek-playback-failure.xml').write_text(adb('shell','cat /data/local/tmp/nova-seek-failure.xml'))
        except Exception:pass
        raise
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
