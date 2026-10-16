#!/usr/bin/env python3
"""Fail-closed WebDAV hard buffer gate on top of the clean main baseline.

The parser/probe/prepare path is never preblocked. Once AVOS has actually
started playback, every guarded WebDAV read checks the 64 MiB read-ahead pipe.
Below 24 MiB it synchronously hard-pauses the current Player/IMediaPlayer before
returning more input; it remains blocked until the pipe is strictly above
45 MiB, then hard-resumes. User pause/stop disarms automatic resume.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

METHOD_RE = re.compile(r'^\.method [^\n]+\n.*?^\.end method', re.M | re.S)

def _one(paths, label):
    paths = list(paths)
    if len(paths) != 1:
        raise RuntimeError(f'{label}: expected one target, got {len(paths)}: {paths}')
    return paths[0]

STREAM_SOURCE_URI_SMALI = r'''.method public getSourceUri()Landroid/net/Uri;
    .locals 1

    iget-object v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp;->mUri:Landroid/net/Uri;

    return-object v0
.end method
'''

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

.field private volatile buffering:Z
.field private volatile closed:Z
.field private volatile eof:Z
.field private volatile failure:Ljava/io/IOException;
.field private volatile initialHold:Z
.field private volatile playbackActive:Z
.field private final pipeIn:Ljava/io/PipedInputStream;
.field private final pipeOut:Ljava/io/PipedOutputStream;
.field private final source:Ljava/io/InputStream;

.method private constructor <init>(Ljava/io/InputStream;)V
    .locals 5

    invoke-direct {p0}, Ljava/io/InputStream;-><init>()V
    iput-object p1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->source:Ljava/io/InputStream;

    const/4 v0, 0x0
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->initialHold:Z

    sget-boolean v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->globalPlaybackActive:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->playbackActive:Z

    new-instance v0, Ljava/io/PipedInputStream;
    const v1, 0x4000000
    invoke-direct {v0, v1}, Ljava/io/PipedInputStream;-><init>(I)V
    iput-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;

    new-instance v1, Ljava/io/PipedOutputStream;
    invoke-direct {v1, v0}, Ljava/io/PipedOutputStream;-><init>(Ljava/io/PipedInputStream;)V
    iput-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeOut:Ljava/io/PipedOutputStream;

    sget-object v2, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->activeStream:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
    if-eqz v2, :no_old_stream
    if-eq v2, p0, :no_old_stream
    invoke-virtual {v2}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->close()V

    const-string v3, "NovaNetBuf"
    const-string v4, "HARD_GATE_REPLACE_OLD close_previous=1"
    invoke-static {v3, v4}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    :no_old_stream
    sput-object p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->activeStream:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;

    new-instance v2, Ljava/lang/Thread;
    const-string v3, "Nova WebDAV hard-buffer producer"
    invoke-direct {v2, p0, v3}, Ljava/lang/Thread;-><init>(Ljava/lang/Runnable;Ljava/lang/String;)V
    const/4 v4, 0x1
    invoke-virtual {v2, v4}, Ljava/lang/Thread;->setDaemon(Z)V
    invoke-virtual {v2}, Ljava/lang/Thread;->start()V

    new-instance v2, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream$Watchdog;
    invoke-direct {v2, p0}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream$Watchdog;-><init>(Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;)V

    new-instance v3, Ljava/lang/Thread;
    const-string v4, "Nova WebDAV buffer watchdog"
    invoke-direct {v3, v2, v4}, Ljava/lang/Thread;-><init>(Ljava/lang/Runnable;Ljava/lang/String;)V
    const/4 v4, 0x1
    invoke-virtual {v3, v4}, Ljava/lang/Thread;->setDaemon(Z)V
    invoke-virtual {v3}, Ljava/lang/Thread;->start()V
    return-void
.end method

.method public static isPlaybackActive()Z
    .locals 1
    sget-boolean v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->globalPlaybackActive:Z
    return v0
.end method

.method public static setPlaybackActive(Z)V
    .locals 2

    sput-boolean p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->globalPlaybackActive:Z

    sget-object v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->activeStream:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
    if-eqz v0, :done

    iput-boolean p0, v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->playbackActive:Z
    if-nez p0, :done

    const/4 v1, 0x0
    iput-boolean v1, v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    iput-boolean v1, v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->initialHold:Z

    :done
    return-void
.end method

.method public static beforeNativeStart(Landroid/net/Uri;)Z
    .locals 5

    if-eqz p0, :unguarded_ok

    invoke-virtual {p0}, Landroid/net/Uri;->getScheme()Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :unguarded_ok

    const-string v1, "webdav"
    invoke-virtual {v1, v0}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-nez v2, :webdav_required

    const-string v1, "webdavs"
    invoke-virtual {v1, v0}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-eqz v2, :unguarded_ok

    :webdav_required
    sget-object v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->activeStream:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
    if-eqz v0, :missing_guard

    const/4 v1, 0x1
    sput-boolean v1, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->globalPlaybackActive:Z
    iput-boolean v1, v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->playbackActive:Z

    iget-object v2, v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->failure:Ljava/io/IOException;
    if-nez v2, :fail_closed

    iget-boolean v2, v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    if-nez v2, :hold

    iget-boolean v2, v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z
    if-nez v2, :ready

    iget-object v2, v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v2}, Ljava/io/PipedInputStream;->available()I
    move-result v2

    const v3, 0x1840000
    if-ge v2, v3, :ready

    :hold
    const/4 v1, 0x1
    iput-boolean v1, v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    iput-boolean v1, v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->initialHold:Z

    const-string v1, "NovaNetBuf"
    const-string v2, "INITIAL_HOLD prepared=1 wait_for_24MiB_floor"
    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    const/4 v0, 0x0
    return v0

    :missing_guard
    const-string v0, "NovaNetBuf"
    const-string v1, "INITIAL_HOLD webdav_without_guarded_media_stream fail_closed"
    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I
    const/4 v0, 0x0
    return v0

    :fail_closed
    const/4 v1, 0x1
    iput-boolean v1, v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    iput-boolean v1, v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->initialHold:Z

    const-string v1, "NovaNetBuf"
    const-string v2, "INITIAL_HOLD network_failure fail_closed"
    invoke-static {v1, v2}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I

    const/4 v0, 0x0
    return v0

    :ready
    const/4 v2, 0x0
    iput-boolean v2, v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->initialHold:Z
    iput-boolean v2, v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    :unguarded_ok
    const/4 v0, 0x1
    return v0
.end method

.method public static wrap(Landroid/net/Uri;Ljava/io/InputStream;Z)Ljava/io/InputStream;
    .locals 5

    if-eqz p1, :return_original
    if-eqz p0, :return_original

    invoke-virtual {p0}, Landroid/net/Uri;->getScheme()Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :return_original

    const-string v1, "webdav"
    invoke-virtual {v1, v0}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-nez v2, :scheme_ok

    const-string v1, "webdavs"
    invoke-virtual {v1, v0}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-eqz v2, :return_original

    :scheme_ok
    if-eqz p2, :return_original

    :wrap_stream
    :try_start_0
    new-instance v2, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
    invoke-direct {v2, p1}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;-><init>(Ljava/io/InputStream;)V

    const-string v3, "NovaNetBuf"
    const-string v4, "HARD_GATE_ON cap=64MiB low<24MiB resume>45MiB startup=prepare-pass watchdog=5ms"
    invoke-static {v3, v4}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-object v2
    :try_end_0
    .catch Ljava/io/IOException; {:try_start_0 .. :try_end_0} :catch_io
    .catch Ljava/lang/OutOfMemoryError; {:try_start_0 .. :try_end_0} :catch_oom

    :catch_io
    move-exception v2
    const-string v3, "NovaNetBuf"
    const-string v4, "HARD_GATE_INIT_IO_FAIL fail_closed"
    invoke-static {v3, v4, v2}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I
    throw v2

    :catch_oom
    move-exception v2
    const-string v3, "NovaNetBuf"
    const-string v4, "HARD_GATE_INIT_OOM fail_closed"
    invoke-static {v3, v4, v2}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I
    throw v2

    :return_original
    return-object p1
.end method

.method private awaitBudget(I)V
    .locals 5

    :loop
    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    if-nez v0, :return

    sget-object v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->activeStream:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
    if-ne v0, p0, :stale

    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->playbackActive:Z
    if-nez v0, :active

    const/4 v0, 0x0
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    return-void

    :active
    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    if-eqz v0, :not_buffering

    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->failure:Ljava/io/IOException;
    if-nez v0, :throw_failure

    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->initialHold:Z
    if-nez v0, :wait_more

    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z
    if-eqz v0, :rebuffer_check

    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->bufferResumeCurrent()V
    const/4 v0, 0x0
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    return-void

    :rebuffer_check
    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->available()I
    move-result v0

    const v1, 0x2d00000
    if-le v0, v1, :wait_more

    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->bufferResumeCurrent()V
    const/4 v0, 0x0
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    goto :loop

    :not_buffering
    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z
    if-eqz v0, :budget_check

    iget-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->failure:Ljava/io/IOException;
    if-nez v1, :throw_failure
    return-void

    :budget_check
    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->available()I
    move-result v0

    const v1, 0x1800000
    add-int v2, v1, p1
    if-ge v0, v2, :return

    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->bufferPauseCurrent()Z
    move-result v2

    const/4 v3, 0x1
    iput-boolean v3, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    iget-object v4, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->failure:Ljava/io/IOException;
    if-nez v4, :throw_failure_v4

    const-string v3, "NovaNetBuf"
    if-eqz v2, :pause_confirmed
    const-string v4, "HARD_WAIT floor_would_cross_24MiB player_already_not_running"
    invoke-static {v3, v4}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    goto :wait_more

    :pause_confirmed
    const-string v4, "HARD_PAUSE before_floor_cross nativePause=1"
    invoke-static {v3, v4}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    :wait_more
    const-wide/32 v1, 0x4c4b40
    invoke-static {v1, v2}, Ljava/util/concurrent/locks/LockSupport;->parkNanos(J)V
    goto :loop

    :throw_failure_v4
    throw v4

    :throw_failure
    throw v0

    :stale
    invoke-virtual {p0}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->close()V

    :return
    return-void
.end method

.method public monitorLoop()V
    .locals 5

    :loop
    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    if-nez v0, :return

    sget-object v0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->activeStream:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
    if-ne v0, p0, :return

    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->playbackActive:Z
    if-eqz v0, :sleep

    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->available()I
    move-result v0

    iget-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    if-eqz v1, :not_buffering

    iget-object v2, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->failure:Ljava/io/IOException;
    if-nez v2, :sleep

    iget-boolean v2, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->initialHold:Z
    if-eqz v2, :rebuffer_wait

    iget-boolean v2, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z
    if-nez v2, :initial_ready

    const v3, 0x1840000
    if-lt v0, v3, :sleep

    :initial_ready
    const/4 v2, 0x0
    iput-boolean v2, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->initialHold:Z
    iput-boolean v2, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->bufferStartHeldCurrent()V

    const-string v2, "NovaNetBuf"
    const-string v3, "INITIAL_RELEASE floor>=24MiB_or_clean_eof"
    invoke-static {v2, v3}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    goto :sleep

    :rebuffer_wait
    iget-boolean v2, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z
    if-nez v2, :resume

    const v3, 0x2d00000
    if-le v0, v3, :sleep

    :resume
    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->bufferResumeCurrent()V
    const/4 v2, 0x0
    iput-boolean v2, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    const-string v2, "NovaNetBuf"
    const-string v3, "WATCHDOG_RESUME buffer>45MiB_or_clean_eof"
    invoke-static {v2, v3}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    goto :sleep

    :not_buffering
    iget-object v2, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->failure:Ljava/io/IOException;
    if-eqz v2, :clean_eof_check

    const v3, 0x1800000
    if-ge v0, v3, :sleep

    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->bufferPauseCurrent()Z
    const/4 v2, 0x1
    iput-boolean v2, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    const-string v2, "NovaNetBuf"
    const-string v3, "NETWORK_FAILURE_HARD_PAUSE fail_closed"
    invoke-static {v2, v3}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I
    goto :sleep

    :clean_eof_check
    iget-boolean v2, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z
    if-nez v2, :sleep

    const v3, 0x1800000
    if-ge v0, v3, :sleep

    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->bufferPauseCurrent()Z
    const/4 v2, 0x1
    iput-boolean v2, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    const-string v2, "NovaNetBuf"
    const-string v3, "WATCHDOG_HARD_PAUSE buffer<24MiB"
    invoke-static {v2, v3}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    :sleep
    const-wide/32 v2, 0x4c4b40
    invoke-static {v2, v3}, Ljava/util/concurrent/locks/LockSupport;->parkNanos(J)V
    goto :loop

    :return
    return-void
.end method

.method public run()V
    .locals 5

    const v0, 0x40000
    new-array v0, v0, [B

    :read_loop
    iget-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    if-nez v1, :finish

    :try_start_0
    iget-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->source:Ljava/io/InputStream;
    const/4 v2, 0x0
    array-length v3, v0
    invoke-virtual {v1, v0, v2, v3}, Ljava/io/InputStream;->read([BII)I
    move-result v1
    if-ltz v1, :finish
    if-eqz v1, :read_loop

    iget-object v3, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeOut:Ljava/io/PipedOutputStream;
    invoke-virtual {v3, v0, v2, v1}, Ljava/io/OutputStream;->write([BII)V
    goto :read_loop
    :try_end_0
    .catch Ljava/io/IOException; {:try_start_0 .. :try_end_0} :catch_io

    :catch_io
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
    .catch Ljava/io/IOException; {:try_start_1 .. :try_end_1} :after_pipe

    :after_pipe
    :try_start_2
    iget-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->source:Ljava/io/InputStream;
    invoke-virtual {v1}, Ljava/io/InputStream;->close()V
    :try_end_2
    .catch Ljava/io/IOException; {:try_start_2 .. :try_end_2} :done

    :done
    return-void
.end method

.method public declared-synchronized read()I
    .locals 2

    const/4 v0, 0x1
    invoke-direct {p0, v0}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->awaitBudget(I)V

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
    .locals 3

    const v0, 0x40000
    if-le p3, v0, :budget_ready
    move p3, v0

    :budget_ready
    invoke-direct {p0, p3}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->awaitBudget(I)V

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

.method public declared-synchronized skip(J)J
    .locals 5

    const v0, 0x40000
    invoke-direct {p0, v0}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->awaitBudget(I)V

    const-wide/32 v0, 0x40000
    cmp-long v2, p1, v0
    if-lez v2, :skip_ready
    move-wide p1, v0

    :skip_ready
    iget-object v2, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v2, p1, p2}, Ljava/io/PipedInputStream;->skip(J)J
    move-result-wide v0
    return-wide v0
.end method

.method public close()V
    .locals 2

    const/4 v0, 0x1
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z

    const/4 v0, 0x0
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->playbackActive:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->initialHold:Z

    sget-object v1, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->activeStream:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
    if-ne v1, p0, :after_clear
    const/4 v1, 0x0
    sput-object v1, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->activeStream:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;

    :after_clear
    :try_start_0
    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->source:Ljava/io/InputStream;
    invoke-virtual {v0}, Ljava/io/InputStream;->close()V
    :try_end_0
    .catch Ljava/io/IOException; {:try_start_0 .. :try_end_0} :after_source

    :after_source
    :try_start_1
    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->close()V
    :try_end_1
    .catch Ljava/io/IOException; {:try_start_1 .. :try_end_1} :after_in

    :after_in
    :try_start_2
    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeOut:Ljava/io/PipedOutputStream;
    invoke-virtual {v0}, Ljava/io/PipedOutputStream;->close()V
    :try_end_2
    .catch Ljava/io/IOException; {:try_start_2 .. :try_end_2} :done
    :done
    return-void
.end method
'''

WATCHDOG_SMALI = r'''.class final Lcom/archos/filecorelibrary/NetworkReadAheadInputStream$Watchdog;
.super Ljava/lang/Object;
.source "NetworkReadAheadInputStream.java"

.implements Ljava/lang/Runnable;

.field private final parent:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;

.method public constructor <init>(Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;)V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    iput-object p1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream$Watchdog;->parent:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
    return-void
.end method

.method public run()V
    .locals 1
    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream$Watchdog;->parent:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
    invoke-virtual {v0}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->monitorLoop()V
    return-void
.end method
'''


STREAM_SESSION_POLICY_SMALI = r'''.method private shouldUseNetworkReadAhead()Z
    .locals 6

    iget-boolean v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->supersedableMediaRequest:Z
    if-eqz v0, :no

    iget-wide v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->length:J
    const-wide/32 v2, 0x800000
    cmp-long v4, v0, v2
    if-ltz v4, :no

    iget-boolean v4, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->partialResponse:Z
    if-eqz v4, :yes

    iget-wide v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->requestedEnd:J
    iget-wide v2, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->length:J
    const-wide/16 v4, 0x1
    sub-long/2addr v2, v4
    cmp-long v4, v0, v2
    if-nez v4, :no

    iget-wide v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->requestedEnd:J
    iget-wide v2, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->requestedStart:J
    sub-long/2addr v0, v2

    const-wide/32 v2, 0x800000
    cmp-long v4, v0, v2
    if-ltz v4, :no

    :yes
    const/4 v0, 0x1
    return v0

    :no
    const/4 v0, 0x0
    return v0
.end method
'''

PLAYER_BUFFER_METHODS_SMALI = r'''
.method public static bufferPauseCurrent()Z
    .locals 4

    sget-boolean v0, Lcom/archos/mediacenter/video/player/Player;->sBufferPaused:Z
    if-eqz v0, :not_already
    const/4 v0, 0x1
    return v0

    :not_already
    sget-object v0, Lcom/archos/mediacenter/video/player/Player;->sPlayer:Lcom/archos/mediacenter/video/player/Player;
    if-eqz v0, :no

    iget v1, v0, Lcom/archos/mediacenter/video/player/Player;->mTargetState:I
    const/4 v2, 0x5
    if-ne v1, v2, :no

    iget-object v1, v0, Lcom/archos/mediacenter/video/player/Player;->mMediaPlayer:Lcom/archos/medialib/IMediaPlayer;
    if-eqz v1, :no

    invoke-interface {v1}, Lcom/archos/medialib/IMediaPlayer;->isPlaying()Z
    move-result v3
    if-eqz v3, :no

    invoke-interface {v1}, Lcom/archos/medialib/IMediaPlayer;->pause()V
    const/4 v3, 0x1
    sput-boolean v3, Lcom/archos/mediacenter/video/player/Player;->sBufferPaused:Z

    const-string v0, "NovaNetBuf"
    const-string v1, "PLAYER_HARD_PAUSE nativePause=1 targetPlaying=1"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return v3

    :no
    const/4 v0, 0x0
    return v0
.end method

.method public static bufferResumeCurrent()V
    .locals 4

    sget-boolean v0, Lcom/archos/mediacenter/video/player/Player;->sBufferPaused:Z
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
    sput-boolean v3, Lcom/archos/mediacenter/video/player/Player;->sBufferPaused:Z

    const-string v0, "NovaNetBuf"
    const-string v1, "PLAYER_HARD_RESUME nativeStart=1 targetPlaying=1"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void

    :clear
    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/mediacenter/video/player/Player;->sBufferPaused:Z

    :done
    return-void
.end method

.method public static bufferStartHeldCurrent()V
    .locals 3

    sget-object v0, Lcom/archos/mediacenter/video/player/Player;->sPlayer:Lcom/archos/mediacenter/video/player/Player;
    if-eqz v0, :done

    iget v1, v0, Lcom/archos/mediacenter/video/player/Player;->mTargetState:I
    const/4 v2, 0x5
    if-ne v1, v2, :done

    const/4 v1, 0x0
    invoke-virtual {v0, v1}, Lcom/archos/mediacenter/video/player/Player;->start(I)V

    :done
    return-void
.end method

.method public static cancelBufferPause()V
    .locals 1

    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/mediacenter/video/player/Player;->sBufferPaused:Z
    return-void
.end method
'''



def patch_stream_over_http_text(text: str) -> tuple[str, str]:
    sig = ' getSourceUri()Landroid/net/Uri;'
    if sig in text:
        return text, 'already-applied'
    if 'mUri:Landroid/net/Uri;' not in text:
        raise RuntimeError('StreamOverHttp.mUri missing')

    methods = []
    for m in METHOD_RE.finditer(text):
        first = m.group(0).splitlines()[0]
        if ' copyStream(' in first:
            methods.append(m)
    if len(methods) != 1:
        raise RuntimeError(f'StreamOverHttp.copyStream missing/ambiguous: {len(methods)}')
    m = methods[0]
    body = m.group(0)
    flush_re = re.compile(r'\n\s*invoke-virtual \{[^}]+\}, Ljava/io/OutputStream;->flush\(\)V')
    hits = list(flush_re.finditer(body))
    if len(hits) > 1:
        raise RuntimeError(f'StreamOverHttp per-chunk flush ambiguous: {len(hits)}')
    if hits:
        body = body[:hits[0].start()] + body[hits[0].end():]
    text = text[:m.start()] + body + text[m.end():]
    return text.rstrip() + '\n\n' + STREAM_SOURCE_URI_SMALI + '\n', 'applied'


def patch_stream_http_session_text(text: str) -> tuple[str, str]:
    wrapper = (
        'Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->wrap'
        '(Landroid/net/Uri;Ljava/io/InputStream;Z)Ljava/io/InputStream;'
    )
    policy = ' shouldUseNetworkReadAhead()Z'
    if wrapper in text and policy in text:
        return text, 'already-applied'
    if wrapper in text or policy in text:
        raise RuntimeError('Partial WebDAV read-ahead patch found')

    methods = []
    for m in METHOD_RE.finditer(text):
        first = m.group(0).splitlines()[0]
        if ' publishInput(Ljava/io/InputStream;)V' in first:
            methods.append(m)
    if len(methods) != 1:
        raise RuntimeError(f'StreamOverHttp.HttpSession.publishInput missing/ambiguous: {len(methods)}')

    for field in ('supersedableMediaRequest:Z', 'partialResponse:Z', 'length:J',
                  'requestedStart:J', 'requestedEnd:J'):
        if field not in text:
            raise RuntimeError(f'StreamOverHttp.HttpSession field missing: {field}')

    m = methods[0]
    body = m.group(0)
    lines = body.splitlines()
    decl_idx = next((i for i, line in enumerate(lines)
                     if line.strip().startswith(('.locals ', '.registers '))), None)
    if decl_idx is None:
        raise RuntimeError('StreamOverHttp.HttpSession.publishInput register declaration missing')

    decl = lines[decl_idx].strip()
    if decl.startswith('.locals '):
        old_locals = int(decl.split()[1], 0)
        lines[decl_idx] = lines[decl_idx].replace(
            '.locals ' + decl.split()[1], '.locals ' + str(old_locals + 2), 1)
    else:
        old_regs = int(decl.split()[1], 0)
        old_locals = old_regs - 2
        if old_locals < 0:
            raise RuntimeError('Invalid publishInput register count')
        lines[decl_idx] = lines[decl_idx].replace(
            '.registers ' + decl.split()[1], '.registers ' + str(old_regs + 2), 1)

    uri_reg = f'v{old_locals}'
    bool_reg = f'v{old_locals + 1}'
    injection = [
        '',
        f'    iget-object {uri_reg}, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->this$0:Lcom/archos/filecorelibrary/StreamOverHttp;',
        '',
        f'    invoke-virtual {{{uri_reg}}}, Lcom/archos/filecorelibrary/StreamOverHttp;->getSourceUri()Landroid/net/Uri;',
        '',
        f'    move-result-object {uri_reg}',
        '',
        '    invoke-direct {p0}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->shouldUseNetworkReadAhead()Z',
        '',
        f'    move-result {bool_reg}',
        '',
        f'    invoke-static {{{uri_reg}, p1, {bool_reg}}}, {wrapper}',
        '',
        '    move-result-object p1',
    ]
    lines[decl_idx + 1:decl_idx + 1] = injection
    new_body = '\n'.join(lines)
    text = text[:m.start()] + new_body + text[m.end():]
    return text.rstrip() + '\n\n' + STREAM_SESSION_POLICY_SMALI + '\n', 'applied'


def _next_smali_dir(root: Path) -> Path:
    nums = [1]
    for p in root.glob('smali_classes*'):
        try:
            nums.append(int(p.name.removeprefix('smali_classes')))
        except ValueError:
            pass
    return root / f'smali_classes{max(nums) + 1}'



def _find_method(text: str, signature: str):
    hits = [m for m in METHOD_RE.finditer(text) if signature in m.group(0).splitlines()[0]]
    if len(hits) != 1:
        raise RuntimeError(f'{signature}: expected one method, got {len(hits)}')
    return hits[0]

def patch_player_text(text: str) -> tuple[str, str]:
    if ' bufferPauseCurrent()Z' in text:
        required = (
            '.field private static volatile sBufferPaused:Z',
            'NetworkReadAheadInputStream;->beforeNativeStart(Landroid/net/Uri;)Z',
            ' bufferResumeCurrent()V',
            ' bufferStartHeldCurrent()V',
            ' cancelBufferPause()V',
        )
        if all(x in text for x in required):
            return text, 'already-applied'
        raise RuntimeError('Partial hard-buffer Player patch found')

    field_anchor = '.field public static sPlayer:Lcom/archos/mediacenter/video/player/Player;\n'
    if text.count(field_anchor) != 1:
        raise RuntimeError('Player.sPlayer field missing/ambiguous')
    text = text.replace(field_anchor, field_anchor + '\n.field private static volatile sBufferPaused:Z\n', 1)

    # Manual pause disarms all automatic start/resume paths first.
    m = _find_method(text, ' pause(I)V')
    body = m.group(0)
    decl_end = body.find('\n', body.find('.locals '))
    injection = (
        '\n\n    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->cancelBufferPause()V'
        '\n    const/4 v0, 0x0'
        '\n    invoke-static {v0}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->setPlaybackActive(Z)V'
    )
    body = body[:decl_end] + injection + body[decl_end:]
    text = text[:m.start()] + body + text[m.end():]

    # Stop disarms before closing the current player/stream.
    m = _find_method(text, ' stopPlayback()V')
    body = m.group(0)
    decl_end = body.find('\n', body.find('.locals '))
    injection = (
        '\n\n    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->cancelBufferPause()V'
        '\n    const/4 v0, 0x0'
        '\n    invoke-static {v0}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->setPlaybackActive(Z)V'
    )
    body = body[:decl_end] + injection + body[decl_end:]
    text = text[:m.start()] + body + text[m.end():]

    # Gate only after prepare/metadata are ready, but before audio focus/nativeStart.
    m = _find_method(text, ' start(I)V')
    body = m.group(0)
    acquire_anchor = (
        '    :cond_2\n'
        '    invoke-direct {p0}, Lcom/archos/mediacenter/video/player/Player;->acquireFocus()Z'
    )
    if body.count(acquire_anchor) != 1:
        raise RuntimeError('Player.start acquireFocus anchor missing/ambiguous')
    gated = (
        '    :cond_2\n'
        '    iget-object v2, p0, Lcom/archos/mediacenter/video/player/Player;->mUri:Landroid/net/Uri;\n'
        '    invoke-static {v2}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->beforeNativeStart(Landroid/net/Uri;)Z\n'
        '    move-result v2\n'
        '    if-nez v2, :nova_buffer_start_safe\n'
        '    return-void\n\n'
        '    :nova_buffer_start_safe\n'
        '    invoke-direct {p0}, Lcom/archos/mediacenter/video/player/Player;->acquireFocus()Z'
    )
    body = body.replace(acquire_anchor, gated, 1)

    # If focus is not granted, this is not a buffer pause; disarm the buffer gate.
    focus_anchor = '    if-nez v2, :cond_4\n\n    invoke-interface {v3}, Lcom/archos/medialib/IMediaPlayer;->pause()V'
    if body.count(focus_anchor) != 1:
        raise RuntimeError('Player.start focus-failure anchor missing/ambiguous')
    body = body.replace(
        focus_anchor,
        '    if-nez v2, :cond_4\n\n'
        '    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->cancelBufferPause()V\n'
        '    invoke-static {v1}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->setPlaybackActive(Z)V\n\n'
        '    invoke-interface {v3}, Lcom/archos/medialib/IMediaPlayer;->pause()V',
        1)

    text = text[:m.start()] + body + text[m.end():]

    # Completion disarms any lingering guard.
    m = _find_method(text, ' onCompletion(Lcom/archos/medialib/IMediaPlayer;)V')
    body = m.group(0)
    completion_anchor = '    :cond_0\n    const/4 p1, 0x7'
    if body.count(completion_anchor) != 1:
        raise RuntimeError('Player.onCompletion anchor missing/ambiguous')
    body = body.replace(
        completion_anchor,
        '    :cond_0'
        '\n    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->cancelBufferPause()V'
        '\n    const/4 v0, 0x0'
        '\n    invoke-static {v0}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->setPlaybackActive(Z)V'
        '\n\n    const/4 p1, 0x7',
        1)
    text = text[:m.start()] + body + text[m.end():]

    return text.rstrip() + '\n\n' + PLAYER_BUFFER_METHODS_SMALI + '\n', 'applied'


def verify_roundtrip(expected: Path, actual: Path, report: Path, g):
    sa = g.resource_map(expected)
    sb = g.resource_map(actual)
    ia = g.class_index(expected)
    ib = g.class_index(actual)
    bad = []
    if ia.keys() != ib.keys():
        bad.append('class set differs')

    semantic = {
        'Lcom/archos/filecorelibrary/StreamOverHttp;',
        'Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;',
        'Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;',
        'Lcom/archos/filecorelibrary/NetworkReadAheadInputStream$Watchdog;',
        'Lcom/archos/mediacenter/video/player/Player;',
    }
    for name in ia.keys() & ib.keys():
        if name in semantic:
            continue
        a = ia[name].read_text()
        b = ib[name].read_text()
        if a != b:
            an = a.replace('const-string/jumbo', 'const-string')
            bn = b.replace('const-string/jumbo', 'const-string')
            if g.logical_class(an, sa) != g.logical_class(bn, sb):
                bad.append(name)

    aa = {p.relative_to(expected).as_posix() for p in expected.rglob('*.xml')
          if p.relative_to(expected).as_posix().startswith(('res/', 'AndroidManifest.xml'))}
    bb = {p.relative_to(actual).as_posix() for p in actual.rglob('*.xml')
          if p.relative_to(actual).as_posix().startswith(('res/', 'AndroidManifest.xml'))}
    if aa != bb:
        bad.append('XML resource set differs')
    for path in aa & bb:
        if (expected / path).read_bytes() != (actual / path).read_bytes():
            if g.logical_xml(g.ET.parse(expected / path).getroot()) != g.logical_xml(g.ET.parse(actual / path).getroot()):
                bad.append(path)

    for root, label in ((expected, 'expected'), (actual, 'roundtrip')):
        player = list(root.glob('smali*/com/archos/mediacenter/video/player/Player.smali'))
        if len(player) != 1:
            bad.append(label + ': Player missing/duplicate')
        else:
            pt = player[0].read_text()
            req = (
                '.field private static volatile sBufferPaused:Z',
                ' bufferPauseCurrent()Z',
                ' bufferResumeCurrent()V',
                ' cancelBufferPause()V',
                'IMediaPlayer;->pause()V',
                'IMediaPlayer;->start()V',
                'PLAYER_HARD_PAUSE nativePause=1 targetPlaying=1',
                'PLAYER_HARD_RESUME nativeStart=1 targetPlaying=1',
                'NetworkReadAheadInputStream;->beforeNativeStart(Landroid/net/Uri;)Z',
                ' bufferStartHeldCurrent()V',
            )
            for token in req:
                if token not in pt:
                    bad.append(label + ': Player hard-gate missing ' + token)
            pause_m = _find_method(pt, ' pause(I)V').group(0)
            stop_m = _find_method(pt, ' stopPlayback()V').group(0)
            start_m = _find_method(pt, ' start(I)V').group(0)
            if 'cancelBufferPause()V' not in pause_m or 'setPlaybackActive(Z)V' not in pause_m:
                bad.append(label + ': manual pause does not disarm auto-resume')
            if 'cancelBufferPause()V' not in stop_m or 'setPlaybackActive(Z)V' not in stop_m:
                bad.append(label + ': stop does not disarm auto-resume')
            gate = start_m.find('NetworkReadAheadInputStream;->beforeNativeStart(Landroid/net/Uri;)Z')
            focus = start_m.find('Player;->acquireFocus()Z')
            native_start = start_m.find('IMediaPlayer;->start()V')
            if not (0 <= gate < focus < native_start):
                bad.append(label + ': prepare-safe buffer gate is not before focus/nativeStart')
            if 'setPlaybackActive(Z)V' not in start_m:
                bad.append(label + ': focus-failure path does not disarm buffer gate')

        stream = list(root.glob('smali*/com/archos/filecorelibrary/StreamOverHttp.smali'))
        if len(stream) != 1 or stream[0].read_text().count(' getSourceUri()Landroid/net/Uri;') != 1:
            bad.append(label + ': StreamOverHttp source bridge invalid')

        session = list(root.glob('smali*/com/archos/filecorelibrary/StreamOverHttp$HttpSession.smali'))
        if len(session) != 1:
            bad.append(label + ': HttpSession missing/duplicate')
        else:
            ss = session[0].read_text()
            wrapper = ('Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->wrap'
                       '(Landroid/net/Uri;Ljava/io/InputStream;Z)Ljava/io/InputStream;')
            if ss.count(wrapper) != 1 or ss.count(' shouldUseNetworkReadAhead()Z') != 1:
                bad.append(label + ': WebDAV wrapper/policy invalid')
            for token in ('supersedableMediaRequest:Z', 'requestedStart:J', 'requestedEnd:J',
                          'length:J', 'const-wide/32 v2, 0x800000'):
                if token not in ss:
                    bad.append(label + ': bounded probes are not excluded by the long-media policy: ' + token)

        ra = list(root.glob('smali*/com/archos/filecorelibrary/NetworkReadAheadInputStream.smali'))
        if len(ra) != 1:
            bad.append(label + ': NetworkReadAheadInputStream missing/duplicate')
        else:
            rt = ra[0].read_text()
            required = (
                '.field private static final CAPACITY:I = 0x4000000',
                '.field private static final LOW_WATERMARK:I = 0x1800000',
                '.field private static final RESUME_WATERMARK:I = 0x2d00000',
                '.field private static volatile globalPlaybackActive:Z',
                '.field private volatile playbackActive:Z',
                '.field private volatile initialHold:Z',
                ' beforeNativeStart(Landroid/net/Uri;)Z',
                ' monitorLoop()V',
                'NetworkReadAheadInputStream$Watchdog;',
                'const v1, 0x4000000',
                'const v1, 0x1800000',
                'const v1, 0x2d00000',
                'Player;->bufferPauseCurrent()Z',
                'Player;->bufferResumeCurrent()V',
                'HARD_PAUSE before_floor_cross nativePause=1',
                'WATCHDOG_RESUME buffer>45MiB_or_clean_eof',
                'HARD_GATE_ON cap=64MiB low<24MiB resume>45MiB startup=prepare-pass watchdog=5ms',
                'INITIAL_HOLD prepared=1 wait_for_24MiB_floor',
                'NETWORK_FAILURE_HARD_PAUSE fail_closed',
                'WATCHDOG_HARD_PAUSE buffer<24MiB',
                'HARD_GATE_INIT_OOM fail_closed',
                'HARD_GATE_INIT_IO_FAIL fail_closed',
            )
            for token in required:
                if token not in rt:
                    bad.append(label + ': hard-buffer stream missing ' + token)
            ctor = _find_method(rt, ' constructor <init>(Ljava/io/InputStream;)V').group(0)
            if 'const/4 v0, 0x0' not in ctor or '->buffering:Z' not in ctor or 'NetworkReadAheadInputStream$Watchdog;' not in ctor:
                bad.append(label + ': prepare pass-through/watchdog constructor invariant missing')
            before = _find_method(rt, ' beforeNativeStart(Landroid/net/Uri;)Z').group(0)
            if 'const v3, 0x1840000' not in before or '->initialHold:Z' not in before:
                bad.append(label + ': initial start floor/hold invariant missing')
            if 'INITIAL_HOLD webdav_without_guarded_media_stream fail_closed' not in before:
                bad.append(label + ': WebDAV can start without an identified guarded media stream')
            available = _find_method(rt, ' available()I').group(0)
            if '->buffering:Z' in available:
                bad.append(label + ': available() still fakes zero during buffering')
            await_m = _find_method(rt, ' awaitBudget(I)V').group(0)
            low_i = await_m.find('const v1, 0x1800000')
            pause_i = await_m.find('Player;->bufferPauseCurrent()Z')
            resume_thr = await_m.find('const v1, 0x2d00000')
            resume_i = await_m.find('Player;->bufferResumeCurrent()V', resume_thr)
            if not (0 <= low_i < pause_i):
                bad.append(label + ': 24 MiB floor check is not before hard pause')
            if not (0 <= resume_thr < resume_i):
                bad.append(label + ': >45 MiB rebuffer threshold is not before hard resume')
            if 'add-int v2, v1, p1' not in await_m:
                bad.append(label + ': requested-read budget is not included in 24 MiB floor check')
            r1 = _find_method(rt, ' read()I').group(0)
            rb = _find_method(rt, ' read([BII)I').group(0)
            sk = _find_method(rt, ' skip(J)J').group(0)
            if 'declared-synchronized read()I' not in r1.splitlines()[0] or 'declared-synchronized read([BII)I' not in rb.splitlines()[0] or 'declared-synchronized skip(J)J' not in sk.splitlines()[0]:
                bad.append(label + ': consumer methods are not synchronized; floor check is not atomic')
            if 'const v0, 0x40000' not in rb or 'move p3, v0' not in rb or 'awaitBudget(I)V' not in rb:
                bad.append(label + ': bulk read is not capped/budgeted at 256 KiB')
            sk = _find_method(rt, ' skip(J)J').group(0)
            if 'const-wide/32 v0, 0x40000' not in sk or 'awaitBudget(I)V' not in sk:
                bad.append(label + ': skip is not capped/budgeted at 256 KiB')
            ctor = _find_method(rt, ' constructor <init>(Ljava/io/InputStream;)V').group(0)
            if 'HARD_GATE_REPLACE_OLD close_previous=1' not in ctor or '->close()V' not in ctor:
                bad.append(label + ': previous guarded stream is not fail-closed before replacement')
            if not re.search(r'\bif-ge v0, v2, :\S+', await_m):
                bad.append(label + ': pre-read 24 MiB floor branch invariant missing')
            if not re.search(r'\bif-le v0, v1, :\S+', await_m):
                bad.append(label + ': >45 MiB branch invariant missing')
            monitor = _find_method(rt, ' monitorLoop()V').group(0)
            if 'const-wide/32 v2, 0x4c4b40' not in monitor or 'WATCHDOG_HARD_PAUSE buffer<24MiB' not in monitor or 'WATCHDOG_RESUME buffer>45MiB_or_clean_eof' not in monitor:
                bad.append(label + ': 5ms watchdog pause/resume invariant missing')
            if 'NETWORK_FAILURE_HARD_PAUSE fail_closed' not in monitor:
                bad.append(label + ': network failure is not fail-closed in watchdog')
            if 'throw v4' not in await_m and 'throw v0' not in await_m:
                bad.append(label + ': failed stream does not propagate IOException while blocked')
            watchdog = list(root.glob('smali*/com/archos/filecorelibrary/NetworkReadAheadInputStream$Watchdog.smali'))
            if len(watchdog) != 1 or '->monitorLoop()V' not in watchdog[0].read_text():
                bad.append(label + ': watchdog helper missing/invalid')
            for forbidden in ('rebuffer=16/24/28MiB', 'BUFFER_LOW stage=', 'READ_AHEAD_OOM fallback'):
                if forbidden in rt:
                    bad.append(label + ': forbidden legacy behavior remains ' + forbidden)

    result = {
        'status': 'FAIL' if bad else 'PASS',
        'classes_compared': len(ia),
        'xml_files_compared': len(aa),
        'differences': sorted(bad),
        'comparison': 'strict roundtrip except intentional Player/WebDAV classes; explicit fail-closed hard pause/resume invariants',
        'runtime_tested': False,
    }
    g.write_json(report, result)
    if bad:
        raise g.Conflict('Hard-buffer logical verification failed: ' + str(bad[:30]))
    print(json.dumps(result, indent=2))
    return result

def apply(root: Path, report: Path | None = None):
    player = _one(root.glob('smali*/com/archos/mediacenter/video/player/Player.smali'), 'Player')
    player_text, player_status = patch_player_text(player.read_text())
    player.write_text(player_text)

    stream_http = _one(root.glob('smali*/com/archos/filecorelibrary/StreamOverHttp.smali'), 'StreamOverHttp')
    stream_http_text, stream_http_status = patch_stream_over_http_text(stream_http.read_text())
    stream_http.write_text(stream_http_text)

    stream_session = _one(root.glob('smali*/com/archos/filecorelibrary/StreamOverHttp$HttpSession.smali'), 'StreamOverHttp.HttpSession')
    stream_session_text, stream_session_status = patch_stream_http_session_text(stream_session.read_text())
    stream_session.write_text(stream_session_text)

    hits = list(root.glob('smali*/com/archos/filecorelibrary/NetworkReadAheadInputStream.smali'))
    if hits:
        if len(hits) != 1 or hits[0].read_text() != READ_AHEAD_SMALI:
            raise RuntimeError('NetworkReadAheadInputStream class conflict')
        read_ahead_path = hits[0]
        read_ahead_status = 'already-applied'
    else:
        smali_dir = _next_smali_dir(root)
        read_ahead_path = smali_dir / 'com/archos/filecorelibrary/NetworkReadAheadInputStream.smali'
        read_ahead_path.parent.mkdir(parents=True, exist_ok=True)
        read_ahead_path.write_text(READ_AHEAD_SMALI)
        read_ahead_status = 'applied'

    watchdog_path = read_ahead_path.parent / 'NetworkReadAheadInputStream$Watchdog.smali'
    if watchdog_path.exists():
        if watchdog_path.read_text() != WATCHDOG_SMALI:
            raise RuntimeError('NetworkReadAheadInputStream.Watchdog class conflict')
        watchdog_status = 'already-applied'
    else:
        watchdog_path.write_text(WATCHDOG_SMALI)
        watchdog_status = 'applied'

    result = {
        'status': 'PASS',
        'player_hard_gate': player_status,
        'stream_over_http_source_uri': stream_http_status,
        'stream_over_http_readahead': stream_session_status,
        'network_readahead': read_ahead_status,
        'watchdog': watchdog_status,
        'network_readahead_path': read_ahead_path.relative_to(root).as_posix(),
        'watchdog_path': watchdog_path.relative_to(root).as_posix(),
        'capacity_mib': 64,
        'low_watermark_strictly_below_mib': 24,
        'resume_strictly_above_mib': 45,
        'startup_policy': 'probe/prepare pass-through; before nativeStart require ~24 MiB floor or clean EOF; held start is released by watchdog',
        'failure_policy': 'fail closed on initialization or network read failure; never resume a failed stream from residual bytes',
        'strategy': '5ms watchdog + atomic read budget; start floor ~24 MiB after prepare; hard Player/AVOS pause before floor crossing; resume only above 45 MiB; 64 MiB producer cap',
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + '\n')
    return result

