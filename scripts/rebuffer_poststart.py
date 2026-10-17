#!/usr/bin/env python3
"""Minimal post-start WebDAV rebuffer patch built from clean main.

No startup gate exists. Player/AVOS starts exactly through the existing main
path. Protection becomes active only after IMediaPlayer.start() has returned
and Player.mCurrentState has been set to PLAYING.

A 64 MiB asynchronous read-ahead pipe is used only for long supersedable
WebDAV media requests. Once playback is active, protection arms after the pipe
has naturally reached 24 MiB at least once. Thereafter a consumer read is never
allowed to cross below the 24 MiB floor: Player/IMediaPlayer is hard-paused
before that read, and resumes only after buffered bytes are strictly >45 MiB.
"""
from __future__ import annotations

from pathlib import Path
import re

METHOD_RE = re.compile(r'^\.method [^\n]+\n.*?^\.end method', re.M | re.S)

def _one(paths, label):
    paths = list(paths)
    if len(paths) != 1:
        raise RuntimeError(f'{label}: expected one target, got {len(paths)}: {paths}')
    return paths[0]

def _method(text: str, signature: str):
    hits = [m for m in METHOD_RE.finditer(text) if signature in m.group(0).splitlines()[0]]
    if len(hits) != 1:
        raise RuntimeError(f'{signature}: expected one method, got {len(hits)}')
    return hits[0]

READ_AHEAD_SMALI = r'''.class public final Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
.super Ljava/io/InputStream;
.source "NetworkReadAheadInputStream.java"

.implements Ljava/lang/Runnable;

.field private static final CAPACITY:I = 0x4000000
.field private static final CHUNK:I = 0x40000
.field private static final LOW_WATERMARK:I = 0x1800000
.field private static final RESUME_WATERMARK:I = 0x2d00000
.field private static final TAG:Ljava/lang/String; = "NovaNetBuf"
.field private static volatile activeStream:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
.field private static volatile globalPlaybackActive:Z

.field private volatile armed:Z
.field private volatile buffering:Z
.field private volatile closed:Z
.field private volatile eof:Z
.field private volatile failure:Ljava/io/IOException;
.field private volatile playbackActive:Z
.field private final pipeIn:Ljava/io/PipedInputStream;
.field private final pipeOut:Ljava/io/PipedOutputStream;
.field private final source:Ljava/io/InputStream;

.method private constructor <init>(Ljava/io/InputStream;)V
    .locals 5
    .annotation system Ldalvik/annotation/Throws;
        value = {
            Ljava/io/IOException;
        }
    .end annotation

    invoke-direct {p0}, Ljava/io/InputStream;-><init>()V
    iput-object p1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->source:Ljava/io/InputStream;

    const/4 v0, 0x0
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->armed:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z

    sget-boolean v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->globalPlaybackActive:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->playbackActive:Z

    new-instance v0, Ljava/io/PipedInputStream;
    const v1, 0x4000000
    invoke-direct {v0, v1}, Ljava/io/PipedInputStream;-><init>(I)V
    iput-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;

    new-instance v1, Ljava/io/PipedOutputStream;
    invoke-direct {v1, v0}, Ljava/io/PipedOutputStream;-><init>(Ljava/io/PipedInputStream;)V
    iput-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeOut:Ljava/io/PipedOutputStream;

    sput-object p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->activeStream:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;

    new-instance v2, Ljava/lang/Thread;
    const-string v3, "Nova WebDAV read-ahead"
    invoke-direct {v2, p0, v3}, Ljava/lang/Thread;-><init>(Ljava/lang/Runnable;Ljava/lang/String;)V
    const/4 v4, 0x1
    invoke-virtual {v2, v4}, Ljava/lang/Thread;->setDaemon(Z)V
    invoke-virtual {v2}, Ljava/lang/Thread;->start()V

    const-string v2, "NovaNetBuf"
    const-string v3, "READ_AHEAD_ON cap=64MiB startup=main-unchanged gate=post-start-only"
    invoke-static {v2, v3}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method public static wrap(Landroid/net/Uri;Ljava/io/InputStream;)Ljava/io/InputStream;
    .locals 4

    if-eqz p0, :original
    if-eqz p1, :original

    invoke-virtual {p0}, Landroid/net/Uri;->getScheme()Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :original

    const-string v1, "webdav"
    invoke-virtual {v1, v0}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-nez v2, :make

    const-string v1, "webdavs"
    invoke-virtual {v1, v0}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-eqz v2, :original

    :make
    :try_start
    new-instance v2, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
    invoke-direct {v2, p1}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;-><init>(Ljava/io/InputStream;)V
    return-object v2
    :try_end
    .catch Ljava/io/IOException; {:try_start .. :try_end} :fallback_io
    .catch Ljava/lang/OutOfMemoryError; {:try_start .. :try_end} :fallback_oom

    :fallback_io
    move-exception v2
    const-string v0, "NovaNetBuf"
    const-string v3, "READ_AHEAD_INIT_IO_FAIL use-main-stream"
    invoke-static {v0, v3, v2}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I
    return-object p1

    :fallback_oom
    move-exception v2
    const-string v0, "NovaNetBuf"
    const-string v3, "READ_AHEAD_INIT_OOM use-main-stream"
    invoke-static {v0, v3, v2}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I

    :original
    return-object p1
.end method

.method public static onPlaybackStarted()V
    .locals 3

    const/4 v0, 0x1
    sput-boolean v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->globalPlaybackActive:Z

    sget-object v1, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->activeStream:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
    if-eqz v1, :done

    iput-boolean v0, v1, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->playbackActive:Z
    const/4 v0, 0x0
    iput-boolean v0, v1, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->armed:Z
    iput-boolean v0, v1, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    const-string v0, "NovaNetBuf"
    const-string v2, "PLAYBACK_STARTED main-start-complete protection-waiting-for-24MiB"
    invoke-static {v0, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    :done
    return-void
.end method

.method public static onPlaybackStopped()V
    .locals 2

    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->globalPlaybackActive:Z

    sget-object v1, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->activeStream:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
    if-eqz v1, :done

    iput-boolean v0, v1, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->playbackActive:Z
    iput-boolean v0, v1, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->armed:Z
    iput-boolean v0, v1, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    :done
    return-void
.end method

.method public static forceArm()V
    .locals 2

    sget-boolean v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->globalPlaybackActive:Z
    if-eqz v0, :done

    sget-object v1, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->activeStream:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
    if-eqz v1, :done

    const/4 v0, 0x1
    iput-boolean v0, v1, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->armed:Z

    :done
    return-void
.end method

.method private ensureBudget(I)V
    .locals 7
    .annotation system Ldalvik/annotation/Throws;
        value = {
            Ljava/io/IOException;
        }
    .end annotation

    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->playbackActive:Z
    if-eqz v0, :return

    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->armed:Z
    if-nez v0, :gate

    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->available()I
    move-result v0

    const v1, 0x1800000
    if-lt v0, v1, :return

    const/4 v2, 0x1
    iput-boolean v2, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->armed:Z

    const-string v2, "NovaNetBuf"
    const-string v3, "PROTECTION_ARMED buffer>=24MiB"
    invoke-static {v2, v3}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    :gate
    :loop
    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->playbackActive:Z
    if-eqz v0, :return

    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    if-nez v0, :return

    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    if-eqz v0, :normal

    iget-object v4, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->failure:Ljava/io/IOException;
    if-eqz v4, :buffer_check
    throw v4

    :buffer_check
    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->available()I
    move-result v0

    iget-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z
    if-nez v1, :resume

    const v1, 0x2d00000
    if-le v0, v1, :wait_more

    :resume
    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->bufferResumeCurrent()V
    const/4 v1, 0x0
    iput-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    const-string v2, "NovaNetBuf"
    const-string v3, "HARD_RESUME buffer>45MiB"
    invoke-static {v2, v3}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    goto :loop

    :wait_more
    const-wide/32 v5, 0x4c4b40
    invoke-static {v5, v6}, Ljava/util/concurrent/locks/LockSupport;->parkNanos(J)V
    goto :loop

    :normal
    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->available()I
    move-result v0

    const v1, 0x1800000
    add-int v2, v1, p1
    if-ge v0, v2, :return

    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->bufferPauseCurrent()Z
    move-result v3
    if-eqz v3, :return

    const/4 v3, 0x1
    iput-boolean v3, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    const-string v2, "NovaNetBuf"
    const-string v4, "HARD_PAUSE before-crossing-24MiB"
    invoke-static {v2, v4}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    goto :loop

    :return
    return-void
.end method

.method public run()V
    .locals 5

    const v0, 0x40000
    new-array v0, v0, [B

    :loop
    iget-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    if-nez v1, :finish

    :try_start_0
    iget-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->source:Ljava/io/InputStream;
    const/4 v2, 0x0
    array-length v3, v0
    invoke-virtual {v1, v0, v2, v3}, Ljava/io/InputStream;->read([BII)I
    move-result v1
    if-ltz v1, :finish
    if-eqz v1, :loop

    iget-object v3, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeOut:Ljava/io/PipedOutputStream;
    invoke-virtual {v3, v0, v2, v1}, Ljava/io/OutputStream;->write([BII)V
    goto :loop
    :try_end_0
    .catch Ljava/io/IOException; {:try_start_0 .. :try_end_0} :io_fail

    :io_fail
    move-exception v1
    iget-boolean v2, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    if-nez v2, :finish
    iput-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->failure:Ljava/io/IOException;

    :finish
    const/4 v1, 0x1
    iput-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z

    :try_start_1
    iget-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeOut:Ljava/io/PipedOutputStream;
    invoke-virtual {v1}, Ljava/io/PipedOutputStream;->close()V
    :try_end_1
    .catch Ljava/io/IOException; {:try_start_1 .. :try_end_1} :done

    :done
    return-void
.end method

.method public declared-synchronized read()I
    .locals 2

    const/4 v0, 0x1
    invoke-direct {p0, v0}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->ensureBudget(I)V

    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->read()I
    move-result v0
    if-ltz v0, :check_failure
    return v0

    :check_failure
    iget-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->failure:Ljava/io/IOException;
    if-eqz v1, :return_value
    throw v1

    :return_value
    return v0
.end method

.method public declared-synchronized read([BII)I
    .locals 2

    invoke-direct {p0, p3}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->ensureBudget(I)V

    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0, p1, p2, p3}, Ljava/io/PipedInputStream;->read([BII)I
    move-result v0
    if-ltz v0, :check_failure
    return v0

    :check_failure
    iget-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->failure:Ljava/io/IOException;
    if-eqz v1, :return_value
    throw v1

    :return_value
    return v0
.end method

.method public available()I
    .locals 1

    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->available()I
    move-result v0
    return v0
.end method

.method public skip(J)J
    .locals 2

    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0, p1, p2}, Ljava/io/PipedInputStream;->skip(J)J
    move-result-wide v0
    return-wide v0
.end method

.method public close()V
    .locals 2

    const/4 v0, 0x1
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z

    const/4 v0, 0x0
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->playbackActive:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->armed:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    sget-object v1, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->activeStream:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
    if-ne v1, p0, :close_source
    const/4 v1, 0x0
    sput-object v1, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->activeStream:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;

    :close_source
    :try_start_0
    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->source:Ljava/io/InputStream;
    invoke-virtual {v0}, Ljava/io/InputStream;->close()V
    :try_end_0
    .catch Ljava/io/IOException; {:try_start_0 .. :try_end_0} :close_in

    :close_in
    :try_start_1
    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->close()V
    :try_end_1
    .catch Ljava/io/IOException; {:try_start_1 .. :try_end_1} :close_out

    :close_out
    :try_start_2
    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeOut:Ljava/io/PipedOutputStream;
    invoke-virtual {v0}, Ljava/io/PipedOutputStream;->close()V
    :try_end_2
    .catch Ljava/io/IOException; {:try_start_2 .. :try_end_2} :done

    :done
    return-void
.end method
'''

SESSION_POLICY_SMALI = r'''.method private shouldUseNovaReadAhead()Z
    .locals 7

    iget-boolean v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->supersedableMediaRequest:Z
    if-eqz v0, :no

    iget-object v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->this$0:Lcom/archos/filecorelibrary/StreamOverHttp;
    invoke-static {v0}, Lcom/archos/filecorelibrary/StreamOverHttp;->l(Lcom/archos/filecorelibrary/StreamOverHttp;)Landroid/net/Uri;
    move-result-object v0
    if-eqz v0, :no

    invoke-virtual {v0}, Landroid/net/Uri;->getScheme()Ljava/lang/String;
    move-result-object v1
    if-eqz v1, :no

    const-string v2, "webdav"
    invoke-virtual {v2, v1}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v3
    if-nez v3, :range_check

    const-string v2, "webdavs"
    invoke-virtual {v2, v1}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v3
    if-eqz v3, :no

    :range_check
    iget-wide v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->requestedEnd:J
    const-wide/16 v2, 0x0
    cmp-long v4, v0, v2
    if-ltz v4, :yes

    iget-wide v2, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->requestedStart:J
    sub-long/2addr v0, v2
    const-wide/16 v2, 0x1
    add-long/2addr v0, v2

    const-wide/32 v5, 0x800000
    cmp-long v0, v0, v5
    if-lez v0, :no

    :yes
    const/4 v0, 0x1
    return v0

    :no
    const/4 v0, 0x0
    return v0
.end method
'''

PLAYER_HELPERS_SMALI = r'''.method public static bufferPauseCurrent()Z
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

    invoke-interface {v1}, Lcom/archos/medialib/IMediaPlayer;->isPlaying()Z
    move-result v3
    if-eqz v3, :no

    invoke-interface {v1}, Lcom/archos/medialib/IMediaPlayer;->pause()V

    const/4 v3, 0x1
    sput-boolean v3, Lcom/archos/mediacenter/video/player/Player;->sNovaBufferPaused:Z

    const-string v0, "NovaNetBuf"
    const-string v1, "PLAYER_HARD_PAUSE"
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
    const-string v1, "PLAYER_HARD_RESUME"
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
'''

def patch_session(text: str) -> tuple[str, str]:
    if ' shouldUseNovaReadAhead()Z' in text:
        if 'NetworkReadAheadInputStream;->wrap' in text:
            return text, 'already-applied'
        raise RuntimeError('partial HttpSession patch')

    m = _method(text, ' publishInput(Ljava/io/InputStream;)V')
    body = m.group(0)
    anchor = '    if-eqz p1, :cond_2\n'
    if body.count(anchor) != 1:
        raise RuntimeError('publishInput null-check anchor changed')

    inject = (
        anchor +
        '\n    invoke-direct {p0}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->shouldUseNovaReadAhead()Z\n'
        '    move-result v0\n'
        '    if-eqz v0, :nova_after_readahead\n\n'
        '    iget-object v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->this$0:Lcom/archos/filecorelibrary/StreamOverHttp;\n'
        '    invoke-static {v0}, Lcom/archos/filecorelibrary/StreamOverHttp;->l(Lcom/archos/filecorelibrary/StreamOverHttp;)Landroid/net/Uri;\n'
        '    move-result-object v0\n'
        '    invoke-static {v0, p1}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->wrap(Landroid/net/Uri;Ljava/io/InputStream;)Ljava/io/InputStream;\n'
        '    move-result-object p1\n\n'
        '    :nova_after_readahead\n'
    )
    body = body.replace(anchor, inject, 1)
    text = text[:m.start()] + body + text[m.end():]
    return text.rstrip() + '\n\n' + SESSION_POLICY_SMALI + '\n', 'applied'

def patch_player(text: str) -> tuple[str, str]:
    if 'sNovaBufferPaused:Z' in text:
        required = ('NetworkReadAheadInputStream;->onPlaybackStarted()V',
                    'NetworkReadAheadInputStream;->onPlaybackStopped()V',
                    'NetworkReadAheadInputStream;->forceArm()V',
                    ' bufferPauseCurrent()Z', ' bufferResumeCurrent()V')
        if all(x in text for x in required):
            return text, 'already-applied'
        raise RuntimeError('partial Player patch')

    field_anchor = '.field public static sPlayer:Lcom/archos/mediacenter/video/player/Player;\n'
    if text.count(field_anchor) != 1:
        raise RuntimeError('Player.sPlayer field anchor changed')
    text = text.replace(field_anchor, field_anchor + '\n.field private static volatile sNovaBufferPaused:Z\n', 1)

    # Main startup remains byte-for-byte unchanged until its successful tail.
    # Activation is the final action on the successful start path, after nativeStart,
    # PLAYING state, stayAwake, listener onPlay, and VideoEffectRenderer.onPlay.
    m = _method(text, ' start(I)V')
    body = m.group(0)
    tail_anchor = (
        '    :cond_5\n'
        '    iget-object p0, p0, Lcom/archos/mediacenter/video/player/Player;->mEffectRenderer:Lcom/archos/mediacenter/video/player/VideoEffectRenderer;\n\n'
        '    if-eqz p0, :cond_6\n\n'
        '    invoke-virtual {p0}, Lcom/archos/mediacenter/video/player/VideoEffectRenderer;->onPlay()V\n\n'
        '    :cond_6'
    )
    if body.count(tail_anchor) != 1:
        raise RuntimeError('Player.start successful-tail anchor changed')
    tail_replacement = (
        '    :cond_5\n'
        '    iget-object p0, p0, Lcom/archos/mediacenter/video/player/Player;->mEffectRenderer:Lcom/archos/mediacenter/video/player/VideoEffectRenderer;\n\n'
        '    if-eqz p0, :nova_rebuffer_start_done\n\n'
        '    invoke-virtual {p0}, Lcom/archos/mediacenter/video/player/VideoEffectRenderer;->onPlay()V\n\n'
        '    :nova_rebuffer_start_done\n'
        '    invoke-static {}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->onPlaybackStarted()V\n\n'
        '    :cond_6'
    )
    body = body.replace(tail_anchor, tail_replacement, 1)
    text = text[:m.start()] + body + text[m.end():]

    # Manual pause disables automatic rebuffer resume before normal main pause logic.
    m = _method(text, ' pause(I)V')
    body = m.group(0)
    locals_end = body.find('\n', body.find('.locals '))
    body = body[:locals_end] + (
        '\n\n    invoke-static {}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->onPlaybackStopped()V'
        '\n    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->cancelBufferPause()V'
    ) + body[locals_end:]
    text = text[:m.start()] + body + text[m.end():]

    m = _method(text, ' stopPlayback()V')
    body = m.group(0)
    locals_end = body.find('\n', body.find('.locals '))
    body = body[:locals_end] + (
        '\n\n    invoke-static {}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->onPlaybackStopped()V'
        '\n    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->cancelBufferPause()V'
    ) + body[locals_end:]
    text = text[:m.start()] + body + text[m.end():]

    m = _method(text, ' onCompletion(Lcom/archos/medialib/IMediaPlayer;)V')
    body = m.group(0)
    anchor = '    :cond_0\n    const/4 p1, 0x7'
    if body.count(anchor) != 1:
        raise RuntimeError('Player.onCompletion anchor changed')
    body = body.replace(
        anchor,
        '    :cond_0\n'
        '    invoke-static {}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->onPlaybackStopped()V\n'
        '    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->cancelBufferPause()V\n\n'
        '    const/4 p1, 0x7',
        1)
    text = text[:m.start()] + body + text[m.end():]

    # Native buffering after playback has started forces the byte-floor protection armed.
    m = _method(text, ' onInfo(Lcom/archos/medialib/IMediaPlayer;II)Z')
    body = m.group(0)
    anchor = '    :cond_0\n    sget-object v0, Lcom/archos/mediacenter/video/player/Player;->log:Lorg/slf4j/Logger;'
    if body.count(anchor) != 1:
        raise RuntimeError('Player.onInfo verified-player anchor changed')
    body = body.replace(
        anchor,
        '    :cond_0\n'
        '    const/16 v2, 0x2bd\n'
        '    if-ne p2, v2, :nova_not_buffering_start\n'
        '    invoke-static {}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->forceArm()V\n'
        '    :nova_not_buffering_start\n'
        '    sget-object v0, Lcom/archos/mediacenter/video/player/Player;->log:Lorg/slf4j/Logger;',
        1)
    text = text[:m.start()] + body + text[m.end():]

    return text.rstrip() + '\n\n' + PLAYER_HELPERS_SMALI + '\n', 'applied'

def _next_smali_dir(root: Path) -> Path:
    used = {p.name for p in root.iterdir() if p.is_dir() and p.name.startswith('smali_classes')}
    n = 2
    while f'smali_classes{n}' in used:
        n += 1
    out = root / f'smali_classes{n}'
    out.mkdir(parents=True, exist_ok=True)
    return out

def apply(root: Path, report: Path | None = None):
    session = _one(root.glob('smali*/com/archos/filecorelibrary/StreamOverHttp$HttpSession.smali'), 'HttpSession')
    st, ss = patch_session(session.read_text())
    session.write_text(st)

    player = _one(root.glob('smali*/com/archos/mediacenter/video/player/Player.smali'), 'Player')
    pt, ps = patch_player(player.read_text())
    player.write_text(pt)

    hits = list(root.glob('smali*/com/archos/filecorelibrary/NetworkReadAheadInputStream.smali'))
    if hits:
        raise RuntimeError('clean-main invariant violated: NetworkReadAheadInputStream already exists')
    smali_dir = _next_smali_dir(root)
    path = smali_dir / 'com/archos/filecorelibrary/NetworkReadAheadInputStream.smali'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(READ_AHEAD_SMALI)

    result = {
        'status': 'PASS',
        'session_patch': ss,
        'player_patch': ps,
        'capacity_mib': 64,
        'low_floor_mib': 24,
        'resume_strictly_above_mib': 45,
        'startup_gate': False,
        'activation_point': 'after existing IMediaPlayer.start() and mCurrentState=PLAYING',
        'arming': 'after post-start read-ahead naturally reaches 24 MiB, or native BUFFERING_START',
        'old_code_reused': False,
    }
    if report:
        import json
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + '\n')
    return result
