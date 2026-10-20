#!/usr/bin/env python3
"""ISO-only real-time seeks plus controller-owned idle hide; fail-closed patches.

The current ISO bridge emits title bytes. Single-clip titles with validated
metadata and a known FFmpeg start timestamp use the existing FFmpeg timestamp
seek path. No average-byte-ratio is used. Multi-clip/unknown timelines retain
the prior relative fallback, rather than pretending their PTS are continuous.
Apply native AFTER all buffer patches: 2X/5X/10X arithmetic stays byte-identical.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

C_HELPERS = r'''
/* ISO timeline metadata is private to our localhost proxy. */
static int nova_iso_uint_arg(const char *query, const char *key, uint64_t *value) {
    int seen = 0;
    const char *p = query;
    if (!p) return 0;
    if (*p == '?') ++p;
    size_t k = strlen(key);
    while (*p) {
        const char *end = strchr(p, '&');
        if (!end) end = p + strlen(p);
        if ((size_t)(end - p) > k && !strncmp(p, key, k) && p[k] == '=') {
            if (++seen != 1) return 0;
            const char *q = p + k + 1;
            uint64_t n = 0;
            if (q == end) return 0;
            while (q != end) {
                unsigned d = (unsigned char)*q++ - '0';
                if (d > 9 || n > (UINT64_MAX - d) / 10) return 0;
                n = n * 10 + d;
            }
            *value = n;
        }
        p = *end ? end + 1 : end;
    }
    return seen == 1;
}
static int64_t nova_iso_timeline_us(const char *url, const char *query, uint64_t size) {
    const char *p = NULL;
    if (!url || !query || !size) return 0;
    if (!strncmp(url, "http://127.0.0.1:", 17)) p = url + 17;
    else if (!strncmp(url, "http://localhost:", 17)) p = url + 17;
    else return 0;
    unsigned port = 0;
    if (*p < '0' || *p > '9') return 0;
    while (*p >= '0' && *p <= '9') {
        port = port * 10 + (unsigned)(*p++ - '0');
        if (port > 65535) return 0;
    }
    if (!port || (strncmp(p, "/main.m2ts", 10) || (p[10] && p[10] != '?'))) return 0;
    uint64_t iso = 0, us = 0, clips = 0, title = 0, generation = 0;
    if (!nova_iso_uint_arg(query, "nova_iso", &iso) || iso != 1 ||
        !nova_iso_uint_arg(query, "nova_iso_duration_us", &us) ||
        !nova_iso_uint_arg(query, "nova_iso_clip_count", &clips) || clips != 1 ||
        !nova_iso_uint_arg(query, "nova_iso_title_size", &title) || title != size ||
        !nova_iso_uint_arg(query, "nova_iso_generation", &generation) || !generation ||
        us < 10000000ULL || us > 86400000000ULL) return 0;
    return (int64_t)us;
}
'''

C_ACTIVATE = r'''
    /* Publish presentation time AFTER the untouched 2X/5X/10X calculation.
     * Existing _get_*_time normalizes PTS against start_time, getduration uses
     * s->duration, and stream_seek_pos now routes milliseconds to _seek_time.
     * The existing timestamp/keyframe seek is used, not a bytes/size estimate.
     */
    if (s->etype == ETYPE_MPEG_TS && ff_p->size_known && ff_p->fmt->pb &&
        (ff_p->fmt->pb->seekable & AVIO_SEEKABLE_NORMAL)) {
        int64_t us = nova_iso_timeline_us(s->src.url, s->src_query, s->size);
        int64_t first = ff_p->fmt->start_time;
        if (us > 0 && first != AV_NOPTS_VALUE &&
            first >= 0 && first / 1000 <= INT_MAX) {
            ff_p->duration = (int)(us / 1000);
            ff_p->fmt->duration = us;
            s->duration = ff_p->duration;
            s->no_duration = 0;
            ff_p->nova_iso_time_mode = 1;
            serprintf("NOVA_ISO_TIMELINE_READY durationMs=%d startMs=%d seekUnit=ms mapping=timestamp\n",
                      s->duration, ff_p->start_time);
        } else if (strstr(s->src_query, "nova_iso=1")) {
            serprintf("NOVA_ISO_TIMELINE_FALLBACK reason=unverified_or_multiclip_timeline\n");
        }
    }
'''

PC = 'Lcom/archos/mediacenter/video/player/PlayerController;'
PLAYER = 'Lcom/archos/mediacenter/video/player/Player;'
POLICY = 'Lcom/archos/filecorelibrary/NovaControlbarAutoHide;'
HOST = 'Lcom/archos/filecorelibrary/NovaControlbarAutoHide$Host;'
METHODS = f'''
.method private novaArmHide(I)V
    .locals 1
    iget-object v0, p0, {PC}->mNovaAutoHide:{POLICY}
    if-nez v0, :nova_hide_exists
    new-instance v0, {POLICY}
    invoke-direct {{v0, p0}}, {POLICY}-><init>({HOST})V
    iput-object v0, p0, {PC}->mNovaAutoHide:{POLICY}
    :nova_hide_exists
    invoke-virtual {{v0, p1}}, {POLICY}->arm(I)V
    return-void
.end method

.method private novaCancelHide()V
    .locals 1
    iget-object v0, p0, {PC}->mNovaAutoHide:{POLICY}
    if-eqz v0, :nova_cancel_done
    invoke-virtual {{v0}}, {POLICY}->cancel()V
    :nova_cancel_done
    return-void
.end method

.method public novaSeekHideEvent()V
    .locals 1
    const/16 v0, 0xbb8
    invoke-direct {{p0, v0}}, {PC}->novaArmHide(I)V
    return-void
.end method

.method public novaBeginTrackingHide()V
    .locals 1
    const/4 v0, 0x1
    iput-boolean v0, p0, {PC}->mNovaTouchTracking:Z
    invoke-virtual {{p0}}, {PC}->novaSeekHideEvent()V
    return-void
.end method

.method public novaEndTrackingHide()V
    .locals 1
    const/4 v0, 0x0
    iput-boolean v0, p0, {PC}->mNovaTouchTracking:Z
    invoke-virtual {{p0}}, {PC}->novaSeekHideEvent()V
    return-void
.end method

.method private novaResetHide()V
    .locals 1
    invoke-direct {{p0}}, {PC}->novaCancelHide()V
    const/4 v0, 0x0
    iput-boolean v0, p0, {PC}->mNovaTouchTracking:Z
    return-void
.end method

.method public novaHideActive()Z
    .locals 1
    iget-boolean v0, p0, {PC}->mIsStopped:Z
    if-nez v0, :nova_inactive
    invoke-virtual {{p0}}, {PC}->isShowing()Z
    move-result v0
    return v0
    :nova_inactive
    const/4 v0, 0x0
    return v0
.end method

.method public novaHideReady(Z)Z
    .locals 2
    iget-boolean v0, p0, {PC}->mNovaTouchTracking:Z
    if-nez v0, :nova_not_ready
    invoke-virtual {{p0}}, {PC}->isSeekPressed()Z
    move-result v0
    if-nez v0, :nova_not_ready
    iget-boolean v0, p0, {PC}->isTVMenuDisplayed:Z
    if-nez v0, :nova_not_ready
    iget-object v0, p0, {PC}->tvCardDialog:Lcom/archos/mediacenter/video/player/TVCardDialog;
    if-eqz v0, :nova_dialog_hidden
    invoke-virtual {{v0}}, Landroid/view/View;->getVisibility()I
    move-result v0
    if-eqz v0, :nova_not_ready
    :nova_dialog_hidden
    sget-object v0, {PLAYER}->sPlayer:{PLAYER}
    if-eqz v0, :nova_not_ready
    invoke-virtual {{v0}}, {PLAYER}->isPlaying()Z
    move-result v0
    or-int/2addr v0, p1
    return v0
    :nova_not_ready
    const/4 v0, 0x0
    return v0
.end method

.method public novaHideControls()V
    .locals 0
    invoke-virtual {{p0}}, {PC}->hide()V
    return-void
.end method
'''

def once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f'{label}: expected one anchor, got {text.count(old)}')
    return text.replace(old, new, 1)

def edit_method(text: str, sig: str, fn) -> str:
    pat = re.compile(r'(?ms)^\.method [^\n]* '+re.escape(sig)+r'\n.*?^\.end method$')
    if len(pat.findall(text)) != 1: raise RuntimeError('Missing/duplicate method '+sig)
    return pat.sub(lambda m: fn(m.group(0)), text, count=1)

def entry(body: str, instructions: str) -> str:
    # Add only after register declaration; no new registers needed for entry hooks.
    return re.sub(r'(?m)^(    \.(?:locals|registers) \d+)\n', lambda m:m.group(0)+instructions+'\n',body,count=1)

def native_text(text: str) -> str:
    if 'nova_iso_time_mode' in text: raise RuntimeError('ISO timeline already installed')
    if 'NOVA_DYNAMIC_BUFFER:' not in text: raise RuntimeError('Expected main dynamic buffer base')
    text = once(text, '\tint\t\tstart_time;\n', '\tint\t\tstart_time;\n\tint nova_iso_time_mode;\n','private parser time mode')
    text = once(text, 'static int _open( STREAM *s, int buffer_size, int flags )', C_HELPERS+'\nstatic int _open( STREAM *s, int buffer_size, int flags )','ISO helpers')
    text = once(text, '\ts->parser_open = 1;', C_ACTIVATE+'\n\ts->parser_open = 1;','activate consistent timeline')
    anchor = '\t\tnew_pos = ((INT64)time + ff_p->start_time) * AV_TIME_BASE / 1000;'
    text = once(text, anchor, anchor+r'''
        if (ff_p->nova_iso_time_mode)
            serprintf("NOVA_ISO_TIME_SEEK targetMs=%d startMs=%d absoluteUs=%lld byteMode=0\n",
                      time, ff_p->start_time, (long long)new_pos);''','time seek diagnostic')
    return text

def iso_text(text: str) -> str:
    if 'nova_iso_clip_count' in text: raise RuntimeError('ISO timeline metadata already installed')
    if 'nativeCloseGeneration' not in text: raise RuntimeError('Expected verified ISO owner base')
    text = once(text, '    uint64_t title_size;\n', '    uint64_t title_size;\n    uint32_t timeline_clip_count;\n','clip metadata')
    text = once(text, '    if (ti) {\n        // Blu-ray title durations', '    if (ti) {\n        s->timeline_clip_count = ti->clip_count;\n        // Blu-ray title durations','record clip count')
    anchor = '        result = (*env)->NewStringUTF(env, out);'
    extra = r'''        {
            size_t used = strlen(out);
            int added = snprintf(out + used, sizeof(out) - used,
                "&nova_iso_clip_count=%u&nova_iso_title_size=%" PRIu64,
                g_session->timeline_clip_count, g_session->title_size);
            if (added < 0 || (size_t)added >= sizeof(out) - used) {
                session_destroy(g_session); g_session = NULL;
                pthread_mutex_unlock(&g_lock); return NULL;
            }
        }
'''
    text = once(text, '        char out[320];', '        char out[448];','URL bounds')
    return once(text, anchor, extra+anchor,'export timeline identity')

def controller_text(text: str) -> str:
    if 'mNovaAutoHide' in text: raise RuntimeError('Controller idle hide already installed')
    # Append to the existing interface block; preserve apktool canonical ordering.
    anchor = '.implements Landroid/view/GestureDetector$OnDoubleTapListener;'
    text = once(text, anchor, anchor+'\n.implements '+HOST,'controller Host interface')
    # Confirm actual obfuscated APK field descriptor, not a source-only guess.
    dialog = re.search(r'(?m)^\.field private tvCardDialog:(L[^;]+;)', text)
    if not dialog: raise RuntimeError('TV dialog field missing')
    methods = METHODS.replace('Lcom/archos/mediacenter/video/player/TVCardDialog;', dialog.group(1))
    text = once(text, '# instance fields', '# instance fields\n.field private mNovaAutoHide:'+POLICY+'\n.field private mNovaTouchTracking:Z\n','owned hide policy')
    def show(body):
        start=body.index('    const/16 p1, 0x1388')
        # Preserve the original stopped goto target while replacing the end only.
        return body[:start]+f'''    invoke-direct {{p0, p2}}, {PC}->novaArmHide(I)V
    :goto_0
    return-void
.end method'''
    text=edit_method(text,'show(II)V',show)
    text=edit_method(text,'sendFadeOut(I)V',lambda b:'.method private sendFadeOut(I)V\n    .locals 0\n'+f'    invoke-direct {{p0, p1}}, {PC}->novaArmHide(I)V\n    return-void\n.end method')
    text=edit_method(text,'cancelFadeOut()V',lambda b:entry(b,f'    invoke-direct {{p0}}, {PC}->novaCancelHide()V'))
    # Ordinary seek start and explicit key release both arm the independent UI
    # watcher. It waits for real readiness and never forces seek completion.
    text=edit_method(text,'onSeek(IZ)V',lambda b:once(b,'    return-void\n.end method',f'    invoke-virtual {{p0}}, {PC}->novaSeekHideEvent()V\n    return-void\n.end method','seek event'))
    def key(body):
        pattern=r'(    iput ([vp]\d+), p0, '+re.escape(PC)+r'->mSeekKeyDirection:I)'
        # Every direction transition (down and up) is actual interaction. onSeek
        # resets the first arm; repeat key events are handled by the existing code.
        return re.sub(pattern,lambda m:m.group(0)+'\n\n    invoke-virtual {p0}, '+PC+'->novaSeekHideEvent()V',body)
    text=edit_method(text,'onKey(ILandroid/view/KeyEvent;)Z',key)
    for sig in ['stop()V','reset()V']:
        text=edit_method(text,sig,lambda b:entry(b,f'    invoke-direct {{p0}}, {PC}->novaResetHide()V'))
    return text.rstrip()+'\n\n'+methods

def apply(root: Path, report: Path|None=None) -> dict:
    paths=list(root.glob('smali*/com/archos/mediacenter/video/player/PlayerController.smali'))
    if len(paths)!=1: raise RuntimeError('Expected one PlayerController')
    p=paths[0]; updates=[(p, controller_text(p.read_text()))]
    # Touch release calls onSeekAndDraggingComplete normally. Also arm directly
    # on tracking end, so a delayed all-seek-complete does not lose UI cleanup.
    count=0
    for p in root.glob('smali*/com/archos/mediacenter/video/player/PlayerController$*.smali'):
        t=p.read_text()
        if '.method public onStopTrackingTouch(Landroid/widget/SeekBar;)V' not in t: continue
        field=re.search(r'(?m)^\.field final synthetic ([A-Za-z0-9_$]+):'+re.escape(PC),t)
        cls=re.search(r'(?m)^\.class (?:[^\n]* )?(L[^;]+;)',t)
        if not field or not cls: raise RuntimeError('Tracking listener owner missing')
        # Entry hook uses the listener receiver before the original method may
        # reuse p0. The queued callback runs after the existing release updates.
        def hook(b, method):
            registers=re.search(r'\.locals (\d+)',b)
            if not registers or int(registers.group(1))<1: raise RuntimeError('Tracking scratch register missing')
            return entry(b,f'    iget-object v0, p0, {cls.group(1)}->{field.group(1)}:{PC}\n    invoke-virtual {{v0}}, {PC}->{method}()V')
        changed=edit_method(t,'onStartTrackingTouch(Landroid/widget/SeekBar;)V',lambda b:hook(b,'novaBeginTrackingHide'))
        changed=edit_method(changed,'onStopTrackingTouch(Landroid/widget/SeekBar;)V',lambda b:hook(b,'novaEndTrackingHide'))
        updates.append((p,changed)); count+=1
    if count != 2: raise RuntimeError('Expected two tracking listeners, got '+str(count))
    for path, content in updates: path.write_text(content)
    result={'status':'PASS','scope':'controller idle timer only','touch_listeners':count,
            'default_idle_ms':3000,'poll_ms':250,'playback_mutations':0,
            'timer_independent_of_seek_callback':True}
    if report:report.write_text(json.dumps(result,indent=2)+'\n')
    return result

def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--native',type=Path);g.add_argument('--iso',type=Path);g.add_argument('--decoded',type=Path)
    p.add_argument('--report',type=Path);a=p.parse_args()
    if a.decoded: result=apply(a.decoded,a.report)
    else:
        path=a.native/'Source/stream_parser_ffmpeg.c' if a.native else a.iso
        fn=native_text if a.native else iso_text
        path.write_text(fn(path.read_text()));result={'status':'PASS','scope':'ISO single-clip verified timeline','other_formats':'unchanged'}
        if a.report:a.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
if __name__=='__main__':main()
