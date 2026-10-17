#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import json
import re
import base64
import zlib

METHOD_RE = re.compile(r'^\.method [^\n]+\n.*?^\.end method', re.M | re.S)

ROOT = Path(__file__).resolve().parents[1]
REBUFFER_SMALI = zlib.decompress(base64.b64decode((ROOT / 'patches' / 'MainRebufferInputStream.smali.zlib.b64').read_text().strip())).decode('utf-8')
PLAYER_HELPERS = r'''
.method public static bufferPauseCurrent()Z
    .locals 4

    sget-boolean v0, Lcom/archos/mediacenter/video/player/Player;->sNovaBufferPaused:Z
    if-eqz v0, :check
    const/4 v0, 0x1
    return v0

    :check
    sget-object v0, Lcom/archos/mediacenter/video/player/Player;->sPlayer:Lcom/archos/mediacenter/video/player/Player;
    if-eqz v0, :no

    iget v1, v0, Lcom/archos/mediacenter/video/player/Player;->mTargetState:I
    const/4 v2, 0x5
    if-ne v1, v2, :no

    iget v1, v0, Lcom/archos/mediacenter/video/player/Player;->mCurrentState:I
    if-ne v1, v2, :no

    iget-object v1, v0, Lcom/archos/mediacenter/video/player/Player;->mMediaPlayer:Lcom/archos/medialib/IMediaPlayer;
    if-eqz v1, :no

    invoke-interface {v1}, Lcom/archos/medialib/IMediaPlayer;->pause()V
    const/4 v3, 0x1
    sput-boolean v3, Lcom/archos/mediacenter/video/player/Player;->sNovaBufferPaused:Z

    const-string v0, "NovaNetBuf"
    const-string v1, "PLAYER_REBUFFER_PAUSE"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return v3

    :no
    const/4 v0, 0x0
    return v0
.end method

.method public static bufferResumeCurrent()V
    .locals 4

    sget-boolean v0, Lcom/archos/mediacenter/video/player/Player;->sNovaBufferPaused:Z
    if-eqz v0, :done

    sget-object v0, Lcom/archos/mediacenter/video/player/Player;->sPlayer:Lcom/archos/mediacenter/video/player/Player;
    if-eqz v0, :clear

    iget v1, v0, Lcom/archos/mediacenter/video/player/Player;->mTargetState:I
    const/4 v2, 0x5
    if-ne v1, v2, :clear

    iget v1, v0, Lcom/archos/mediacenter/video/player/Player;->mCurrentState:I
    if-ne v1, v2, :clear

    iget-object v1, v0, Lcom/archos/mediacenter/video/player/Player;->mMediaPlayer:Lcom/archos/medialib/IMediaPlayer;
    if-eqz v1, :clear

    invoke-interface {v1}, Lcom/archos/medialib/IMediaPlayer;->start()V
    const/4 v3, 0x0
    sput-boolean v3, Lcom/archos/mediacenter/video/player/Player;->sNovaBufferPaused:Z

    const-string v0, "NovaNetBuf"
    const-string v1, "PLAYER_REBUFFER_RESUME"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void

    :clear
    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/mediacenter/video/player/Player;->sNovaBufferPaused:Z

    :done
    return-void
.end method

.method public static cancelBufferPause()V
    .locals 1
    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/mediacenter/video/player/Player;->sNovaBufferPaused:Z
    return-void
.end method

.method public static isBufferPaused()Z
    .locals 1
    sget-boolean v0, Lcom/archos/mediacenter/video/player/Player;->sNovaBufferPaused:Z
    return v0
.end method
'''

def _method(text: str, signature: str):
    hits=[m for m in METHOD_RE.finditer(text) if signature in m.group(0).splitlines()[0]]
    if len(hits)!=1:
        raise RuntimeError(f'{signature}: expected 1 method, got {len(hits)}')
    return hits[0]

def patch_player_text(text: str) -> str:
    forbidden=('sNovaBufferPaused','MainRebufferInputStream;->activateCurrent')
    if any(x in text for x in forbidden):
        raise RuntimeError('player already contains new rebuffer patch')
    field='.field public static sPlayer:Lcom/archos/mediacenter/video/player/Player;\n'
    if text.count(field)!=1:
        raise RuntimeError('sPlayer field anchor not unique')
    text=text.replace(field,field+'\n.field private static volatile sNovaBufferPaused:Z\n',1)

    m=_method(text,' pausePlayback(I)V')
    body=m.group(0)
    loc=body.find('\n',body.find('.locals '))
    inject='\n\n    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->cancelBufferPause()V\n    invoke-static {}, Lcom/archos/filecorelibrary/MainRebufferInputStream;->deactivateCurrent()V'
    body=body[:loc]+inject+body[loc:]
    text=text[:m.start()]+body+text[m.end():]

    m=_method(text,' stopPlayback()V')
    body=m.group(0)
    loc=body.find('\n',body.find('.locals '))
    body=body[:loc]+inject+body[loc:]
    text=text[:m.start()]+body+text[m.end():]

    m=_method(text,' onCompletion(Lcom/archos/medialib/IMediaPlayer;)V')
    body=m.group(0)
    loc=body.find('\n',body.find('.locals '))
    body=body[:loc]+inject+body[loc:]
    text=text[:m.start()]+body+text[m.end():]

    m=_method(text,' start(I)V')
    body=m.group(0)
    cond='    :cond_0\n    const/4 v0, 0x5\n'
    if body.count(cond)!=1:
        raise RuntimeError('Player.start cond0 anchor not unique')
    body=body.replace(cond,
        '    :cond_0\n'
        '    sget-boolean v2, Lcom/archos/mediacenter/video/player/Player;->sNovaBufferPaused:Z\n'
        '    if-eqz v2, :nova_start_not_buffer_paused\n'
        '    return-void\n\n'
        '    :nova_start_not_buffer_paused\n'
        '    const/4 v0, 0x5\n',1)
    anchor=('    invoke-interface {v3}, Lcom/archos/medialib/IMediaPlayer;->start()V\n\n'
            '    iput v0, p0, Lcom/archos/mediacenter/video/player/Player;->mCurrentState:I')
    if body.count(anchor)!=1:
        raise RuntimeError('native start anchor not unique')
    body=body.replace(anchor,anchor+'\n\n    invoke-static {}, Lcom/archos/filecorelibrary/MainRebufferInputStream;->activateCurrent()V',1)
    text=text[:m.start()]+body+text[m.end():]

    return text.rstrip()+'\n\n'+PLAYER_HELPERS+'\n'

def patch_session_text(text: str) -> str:
    if 'MainRebufferInputStream;->wrap' in text:
        raise RuntimeError('session already patched')
    m=_method(text,' publishInput(Ljava/io/InputStream;)V')
    body=m.group(0)
    anchor='    :cond_0\n    monitor-enter p0\n'
    if body.count(anchor)!=1:
        raise RuntimeError('publishInput cond0 anchor not unique')
    inject=(
        '    :cond_0\n'
        '    iget-boolean v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->supersedableMediaRequest:Z\n'
        '    if-eqz v0, :nova_no_rebuffer\n\n'
        '    iget-object v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->this$0:Lcom/archos/filecorelibrary/StreamOverHttp;\n'
        '    invoke-static {v0}, Lcom/archos/filecorelibrary/StreamOverHttp;->m(Lcom/archos/filecorelibrary/StreamOverHttp;)Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;\n'
        '    move-result-object v1\n'
        '    sget-object v0, Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;->PLAYBACK:Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;\n'
        '    if-ne v1, v0, :nova_no_rebuffer\n\n'
        '    iget-object v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->this$0:Lcom/archos/filecorelibrary/StreamOverHttp;\n'
        '    invoke-static {v0}, Lcom/archos/filecorelibrary/StreamOverHttp;->p(Lcom/archos/filecorelibrary/StreamOverHttp;)Landroid/net/Uri;\n'
        '    move-result-object v0\n'
        '    invoke-static {v0, p1}, Lcom/archos/filecorelibrary/MainRebufferInputStream;->wrap(Landroid/net/Uri;Ljava/io/InputStream;)Ljava/io/InputStream;\n'
        '    move-result-object p1\n\n'
        '    :nova_no_rebuffer\n'
        '    monitor-enter p0\n'
    )
    body=body.replace(anchor,inject,1)
    return text[:m.start()]+body+text[m.end():]

def apply(root: Path, report: Path|None=None):
    player=next(iter(root.glob('smali*/com/archos/mediacenter/video/player/Player.smali')),None)
    session=next(iter(root.glob('smali*/com/archos/filecorelibrary/StreamOverHttp$HttpSession.smali')),None)
    if player is None or session is None:
        raise RuntimeError('required clean-main smali targets not found')
    player.write_text(patch_player_text(player.read_text()))
    session.write_text(patch_session_text(session.read_text()))
    out=session.parent/'MainRebufferInputStream.smali'
    if out.exists():
        raise RuntimeError('MainRebufferInputStream already exists on clean main')
    out.write_text(REBUFFER_SMALI)
    result={
        'status':'PASS',
        'base_policy':'Player.start remains original until after IMediaPlayer.start and mCurrentState=PLAYING',
        'prestart_watermark_gate':False,
        'capacity_mib':64,
        'low_mib':24,
        'resume_strictly_above_mib':45,
        'activation':'after original native/player start only',
        'unarmed_policy':'first protected read is grace; no 24 MiB gate until buffer naturally reaches 24 MiB; later empty read hard-pauses',
        'armed_policy':'pause before a read can cross below 24 MiB; resume only above 45 MiB or clean EOF',
    }
    if report:
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps(result,indent=2)+'\n')
    return result


def verify_roundtrip(expected: Path, actual: Path, report: Path, g):
    sa=g.resource_map(expected); sb=g.resource_map(actual)
    ia=g.class_index(expected); ib=g.class_index(actual); bad=[]
    if ia.keys()!=ib.keys():
        bad.append('class set differs')
    intentional={
        'Lcom/archos/mediacenter/video/player/Player;',
        'Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;',
        'Lcom/archos/filecorelibrary/MainRebufferInputStream;',
    }
    for name in ia.keys() & ib.keys():
        if name in intentional:
            continue
        a=ia[name].read_text(); b=ib[name].read_text()
        if a!=b:
            an=a.replace('const-string/jumbo','const-string')
            bn=b.replace('const-string/jumbo','const-string')
            if g.logical_class(an,sa)!=g.logical_class(bn,sb):
                bad.append(name)

    aa={p.relative_to(expected).as_posix() for p in expected.rglob('*.xml')
        if p.relative_to(expected).as_posix().startswith(('res/','AndroidManifest.xml'))}
    bb={p.relative_to(actual).as_posix() for p in actual.rglob('*.xml')
        if p.relative_to(actual).as_posix().startswith(('res/','AndroidManifest.xml'))}
    if aa!=bb:
        bad.append('XML resource set differs')
    for path in aa & bb:
        if (expected/path).read_bytes()!=(actual/path).read_bytes():
            if g.logical_xml(g.ET.parse(expected/path).getroot())!=g.logical_xml(g.ET.parse(actual/path).getroot()):
                bad.append(path)

    forbidden=('initialHold','beforeNativeStart','awaitBudget','bufferStartHeldCurrent','HARD_GATE')
    for root,label in ((expected,'expected'),(actual,'roundtrip')):
        player=list(root.glob('smali*/com/archos/mediacenter/video/player/Player.smali'))
        session=list(root.glob('smali*/com/archos/filecorelibrary/StreamOverHttp$HttpSession.smali'))
        rb=list(root.glob('smali*/com/archos/filecorelibrary/MainRebufferInputStream.smali'))
        if len(player)!=1: bad.append(label+': Player missing/duplicate')
        if len(session)!=1: bad.append(label+': HttpSession missing/duplicate')
        if len(rb)!=1: bad.append(label+': MainRebufferInputStream missing/duplicate')
        if len(player)==1:
            pt=player[0].read_text()
            if any(x in pt for x in forbidden): bad.append(label+': old gate code remains in Player')
            for token in ('.field private static volatile sNovaBufferPaused:Z',
                          ' bufferPauseCurrent()Z',' bufferResumeCurrent()V',
                          ' cancelBufferPause()V',' isBufferPaused()Z',
                          'MainRebufferInputStream;->activateCurrent()V',
                          'MainRebufferInputStream;->deactivateCurrent()V'):
                if token not in pt: bad.append(label+': Player missing '+token)
            sm=_method(pt,' start(I)V').group(0)
            ns=sm.find('IMediaPlayer;->start()V')
            state=sm.find('->mCurrentState:I',ns)
            activate=sm.find('MainRebufferInputStream;->activateCurrent()V',state)
            if not (0<=ns<state<activate):
                bad.append(label+': activation is not strictly after native start and PLAYING state')
        if len(session)==1:
            st=session[0].read_text()
            if st.count('MainRebufferInputStream;->wrap')!=1:
                bad.append(label+': playback wrapper count is not exactly one')
            pm=_method(st,' publishInput(Ljava/io/InputStream;)V').group(0)
            for token in ('supersedableMediaRequest:Z',
                          'StreamOverHttp$ReadMode;->PLAYBACK',
                          'MainRebufferInputStream;->wrap'):
                if token not in pm: bad.append(label+': publishInput missing '+token)
        if len(rb)==1:
            rt=rb[0].read_text()
            if any(x in rt for x in forbidden): bad.append(label+': old gate code remains in rebuffer class')
            for token in ('.field private static final CAPACITY:I = 0x4000000',
                          '.field private static final LOW:I = 0x1800000',
                          '.field private static final RESUME:I = 0x2d00000',
                          'REBUFFER_WRAP prestart=main-direct',
                          'REBUFFER_ACTIVE after-native-start cap=64MiB',
                          'REBUFFER_ARMED buffer>=24MiB',
                          'REBUFFER_RESUME buffer>45MiB',
                          'REBUFFER_PAUSE low-or-empty',
                          'Ljava/io/InputStream;->read()I',
                          'Ljava/io/InputStream;->read([BII)I',
                          'Ljava/io/InputStream;->skip(J)J',
                          'Ljava/io/InputStream;->available()I'):
                if token not in rt: bad.append(label+': rebuffer invariant missing '+token)
            ctor=_method(rt,' constructor <init>(Ljava/io/InputStream;)V').group(0)
            if 'PipedInputStream' in ctor or 'Thread;->start()V' in ctor:
                bad.append(label+': pre-start constructor starts buffering')
            act=_method(rt,' activateInstance()V').group(0)
            cap_ok=('const v1, 0x4000000' in act or 'const/high16 v1, 0x400' in act)
            if 'PipedInputStream' not in act or not cap_ok or 'Thread;->start()V' not in act:
                bad.append(label+': activation does not create/start 64 MiB producer')
            for sig in (' read()I',' read([BII)I',' skip(J)J',' available()I'):
                m=_method(rt,sig).group(0)
                if 'started:Z' not in m or 'Ljava/io/InputStream;' not in m:
                    bad.append(label+': '+sig+' lacks direct-main pre-start path')
            br=_method(rt,' beforeRead(I)V').group(0)
            low_ok=(('const v1, 0x1800000\n    add-int v2, v1, p1' in br) or ('const/high16 v1, 0x180\n    add-int v2, v1, p1' in br))
            resume_ok=(('const v1, 0x2d00000\n    if-le v0, v1, :' in br) or ('const/high16 v1, 0x2d0\n    if-le v0, v1, :' in br))
            if not low_ok:
                bad.append(label+': 24 MiB floor/budget check missing')
            if not resume_ok:
                bad.append(label+': strict >45 MiB resume check missing')
            throws=[x.strip() for x in rt.splitlines() if x.strip().startswith('throw ')]
            if throws not in (['throw v1','throw v1'],):
                bad.append(label+': unexpected throw-register pattern '+repr(throws))

    result={'status':'FAIL' if bad else 'PASS',
            'classes_compared':len(ia),'xml_files_compared':len(aa),
            'differences':sorted(bad),
            'comparison':'strict all non-intentional classes/XML; explicit post-start rebuffer invariants for Player/HttpSession/MainRebufferInputStream',
            'runtime_tested':False}
    g.write_json(report,result)
    if bad:
        raise g.Conflict('Main rebuffer roundtrip verification failed: '+str(bad[:30]))
    print(json.dumps(result,indent=2))
    return result
