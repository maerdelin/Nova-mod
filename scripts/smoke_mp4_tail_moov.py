#!/usr/bin/env python3
"""Final-APK regression for MP4 whose moov atom is at the tail.

The Range server records probe-time seeks. Success requires:
1) the file really has a late top-level moov,
2) FFmpeg completes native URL probe without "moov atom not found",
3) one stable RAW10X AVIO is active before probe and survives tail seeks,
4) the final APK renders a frame.
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
def wait_for(pred,seconds,label):
    end=time.monotonic()+seconds;last=''
    while time.monotonic()<end:
        last=logs()
        if pred(last): return last
        time.sleep(.25)
    raise RuntimeError('Missing '+label)

def top_atoms(path):
    out=[];size=path.stat().st_size
    with path.open('rb') as f:
        pos=0
        while pos+8<=size:
            f.seek(pos);h=f.read(16)
            n=int.from_bytes(h[:4],'big');typ=h[4:8].decode('latin1')
            head=8
            if n==1:
                if len(h)<16: break
                n=int.from_bytes(h[8:16],'big');head=16
            elif n==0:
                n=size-pos
            if n<head or pos+n>size: break
            out.append((typ,pos,n));pos+=n
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument('--reports',type=Path,required=True);a=p.parse_args()
    a.reports.mkdir(parents=True,exist_ok=True)
    report={'status':'FAIL','scope':'final APK late-moov MP4 over one stable pre-probe RAW10X AVIO'}
    server=None;port=None
    try:
        with tempfile.TemporaryDirectory(prefix='nova-tail-moov-') as td:
            root=Path(td);media=root/'tail-moov.mp4'
            run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=1280x720:rate=30',
                 '-f','lavfi','-i','sine=frequency=523:sample_rate=48000','-t','12',
                 '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',
                 '-b:v','8M','-maxrate','8M','-bufsize','16M','-g','60',
                 '-c:a','aac','-b:a','160k','-f','mp4',media],timeout=120)
            size=media.stat().st_size
            atoms=top_atoms(media)
            moovs=[x for x in atoms if x[0]=='moov']
            mdats=[x for x in atoms if x[0]=='mdat']
            if not moovs or not mdats:
                raise RuntimeError('Generated MP4 missing moov/mdat: '+repr(atoms))
            moov_off=moovs[-1][1];mdat_off=mdats[0][1]
            if not (mdat_off < moov_off and moov_off > size*0.70):
                raise RuntimeError('Generated MP4 is not a late-moov file: '+repr((size,atoms)))

            starts=[];lock=threading.Lock()
            class H(http.server.BaseHTTPRequestHandler):
                protocol_version='HTTP/1.1'
                def log_message(self,*_): pass
                def do_GET(self):
                    if self.path.split('?',1)[0]!='/tail-moov.mp4':
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
                                b=f.read(min(left,65536))
                                if not b:break
                                self.wfile.write(b);left-=len(b)
                    except (BrokenPipeError,ConnectionResetError): pass

            server=http.server.ThreadingHTTPServer(('127.0.0.1',0),H);port=server.server_port
            threading.Thread(target=server.serve_forever,daemon=True).start()
            adb('reverse',f'tcp:{port}',f'tcp:{port}')
            adb('shell','am force-stop '+PACKAGE);adb('logcat','-c')
            url=f'http://127.0.0.1:{port}/tail-moov.mp4'
            adb('shell',f'am start -W -n {PLAYER} -a android.intent.action.VIEW -d {shlex.quote(url)} -t video/mp4',timeout=30)
            text=wait_for(lambda t:
                'ETYPE_MP4' in t and
                'NOVA_RAW10X_OPEN: phase=pre_probe' in t and
                'NOVA_STARTUP_TRACE probe_done' in t and
                'NOVA_RAW10X_SEEK:' in t and
                'NOVA_STARTUP_TRACE first_frame_sink' in t,
                35,'late-moov MP4 pre-probe RAW seek, probe completion and first frame')
            if 'moov atom not found' in text:
                raise RuntimeError('late-moov MP4 still failed probe')
            raw_i=text.index('NOVA_RAW10X_OPEN: phase=pre_probe')
            probe_i=text.index('NOVA_STARTUP_TRACE probe_done')
            if raw_i > probe_i:
                raise RuntimeError('RAW AVIO was not installed before MP4 probe')
            with lock: ranges=list(starts)
            far=[x for x in ranges if x>size*0.60]
            if not far:
                raise RuntimeError('HTTP server did not observe a far tail Range seek: '+repr(ranges))
            report.update(status='PASS',size=size,moov_offset=moov_off,
                          moov_fraction=moov_off/size,range_starts=ranges,
                          far_tail_range=True,raw_before_probe=True,
                          raw_seek_seen=True,first_frame=True)
            (a.reports/'mp4-tail-moov-logcat.txt').write_text(text)
            print('MP4_TAIL_MOOV_SMOKE=PASS '+json.dumps(report))
    except Exception as e:
        report['error']=str(e)
        try:
            with lock:
                report['range_starts']=list(starts)
        except Exception:
            pass
        raise
    finally:
        try:(a.reports/'mp4-tail-moov-last-logcat.txt').write_text(logs())
        except Exception:pass
        try:adb('shell','am force-stop '+PACKAGE)
        except Exception:pass
        if port:
            try:adb('reverse','--remove',f'tcp:{port}')
            except Exception:pass
        if server:server.shutdown();server.server_close()
        (a.reports/'mp4-tail-moov.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
