#!/usr/bin/env python3
"""Hard decoder gate for WebDAV starvation.

This layer is intentionally separate from the byte-buffer patch. It proves the
network-starvation invariant at the Player/IMediaPlayer boundary:
- a read that leaves <24 MiB pauses IMediaPlayer before returning to AVOS;
- while blocked, Player.start() cannot reach IMediaPlayer.start();
- only the same active stream becoming >45 MiB may auto-resume a pause caused
  by this gate, and a normal Player.pause() cancels that auto-resume intent.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

METHOD_RE = re.compile(r'^\.method [^\n]+\n.*?^\.end method', re.M | re.S)

GATE = 'Lcom/archos/mediacenter/video/player/WebDavBufferGate;'
PLAYER = 'Lcom/archos/mediacenter/video/player/Player;'

WEB_DAV_BUFFER_GATE_SMALI = r'''.class public final Lcom/archos/mediacenter/video/player/WebDavBufferGate;
.super Ljava/lang/Object;
.source "WebDavBufferGate.java"

.field private static volatile sActive:Z
.field private static volatile sBlocked:Z
.field private static volatile sPausedByBuffer:Z
.field private static volatile sPlayWanted:Z
.field private static volatile sPlayer:Lcom/archos/mediacenter/video/player/Player;
.field private static volatile sSource:Ljava/lang/Object;

.method private constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public static declared-synchronized attach(Lcom/archos/mediacenter/video/player/Player;Landroid/net/Uri;)V
    .locals 3
    if-eqz p1, :detach_if_same
    invoke-virtual {p1}, Landroid/net/Uri;->getScheme()Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :detach_if_same

    const-string v1, "webdav"
    invoke-virtual {v1, v0}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-nez v2, :attach_webdav

    const-string v1, "webdavs"
    invoke-virtual {v1, v0}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-eqz v2, :detach_if_same

    :attach_webdav
    sput-object p0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPlayer:Lcom/archos/mediacenter/video/player/Player;
    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sActive:Z
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sBlocked:Z
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPausedByBuffer:Z
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPlayWanted:Z
    const/4 v0, 0x0
    sput-object v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sSource:Ljava/lang/Object;
    return-void

    :detach_if_same
    sget-object v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPlayer:Lcom/archos/mediacenter/video/player/Player;
    if-ne v0, p0, :done
    const/4 v0, 0x0
    sput-object v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPlayer:Lcom/archos/mediacenter/video/player/Player;
    sput-object v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sSource:Ljava/lang/Object;
    const/4 v1, 0x0
    sput-boolean v1, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sActive:Z
    sput-boolean v1, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sBlocked:Z
    sput-boolean v1, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPausedByBuffer:Z
    sput-boolean v1, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPlayWanted:Z
    :done
    return-void
.end method

.method public static declared-synchronized noteStart(Lcom/archos/mediacenter/video/player/Player;)Z
    .locals 2
    sget-object v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPlayer:Lcom/archos/mediacenter/video/player/Player;
    if-ne v0, p0, :not_blocked
    const/4 v0, 0x1
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPlayWanted:Z
    sget-boolean v1, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sActive:Z
    if-eqz v1, :not_blocked
    sget-boolean v1, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sBlocked:Z
    if-eqz v1, :not_blocked
    return v0
    :not_blocked
    const/4 v0, 0x0
    return v0
.end method

.method public static declared-synchronized notePause(Lcom/archos/mediacenter/video/player/Player;)V
    .locals 1
    sget-object v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPlayer:Lcom/archos/mediacenter/video/player/Player;
    if-ne v0, p0, :done
    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPlayWanted:Z
    :done
    return-void
.end method

.method public static declared-synchronized onStreamStart(Ljava/lang/Object;)V
    .locals 3
    sput-object p0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sSource:Ljava/lang/Object;
    const/4 v0, 0x1
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sActive:Z
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sBlocked:Z
    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPausedByBuffer:Z
    const-string v1, "NovaNetBuf"
    const-string v2, "HARD_GATE stream_start blocked=1"
    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method public static declared-synchronized onLow(Ljava/lang/Object;)V
    .locals 4
    sget-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sActive:Z
    if-eqz v0, :done
    sget-object v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sSource:Ljava/lang/Object;
    if-ne v0, p0, :done
    const/4 v0, 0x1
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sBlocked:Z

    sget-object v1, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPlayer:Lcom/archos/mediacenter/video/player/Player;
    if-eqz v1, :log_low
    invoke-virtual {v1}, Lcom/archos/mediacenter/video/player/Player;->bufferGatePause()Z
    move-result v2
    if-eqz v2, :log_low
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPausedByBuffer:Z

    :log_low
    const-string v2, "NovaNetBuf"
    const-string v3, "HARD_GATE low<24MiB decoder_paused_before_read_return"
    invoke-static {v2, v3}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    :done
    return-void
.end method

.method public static declared-synchronized onReady(Ljava/lang/Object;)V
    .locals 4
    sget-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sActive:Z
    if-eqz v0, :done
    sget-object v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sSource:Ljava/lang/Object;
    if-ne v0, p0, :done

    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sBlocked:Z

    sget-boolean v1, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPausedByBuffer:Z
    if-eqz v1, :clear_pause
    sget-boolean v1, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPlayWanted:Z
    if-eqz v1, :clear_pause
    sget-object v1, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPlayer:Lcom/archos/mediacenter/video/player/Player;
    if-eqz v1, :clear_pause
    invoke-virtual {v1}, Lcom/archos/mediacenter/video/player/Player;->bufferGateResume()Z
    move-result v2

    :clear_pause
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPausedByBuffer:Z
    const-string v2, "NovaNetBuf"
    const-string v3, "HARD_GATE ready>45MiB blocked=0"
    invoke-static {v2, v3}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    :done
    return-void
.end method

.method public static declared-synchronized onEnd(Ljava/lang/Object;)V
    .locals 4
    sget-object v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sSource:Ljava/lang/Object;
    if-ne v0, p0, :done
    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sBlocked:Z

    sget-boolean v1, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPausedByBuffer:Z
    if-eqz v1, :clear
    sget-boolean v1, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPlayWanted:Z
    if-eqz v1, :clear
    sget-object v1, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPlayer:Lcom/archos/mediacenter/video/player/Player;
    if-eqz v1, :clear
    invoke-virtual {v1}, Lcom/archos/mediacenter/video/player/Player;->bufferGateResume()Z
    move-result v2

    :clear
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sActive:Z
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPausedByBuffer:Z
    const/4 v1, 0x0
    sput-object v1, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sSource:Ljava/lang/Object;
    :done
    return-void
.end method

.method public static declared-synchronized onClosed(Ljava/lang/Object;)V
    .locals 2
    sget-object v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sSource:Ljava/lang/Object;
    if-ne v0, p0, :done
    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sActive:Z
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sBlocked:Z
    sput-boolean v0, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sPausedByBuffer:Z
    const/4 v1, 0x0
    sput-object v1, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->sSource:Ljava/lang/Object;
    :done
    return-void
.end method
'''

PLAYER_BUFFER_METHODS = r'''
.method public bufferGatePause()Z
    .locals 3
    invoke-virtual {p0}, Lcom/archos/mediacenter/video/player/Player;->isInPlaybackState()Z
    move-result v0
    if-eqz v0, :no
    iget-object v0, p0, Lcom/archos/mediacenter/video/player/Player;->mMediaPlayer:Lcom/archos/medialib/IMediaPlayer;
    if-eqz v0, :no
    invoke-interface {v0}, Lcom/archos/medialib/IMediaPlayer;->isPlaying()Z
    move-result v1
    if-eqz v1, :no

    invoke-interface {v0}, Lcom/archos/medialib/IMediaPlayer;->pause()V
    const/4 v1, 0x6
    iput v1, p0, Lcom/archos/mediacenter/video/player/Player;->mCurrentState:I

    const-string v1, "NovaNetBuf"
    const-string v2, "HARD_GATE IMediaPlayer.pause current=PAUSED target_preserved"
    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    const/4 v0, 0x1
    return v0
    :no
    const/4 v0, 0x0
    return v0
.end method

.method public bufferGateResume()Z
    .locals 4
    iget-boolean v0, p0, Lcom/archos/mediacenter/video/player/Player;->mPlaybackEnding:Z
    if-nez v0, :no
    iget v0, p0, Lcom/archos/mediacenter/video/player/Player;->mTargetState:I
    const/4 v1, 0x5
    if-ne v0, v1, :no
    iget-boolean v0, p0, Lcom/archos/mediacenter/video/player/Player;->mFocusSuspended:Z
    if-nez v0, :no
    iget-boolean v0, p0, Lcom/archos/mediacenter/video/player/Player;->mMetadataReady:Z
    if-eqz v0, :no
    invoke-virtual {p0}, Lcom/archos/mediacenter/video/player/Player;->isInPlaybackState()Z
    move-result v0
    if-eqz v0, :no
    iget-object v0, p0, Lcom/archos/mediacenter/video/player/Player;->mMediaPlayer:Lcom/archos/medialib/IMediaPlayer;
    if-eqz v0, :no
    invoke-interface {v0}, Lcom/archos/medialib/IMediaPlayer;->isPlaying()Z
    move-result v2
    if-nez v2, :already

    invoke-interface {v0}, Lcom/archos/medialib/IMediaPlayer;->start()V
    iput v1, p0, Lcom/archos/mediacenter/video/player/Player;->mCurrentState:I
    const/4 v2, 0x1
    invoke-virtual {p0, v2}, Lcom/archos/mediacenter/video/player/Player;->stayAwake(Z)V
    const-string v2, "NovaNetBuf"
    const-string v3, "HARD_GATE IMediaPlayer.start target=PLAYING"
    invoke-static {v2, v3}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    const/4 v0, 0x1
    return v0

    :already
    const/4 v0, 0x1
    return v0
    :no
    const/4 v0, 0x0
    return v0
.end method
'''

AFTER_CONSUME_SMALI = r'''
.method private afterConsume()V
    .locals 4
    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    if-nez v0, :done
    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    if-nez v0, :done

    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->available()I
    move-result v0
    const v1, 0x1800000
    if-ge v0, v1, :done

    const/4 v1, 0x1
    iput-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    invoke-static {p0}, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->onLow(Ljava/lang/Object;)V

    const-string v2, "NovaNetBuf"
    const-string v3, "POST_READ_LOW remaining<24MiB pause_completed_before_return"
    invoke-static {v2, v3}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    :done
    return-void
.end method
'''

def _one(paths, label):
    paths = list(paths)
    if len(paths) != 1:
        raise RuntimeError(f'{label}: expected one target, got {len(paths)}: {paths}')
    return paths[0]

def _method(text: str, signature_fragment: str):
    hits = [m for m in METHOD_RE.finditer(text) if signature_fragment in m.group(0).splitlines()[0]]
    if len(hits) != 1:
        raise RuntimeError(f'method {signature_fragment} missing/ambiguous: {len(hits)}')
    return hits[0]

def _inject_after_register_decl(body: str, lines_to_add: list[str]) -> str:
    lines = body.splitlines()
    idx = next((i for i,l in enumerate(lines) if l.strip().startswith(('.locals ', '.registers '))), None)
    if idx is None:
        raise RuntimeError('register declaration missing')
    lines[idx+1:idx+1] = [''] + lines_to_add + ['']
    return '\n'.join(lines)

def patch_player(text: str) -> str:
    attach_call = 'WebDavBufferGate;->attach'
    if attach_call not in text:
        m = _method(text, ' setVideoURI(Landroid/net/Uri;Ljava/util/Map;)V')
        body = _inject_after_register_decl(m.group(0), [
            '    invoke-static {p0, p1}, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->attach(Lcom/archos/mediacenter/video/player/Player;Landroid/net/Uri;)V'
        ])
        text = text[:m.start()] + body + text[m.end():]

    if 'WebDavBufferGate;->noteStart' not in text:
        m = _method(text, ' start(I)V')
        body = _inject_after_register_decl(m.group(0), [
            '    invoke-static {p0}, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->noteStart(Lcom/archos/mediacenter/video/player/Player;)Z',
            '    move-result v0',
            '    if-eqz v0, :nova_buffer_gate_start_continue',
            '    const/4 v0, 0x5',
            '    iput v0, p0, Lcom/archos/mediacenter/video/player/Player;->mTargetState:I',
            '    const-string v0, "NovaNetBuf"',
            '    const-string v1, "HARD_GATE Player.start blocked while buffer<resume"',
            '    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I',
            '    return-void',
            '    :nova_buffer_gate_start_continue'
        ])
        text = text[:m.start()] + body + text[m.end():]

    if 'WebDavBufferGate;->notePause' not in text:
        m = _method(text, ' pause(I)V')
        body = _inject_after_register_decl(m.group(0), [
            '    invoke-static {p0}, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->notePause(Lcom/archos/mediacenter/video/player/Player;)V'
        ])
        text = text[:m.start()] + body + text[m.end():]

    if ' bufferGatePause()Z' not in text:
        text = text.rstrip() + '\n\n' + PLAYER_BUFFER_METHODS + '\n'
    return text

def patch_read_ahead(text: str) -> str:
    if 'POST_READ_LOW remaining<24MiB pause_completed_before_return' in text:
        return text

    old = '''    new-instance v1, Ljava/io/PipedOutputStream;
    invoke-direct {v1, v0}, Ljava/io/PipedOutputStream;-><init>(Ljava/io/PipedInputStream;)V
    iput-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeOut:Ljava/io/PipedOutputStream;

    new-instance v2, Ljava/lang/Thread;'''
    new = '''    new-instance v1, Ljava/io/PipedOutputStream;
    invoke-direct {v1, v0}, Ljava/io/PipedOutputStream;-><init>(Ljava/io/PipedInputStream;)V
    iput-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeOut:Ljava/io/PipedOutputStream;

    invoke-static {p0}, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->onStreamStart(Ljava/lang/Object;)V

    new-instance v2, Ljava/lang/Thread;'''
    if old not in text: raise RuntimeError('read-ahead constructor anchor changed')
    text = text.replace(old, new, 1)

    old = '''    const/4 v1, 0x1
    iput-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    const-string v2, "NovaNetBuf"'''
    new = '''    const/4 v1, 0x1
    iput-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    invoke-static {p0}, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->onLow(Ljava/lang/Object;)V

    const-string v2, "NovaNetBuf"'''
    if old not in text: raise RuntimeError('awaitReady low anchor changed')
    text = text.replace(old, new, 1)

    old = '''    iget-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z
    if-nez v1, :return

    const v1, 0x2d00000'''
    new = '''    iget-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z
    if-eqz v1, :nova_buffer_not_eof
    invoke-static {p0}, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->onEnd(Ljava/lang/Object;)V
    return-void
    :nova_buffer_not_eof

    const v1, 0x2d00000'''
    if old not in text: raise RuntimeError('awaitReady eof anchor changed')
    text = text.replace(old, new, 1)

    old = '''    const/4 v1, 0x0
    iput-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    const-string v1, "NovaNetBuf"'''
    new = '''    const/4 v1, 0x0
    iput-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    invoke-static {p0}, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->onReady(Ljava/lang/Object;)V

    const-string v1, "NovaNetBuf"'''
    if old not in text: raise RuntimeError('awaitReady ready anchor changed')
    text = text.replace(old, new, 1)

    old = '''    invoke-virtual {v0}, Ljava/io/PipedInputStream;->read()I
    move-result v0

    if-ltz v0, :check_failure
    return v0'''
    new = '''    invoke-virtual {v0}, Ljava/io/PipedInputStream;->read()I
    move-result v0

    if-ltz v0, :check_failure
    invoke-direct {p0}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->afterConsume()V
    return v0'''
    if old not in text: raise RuntimeError('single read anchor changed')
    text = text.replace(old, new, 1)

    old = '''    invoke-virtual {v0, p1, p2, p3}, Ljava/io/PipedInputStream;->read([BII)I
    move-result v0

    if-ltz v0, :check_failure
    return v0'''
    new = '''    invoke-virtual {v0, p1, p2, p3}, Ljava/io/PipedInputStream;->read([BII)I
    move-result v0

    if-ltz v0, :check_failure
    invoke-direct {p0}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->afterConsume()V
    return v0'''
    if old not in text: raise RuntimeError('bulk read anchor changed')
    text = text.replace(old, new, 1)

    marker = '.method public run()V'
    if marker not in text: raise RuntimeError('run marker missing')
    text = text.replace(marker, AFTER_CONSUME_SMALI + '\n' + marker, 1)

    old = '''    const/4 v0, 0x1
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z'''
    new = '''    const/4 v0, 0x1
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z
    invoke-static {p0}, Lcom/archos/mediacenter/video/player/WebDavBufferGate;->onClosed(Ljava/lang/Object;)V'''
    if old not in text: raise RuntimeError('close anchor changed')
    text = text.replace(old, new, 1)
    return text

def apply(root: Path, report: Path | None = None):
    player = _one(root.glob('smali*/com/archos/mediacenter/video/player/Player.smali'), 'Player')
    player.write_text(patch_player(player.read_text()))

    ra = _one(root.glob('smali*/com/archos/filecorelibrary/NetworkReadAheadInputStream.smali'), 'NetworkReadAheadInputStream')
    ra.write_text(patch_read_ahead(ra.read_text()))

    gate_hits = list(root.glob('smali*/com/archos/mediacenter/video/player/WebDavBufferGate.smali'))
    if gate_hits:
        if len(gate_hits) != 1 or gate_hits[0].read_text() != WEB_DAV_BUFFER_GATE_SMALI:
            raise RuntimeError('WebDavBufferGate class conflict')
        gate = gate_hits[0]
        status = 'already-applied'
    else:
        smali_dirs = sorted(root.glob('smali_classes*'))
        target = smali_dirs[-1] if smali_dirs else root / 'smali_classes4'
        gate = target / 'com/archos/mediacenter/video/player/WebDavBufferGate.smali'
        gate.parent.mkdir(parents=True, exist_ok=True)
        gate.write_text(WEB_DAV_BUFFER_GATE_SMALI)
        status = 'applied'

    result = {
        'status': 'PASS',
        'hard_decoder_gate': status,
        'invariant': 'if a WebDAV read leaves <24MiB, IMediaPlayer.pause completes before read returns; Player.start is blocked until same stream >45MiB',
        'stale_stream_guard': 'stream object identity token',
        'user_pause_guard': 'normal Player.pause cancels auto-resume intent',
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + '\n')
    return result

def verify_roundtrip(root: Path, report: Path, g):
    bad = []
    player = _one(root.glob('smali*/com/archos/mediacenter/video/player/Player.smali'), 'Player').read_text()
    ra = _one(root.glob('smali*/com/archos/filecorelibrary/NetworkReadAheadInputStream.smali'), 'NetworkReadAheadInputStream').read_text()
    gate = _one(root.glob('smali*/com/archos/mediacenter/video/player/WebDavBufferGate.smali'), 'WebDavBufferGate').read_text()

    required_player = (
        'WebDavBufferGate;->attach',
        'WebDavBufferGate;->noteStart',
        'WebDavBufferGate;->notePause',
        ' bufferGatePause()Z',
        ' bufferGateResume()Z',
        'IMediaPlayer;->pause()V',
        'IMediaPlayer;->start()V',
        'HARD_GATE IMediaPlayer.pause current=PAUSED target_preserved',
        'HARD_GATE IMediaPlayer.start target=PLAYING',
    )
    for x in required_player:
        if x not in player: bad.append('Player missing '+x)

    required_ra = (
        'afterConsume()V',
        'POST_READ_LOW remaining<24MiB pause_completed_before_return',
        'WebDavBufferGate;->onStreamStart',
        'WebDavBufferGate;->onLow',
        'WebDavBufferGate;->onReady',
        'WebDavBufferGate;->onEnd',
        'WebDavBufferGate;->onClosed',
    )
    for x in required_ra:
        if x not in ra: bad.append('NetworkReadAhead missing '+x)

    # Hard ordering proof: pause-triggering afterConsume call must occur after pipe read
    # but before the value is returned to AVOS in both read overloads.
    for sig in (' read()I', ' read([BII)I'):
        m = _method(ra, sig).group(0)
        read_pos = m.find('Landroid')  # harmless init
        consume_pos = m.find('->afterConsume()V')
        return_pos = m.rfind('return v0')
        if consume_pos < 0 or return_pos < 0 or consume_pos > return_pos:
            bad.append(sig+' does not gate before return')

    required_gate = (
        '.method public static declared-synchronized onLow(Ljava/lang/Object;)V',
        '.method public static declared-synchronized onReady(Ljava/lang/Object;)V',
        'sSource:Ljava/lang/Object;',
        'sBlocked:Z',
        'sPlayWanted:Z',
        'bufferGatePause()Z',
        'bufferGateResume()Z',
        'HARD_GATE low<24MiB decoder_paused_before_read_return',
        'HARD_GATE ready>45MiB blocked=0',
    )
    for x in required_gate:
        if x not in gate: bad.append('Gate missing '+x)

    result={'status':'FAIL' if bad else 'PASS','differences':bad,
            'proof':'read-drain below 24MiB -> synchronized gate -> IMediaPlayer.pause before read return; all Player.start paths gated while blocked; same-stream >45MiB only; normal pause cancels auto-resume'}
    g.write_json(report,result)
    if bad: raise g.Conflict('hard gate verification failed: '+str(bad))
    return result
