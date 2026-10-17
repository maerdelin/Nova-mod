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
