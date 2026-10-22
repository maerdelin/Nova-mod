#!/usr/bin/env python3
"""Regression: BACK during active RAW HTTP playback must release without retry/ANR."""
import argparse, http.server, json, re, shlex, subprocess, tempfile, threading, time
from pathlib import Path

PACKAGE='org.courville.nova'
PLAYER=PACKAGE+'/com.archos.mediacenter.video.player.PlayerActivity'
BROWSER='com.archos.mediacenter.video.browser.MainActivity'

def run(args,timeout=30):
    r=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=timeout)
    if r.returncode:
        raise RuntimeError('Command failed: '+str(args[:4])+'\n'+r.stdout+r.stderr)
    return r.stdout

def adb(*args,timeout=30): return run(['adb',*args],timeout=timeout)
def logs(): return adb('logcat','-d','-v','threadtime',timeout=20)

def resumed():
    t=adb('shell','dumpsys activity activities',timeout=20)
    m=re.search(r'mResumedActivity:.*? ([^ ]+/[^ }]+)',t)
    return m.group(1) if m else ''

def launcher():
    for cat in ('android.intent.category.LEANBACK_LAUNCHER','android.intent.category.LAUNCHER'):
        out=adb('shell','cmd package resolve-activity --brief -a android.intent.action.MAIN -c '+cat+' '+PACKAGE)
        xs=[x.strip() for x in out.splitlines() if x.strip().startswith(PACKAGE+'/')]
        if len(xs)==1: return xs[0]
    raise RuntimeError('No launcher activity')

def main():
    p=argparse.ArgumentParser(); p.add_argument('--reports',type=Path,required=True); a=p.parse_args()
    a.reports.mkdir(parents=True,exist_ok=True)
    report={'status':'FAIL','scope':'Run496 RAW BACK/release hotfix'}
    server=None;port=None
    try:
        if adb('shell','getprop ro.kernel.qemu').strip()!='1':
            raise RuntimeError('CI emulator required')
        with tempfile.TemporaryDirectory(prefix='nova-back-') as td:
            media=Path(td)/'active.m2ts'
            run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=24',
                 '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','45',
                 '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-g','24',
                 '-b:v','3M','-c:a','aac','-b:a','96k','-f','mpegts',media],timeout=90)
            size=media.stat().st_size

            class H(http.server.BaseHTTPRequestHandler):
                def log_message(self,*_): pass
                def do_GET(self):
                    if self.path.split('?',1)[0]!='/active.m2ts': self.send_error(404); return
                    start=0; end=size-1; partial=False
                    v=self.headers.get('Range')
                    if v:
                        m=re.fullmatch(r'bytes=(\d+)-(\d*)',v)
                        if not m: self.send_error(416); return
                        start=int(m[1]); end=min(size-1,int(m[2])) if m[2] else size-1; partial=True
                    if start>end or start>=size: self.send_error(416); return
                    self.send_response(206 if partial else 200)
                    self.send_header('Content-Type','video/mp2t')
                    self.send_header('Accept-Ranges','bytes')
                    self.send_header('Content-Length',str(end-start+1))
                    self.send_header('Connection','close')
                    if partial: self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
                    self.end_headers()
                    try:
                        with media.open('rb') as f:
                            f.seek(start); left=end-start+1
                            while left:
                                b=f.read(min(left,32768))
                                if not b: break
                                self.wfile.write(b); self.wfile.flush(); left-=len(b)
                                time.sleep(.03)
                    except (BrokenPipeError,ConnectionResetError,OSError):
                        pass

            server=http.server.ThreadingHTTPServer(('127.0.0.1',0),H)
            port=server.server_port
            threading.Thread(target=server.serve_forever,daemon=True).start()
            adb('reverse',f'tcp:{port}',f'tcp:{port}')
            adb('shell','am force-stop '+PACKAGE)
            home=launcher()
            if 'Status: ok' not in adb('shell','am start -W -n '+home,timeout=30):
                raise RuntimeError('launcher start failed')
            adb('logcat','-c')
            url=f'http://127.0.0.1:{port}/active.m2ts'
            adb('shell',f'am start -W -n {PLAYER} -a android.intent.action.VIEW -d {shlex.quote(url)} -t video/mp2t',timeout=30)

            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                t=logs()
                if 'NOVA_RAW128_OPEN:' in t and 'first_frame_sink' in t:
                    break
                time.sleep(.25)
            else:
                raise RuntimeError('active RAW playback did not reach first frame')

            adb('shell','input keyevent KEYCODE_BACK',timeout=10)
            deadline=time.monotonic()+8; last=''
            while time.monotonic()<deadline:
                last=logs()
                if 'NOVA_RAW_ABORT: reason=stream_stop' in last and BROWSER in resumed():
                    break
                time.sleep(.25)
            else:
                raise RuntimeError('BACK did not release player promptly')

            time.sleep(5.5)
            final=logs()
            abort_at=final.rfind('NOVA_RAW_ABORT: reason=stream_stop')
            if abort_at<0: raise RuntimeError('missing RAW early-abort marker')
            after=final[abort_at:]
            if 'NOVA_RAW_RETRY:' in after: raise RuntimeError('RAW retry after shutdown abort')
            if 'Input dispatching timed out' in after or ('ANR in '+PACKAGE) in after:
                raise RuntimeError('ANR/input timeout after return')
            if BROWSER not in resumed(): raise RuntimeError('browser not resumed after return')

            adb('shell','input keyevent KEYCODE_DPAD_DOWN',timeout=10)
            time.sleep(.5)
            tail=logs()[abort_at:]
            if 'Input dispatching timed out' in tail or ('ANR in '+PACKAGE) in tail:
                raise RuntimeError('browser input became unresponsive after return')

            report.update(status='PASS',early_abort=True,retry_after_abort=False,no_anr=True,browser_responsive=True)
            (a.reports/'back-release-logcat.txt').write_text(final)
            print('BACK_RELEASE_SMOKE=PASS '+json.dumps(report))
    except Exception as e:
        report['error']=str(e); raise
    finally:
        try: (a.reports/'back-release-last-logcat.txt').write_text(logs())
        except Exception: pass
        try: adb('shell','am force-stop '+PACKAGE)
        except Exception: pass
        if port:
            try: adb('reverse','--remove',f'tcp:{port}')
            except Exception: pass
        if server: server.shutdown(); server.server_close()
        (a.reports/'back-release.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__': main()
