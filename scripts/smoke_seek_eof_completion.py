#!/usr/bin/env python3
"""Final APK regression for the exact field path: ordinary MPEG-TS position seek -> EOF.

No nova_iso query is used. The player is opened as an ordinary .ts file, DPAD
seeks are issued until avos_mp_video_seek reports a near-tail POSITION target,
then no BACK/STOP input is sent. Success requires the audio worker to perform
its real EOF drain and the existing playback-complete path to return to Nova's
browser.
"""
import argparse,http.server,json,re,shlex,subprocess,tempfile,threading,time
from pathlib import Path

PACKAGE='org.courville.nova'
PLAYER=PACKAGE+'/com.archos.mediacenter.video.player.PlayerActivity'

def run(args,timeout=30):
    r=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=timeout)
    if r.returncode: raise RuntimeError('Command failed: '+str(args[:4])+'\n'+r.stdout+r.stderr)
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
        m=[x.strip() for x in out.splitlines() if x.strip().startswith(PACKAGE+'/')]
        if len(m)==1:return m[0]
    raise RuntimeError('No exported launcher activity')
def wait_for(pred,seconds,label):
    end=time.monotonic()+seconds;last=''
    while time.monotonic()<end:
        last=logs()
        if pred(last):return last
        time.sleep(.35)
    raise RuntimeError('Missing '+label)
def seek_after(text,marker):
    at=text.rfind(marker)
    if at<0:return None
    phase=text[at+len(marker):]
    ms=list(re.finditer(
        r'avos_mp_video_seek current_pos=(\d+) to pos=(\d+) direction=([01])',
        phase))
    if not ms:return None
    m=ms[-1];a=int(m[1]);b=int(m[2]);direction=int(m[3])
    tail=phase[m.end():]
    if 'NOVA_ISO_TIME_SEEK' in tail:return None
    return a,b,direction,phase

def main():
    p=argparse.ArgumentParser();p.add_argument('--reports',type=Path,required=True);a=p.parse_args()
    a.reports.mkdir(parents=True,exist_ok=True)
    report={'status':'FAIL','scope':'ordinary MPEG-TS position seek near EOF; real audio drain; no ISO path; RIGHT no-op events are observed without idle drift'}
    server=None;port=None
    try:
        if adb('shell','getprop ro.kernel.qemu').strip()!='1':raise RuntimeError('Fresh CI emulator required')
        with tempfile.TemporaryDirectory(prefix='nova-ts-eof-') as td:
            root=Path(td);media=root/'ordinary.ts'
            # Match the field content shape: H264 + AAC in MPEG-TS. Audio is
            # slightly longer so video completion must hand off cleanly to the
            # audio worker's terminal drain.
            run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=25',
                 '-f','lavfi','-i','sine=frequency=440:sample_rate=48000',
                 '-t','42','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-g','25',
                 '-c:a','aac','-b:a','160k','-f','mpegts',media],timeout=90)
            size=media.stat().st_size
            class H(http.server.BaseHTTPRequestHandler):
                def log_message(self,*_):pass
                def do_GET(self):
                    if self.path.split('?',1)[0]!='/ordinary.ts':self.send_error(404);return
                    start=0;end=size-1;partial=False
                    v=self.headers.get('Range')
                    if v:
                        m=re.fullmatch(r'bytes=(\d+)-(\d*)',v)
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
            server=http.server.ThreadingHTTPServer(('127.0.0.1',0),H);port=server.server_port
            threading.Thread(target=server.serve_forever,daemon=True).start()
            adb('reverse',f'tcp:{port}',f'tcp:{port}')
            adb('shell','am force-stop '+PACKAGE)
            home=launcher();adb('shell','am start -W -n '+home,timeout=30);adb('logcat','-c')
            url=f'http://127.0.0.1:{port}/ordinary.ts'
            adb('shell',f'am start -W -n {PLAYER} -a android.intent.action.VIEW -d {shlex.quote(url)} -t video/mp2t',timeout=30)
            text=wait_for(lambda t:'first_frame_sink' in t and 'ETYPE_MPEG_TS' in t,30,'ordinary TS first frame')
            if 'NOVA_ISO_TIMELINE_READY' in text or 'nova_iso=1' in text:
                raise RuntimeError('Test accidentally entered ISO path')
            # Run691: "first_frame_sink" only means the FIRST frame entered
            # the decoder, not that media duration / position UI has settled.
            # Previous attempts pressed RIGHT ~0.2 s after first frame and
            # observed position domain corruption 17 -> 5421 and stream_seek
            # pos err!, then the player exited. This is an input-readiness
            # barrier, not a relaxed seek assertion; all EOS tests remain.
            time.sleep(2.0)
            ready=logs()
            if 'NOVA_PLAYBACK_COMPLETE' in ready or 'stream_seek pos err!' in ready:
                raise RuntimeError('Premature completion/seek error before first key')
            if 'PlayerActivity' not in resumed():
                raise RuntimeError('Player not foreground after seek-readiness barrier')
            # Ordinary MPEG-TS DPAD-right uses Nova's position domain
            # (0..1000). Drive the same non-ISO position-seek path repeatedly
            # until the log itself proves we reached the tail. No hidden test
            # API, no nova_iso metadata, and no download-state shortcut.
            seeks=[]
            final_marker=''
            current_target=-1
            for step in range(180):
                marker='NOVA_TS_POS_STEP_'+str(step)+'_'+str(time.monotonic_ns())
                adb('shell','log -p i -t NOVA_TS_EOF_TEST '+marker)
                adb('shell','input keyevent 22')

                # Synchronize one physical key event with one observed forward
                # position seek. Never send another key until this one is
                # either observed or times out.
                try:
                    # A physical RIGHT near the tail can legitimately emit a
                    # direction=0/no-op event while controls/focus settle. Treat
                    # that as an observed key result immediately instead of
                    # sleeping 3 seconds and letting a 42s fixture naturally
                    # run past the verified 930..975 window.
                    text=wait_for(lambda t:seek_after(t,marker) is not None,
                                  1.0,'ordinary TS seek event step '+str(step))
                except RuntimeError:
                    if 'NOVA_PLAYBACK_COMPLETE' in logs():
                        raise RuntimeError('Playback completed before verified near-tail seek')
                    time.sleep(.05)
                    continue

                before,current_target,direction,phase=seek_after(text,marker)
                if 'NOVA_ISO_TIME_SEEK' in phase:
                    raise RuntimeError('ISO seek appeared in ordinary TS position test')
                seeks.append([before,current_target,direction])
                if current_target < 0 or current_target > 1000 or 'stream_seek pos err!' in phase:
                    raise RuntimeError('Invalid position-domain Seek: '+repr(seeks[-1])+
                                       '; stream error='+str('stream_seek pos err!' in phase))

                if direction != 1:
                    # Do not count a RIGHT-key no-op/backward-classified event
                    # as progress; retry promptly so natural playback cannot
                    # carry the short fixture into EOF before verification.
                    time.sleep(.03)
                    continue

                # Run463 proved a batched driver could pass through 966 and
                # race into 990. Stop all input immediately at the first
                # verified safe tail position.
                if 930 <= current_target <= 975:
                    final_marker=marker
                    break

                if current_target > 975:
                    # Recover with single left events if scheduling skipped
                    # over the safe window.
                    for back_step in range(12):
                        back_marker='NOVA_TS_POS_BACK_'+str(back_step)+'_'+str(time.monotonic_ns())
                        adb('shell','log -p i -t NOVA_TS_EOF_TEST '+back_marker)
                        adb('shell','input keyevent 21')
                        try:
                            back_text=wait_for(
                                lambda t: re.search(
                                    r'avos_mp_video_seek current_pos=(\d+) to pos=(\d+) direction=0',
                                    t[t.rfind(back_marker):] if back_marker in t else '') is not None,
                                3,'ordinary TS backward recovery seek')
                        except RuntimeError:
                            continue
                        back_phase=back_text[back_text.rfind(back_marker):]
                        m=list(re.finditer(
                            r'avos_mp_video_seek current_pos=(\d+) to pos=(\d+) direction=0',
                            back_phase))[-1]
                        current_target=int(m[2])
                        seeks.append([int(m[1]),current_target,0])
                        if 930 <= current_target <= 975:
                            final_marker=back_marker
                            break
                    if final_marker:
                        break

            if not final_marker or not seeks or not (930<=seeks[-1][1]<=975):
                raise RuntimeError('Could not land in verified near-tail ordinary TS position: '+repr(seeks[-30:]))
            phase_start=time.monotonic()
            text=wait_for(lambda t:
                final_marker in t and
                'audio drain' in t[t.rfind(final_marker):] and
                'NOVA_PLAYBACK_COMPLETE' in t[t.rfind(final_marker):] and
                'com.archos.mediacenter.video.browser.MainActivity' in resumed(),
                30,'ordinary TS audio EOF drain and automatic browser return')
            phase=text[text.rfind(final_marker):]
            if 'NOVA_ISO_TIME_SEEK' in phase: raise RuntimeError('ISO seek appeared in ordinary TS regression')
            if 'NOVA_EOF_FORCE_COMPLETE' in phase: raise RuntimeError('Deprecated fake completion fallback fired')
            if 'Back navigation: OnBackPressedDispatcher callback' in phase: raise RuntimeError('BACK navigation observed after final seek')
            (a.reports/'ordinary-ts-seek-eof-logcat.txt').write_text(phase)
            report.update(status='PASS',seeks=seeks,final_position=seeks[-1][1],
                          elapsed_after_final_seek_s=time.monotonic()-phase_start,
                          audio_eof_drain_request=('NOVA_AUDIO_EOF_DRAIN_REQUEST' in phase),
                          native_completion=True,
                          returned_to_browser=True,no_iso_path=True,no_back_input=True)
            print('ORDINARY_TS_SEEK_EOF_SMOKE=PASS '+json.dumps(report))
    except Exception as e:
        report['error']=str(e);raise
    finally:
        try:(a.reports/'ordinary-ts-seek-eof-last-logcat.txt').write_text(logs())
        except Exception:pass
        try:adb('shell','am force-stop '+PACKAGE)
        except Exception:pass
        if port:
            try:adb('reverse','--remove',f'tcp:{port}')
            except Exception:pass
        if server:server.shutdown();server.server_close()
        (a.reports/'ordinary-ts-seek-eof.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
