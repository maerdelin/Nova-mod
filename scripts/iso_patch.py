#!/usr/bin/env python3
"""Inject Blu-ray ISO support without replacing Nova's existing classes or native libraries."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil

MIME_OLD = '"application/x-iso9660-image"'
MIME_NEW = '"video/x-bluray-iso"'
METHOD_RE = re.compile(r'^\.method [^\n]+\n.*?^\.end method', re.M | re.S)
AWAIT_RE = re.compile(
    r'^(?P<indent>\s*)invoke-static(?:/range)? \{(?P<regs>[^}]+)\}, '
    r'Lcom/archos/filecorelibrary/NetworkInitialization;->awaitReadyForSmb'
    r'\(Landroid/net/Uri;Landroid/content/Context;\)V\s*$',
    re.M,
)

PROXY_SMALI = r'''.class public final Lcom/archos/mediacenter/video/player/BlurayIsoProxy;
.super Ljava/lang/Object;
.source "BlurayIsoProxy.java"

.field private static sInput:Lcom/archos/filecorelibrary/StreamOverHttp;
.field private static sForceAvos:Z
.field private static sSkipInitialZeroSeek:Z

.method static constructor <clinit>()V
    .locals 1

    const-string v0, "nova_iso"

    invoke-static {v0}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V

    return-void
.end method

.method private constructor <init>()V
    .locals 0

    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    return-void
.end method

.method public static armForUri(Landroid/net/Uri;)V
    .locals 3

    const/4 v0, 0x0

    if-eqz p0, :store

    invoke-virtual {p0}, Landroid/net/Uri;->getPath()Ljava/lang/String;

    move-result-object v1

    if-eqz v1, :store

    sget-object v2, Ljava/util/Locale;->ROOT:Ljava/util/Locale;

    invoke-virtual {v1, v2}, Ljava/lang/String;->toLowerCase(Ljava/util/Locale;)Ljava/lang/String;

    move-result-object v1

    const-string v2, ".iso"

    invoke-virtual {v1, v2}, Ljava/lang/String;->endsWith(Ljava/lang/String;)Z

    move-result v0

    :store
    sput-boolean v0, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->sForceAvos:Z
    sput-boolean v0, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->sSkipInitialZeroSeek:Z

    if-eqz v0, :done

    const-string v1, "NovaIso"

    const-string v2, "PLAYER_ARM iso=1"

    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    :done
    return-void
.end method

.method public static shouldForceAvos()Z
    .locals 1

    sget-boolean v0, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->sForceAvos:Z

    return v0
.end method

.method public static shouldSkipInitialZeroSeek(I)Z
    .locals 1

    sget-boolean v0, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->sForceAvos:Z

    if-eqz v0, :no

    sget-boolean v0, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->sSkipInitialZeroSeek:Z

    if-eqz v0, :no

    const/4 v0, 0x0

    sput-boolean v0, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->sSkipInitialZeroSeek:Z

    if-nez p0, :no

    const/4 v0, 0x1

    return v0

    :no
    const/4 v0, 0x0

    return v0
.end method

.method private static closeLocked()V
    .locals 1

    sget-object v0, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->sInput:Lcom/archos/filecorelibrary/StreamOverHttp;

    if-eqz v0, :native_close

    invoke-virtual {v0}, Lcom/archos/filecorelibrary/StreamOverHttp;->close()V

    const/4 v0, 0x0

    sput-object v0, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->sInput:Lcom/archos/filecorelibrary/StreamOverHttp;

    :native_close
    invoke-static {}, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->nativeClose()V

    return-void
.end method

.method public static declared-synchronized close()V
    .locals 0

    invoke-static {}, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->closeLocked()V

    return-void
.end method

.method private static native nativeClose()V
.end method

.method private static native nativeOpen(Ljava/lang/String;)Ljava/lang/String;
.end method

.method public static declared-synchronized resolve(Landroid/net/Uri;)Landroid/net/Uri;
    .locals 5

    if-eqz p0, :return_original

    invoke-virtual {p0}, Landroid/net/Uri;->getPath()Ljava/lang/String;

    move-result-object v0

    if-eqz v0, :not_iso

    sget-object v1, Ljava/util/Locale;->ROOT:Ljava/util/Locale;

    invoke-virtual {v0, v1}, Ljava/lang/String;->toLowerCase(Ljava/util/Locale;)Ljava/lang/String;

    move-result-object v0

    const-string v1, ".iso"

    invoke-virtual {v0, v1}, Ljava/lang/String;->endsWith(Ljava/lang/String;)Z

    move-result v0

    if-eqz v0, :not_iso

    invoke-static {}, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->closeLocked()V

    new-instance v0, Lcom/archos/filecorelibrary/StreamOverHttp;

    const-string v1, "application/octet-stream"

    sget-object v2, Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;->PLAYBACK:Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;

    invoke-direct {v0, p0, v1, v2}, Lcom/archos/filecorelibrary/StreamOverHttp;-><init>(Landroid/net/Uri;Ljava/lang/String;Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;)V

    sput-object v0, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->sInput:Lcom/archos/filecorelibrary/StreamOverHttp;

    invoke-static {p0}, Lcom/archos/filecorelibrary/FileUtils;->getName(Landroid/net/Uri;)Ljava/lang/String;

    move-result-object v1

    invoke-virtual {v0, v1}, Lcom/archos/filecorelibrary/StreamOverHttp;->getEncodedUri(Ljava/lang/String;)Landroid/net/Uri;

    move-result-object v1

    invoke-virtual {v1}, Landroid/net/Uri;->toString()Ljava/lang/String;

    move-result-object v1

    invoke-static {v1}, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->nativeOpen(Ljava/lang/String;)Ljava/lang/String;

    move-result-object v2

    if-nez v2, :opened

    invoke-static {}, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->closeLocked()V

    new-instance v3, Ljava/lang/RuntimeException;

    const-string v4, "Unable to open Blu-ray ISO"

    invoke-direct {v3, v4}, Ljava/lang/RuntimeException;-><init>(Ljava/lang/String;)V

    throw v3

    :opened
    const-string v3, "NovaIso"

    invoke-static {v3, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    invoke-static {v2}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;

    move-result-object p0

    return-object p0

    :not_iso
    invoke-static {}, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->closeLocked()V

    :return_original
    return-object p0
.end method
'''

def _one(paths, label):
    paths = list(paths)
    if len(paths) != 1:
        raise RuntimeError(f'{label}: expected one target, got {len(paths)}: {paths}')
    return paths[0]

def patch_player_text(text: str) -> tuple[str, str]:
    if 'BlurayIsoProxy;->resolve' in text:
        return text, 'already-applied'
    candidates = []
    for m in METHOD_RE.finditer(text):
        body = m.group(0)
        if ('NetworkInitialization;->awaitReadyForSmb' in body and
                'IMediaPlayer;->setDataSource' in body):
            candidates.append(m)
    if len(candidates) != 1:
        raise RuntimeError(f'Player source method missing/ambiguous: {len(candidates)}')
    m = candidates[0]
    body = m.group(0)
    a = AWAIT_RE.search(body)
    if not a:
        raise RuntimeError('awaitReadyForSmb invocation shape changed')
    regs = a.group('regs').strip()
    uri_reg = regs.split('..', 1)[0].split(',', 1)[0].strip()
    if not re.fullmatch(r'[vp]\d+', uri_reg):
        raise RuntimeError('Unable to identify URI register: ' + uri_reg)
    indent = a.group('indent')
    injected = (
        a.group(0) + '\n\n' +
        indent + f'invoke-static {{{uri_reg}}}, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->resolve(Landroid/net/Uri;)Landroid/net/Uri;\n' +
        indent + f'move-result-object {uri_reg}'
    )
    new_body = body[:a.start()] + injected + body[a.end():]
    return text[:m.start()] + new_body + text[m.end():], m.group(0).splitlines()[0]

ISO_FACTORY_SMALI = r'''.class public final Lcom/archos/mediacenter/video/player/IsoPlayerFactory;
.super Ljava/lang/Object;
.source "IsoPlayerFactory.java"

.method private constructor <init>()V
    .locals 0

    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    return-void
.end method

.method public static create(Landroid/content/Context;Z)Lcom/archos/medialib/IMediaPlayer;
    .locals 3

    invoke-static {}, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->shouldForceAvos()Z

    move-result v0

    if-eqz v0, :normal

    const/4 v0, 0x1

    invoke-static {p0, v0}, Lcom/archos/medialib/MediaFactory;->createPlayer(Landroid/content/Context;Z)Lcom/archos/medialib/IMediaPlayer;

    move-result-object v0

    instance-of v1, v0, Lcom/archos/medialib/AvosMediaPlayer;

    if-eqz v1, :fallback

    if-nez p1, :log_forced

    const/4 v1, 0x0

    invoke-static {v1}, Lcom/archos/medialib/LibAvos;->setDecoder(I)V

    :log_forced
    const-string v1, "NovaIso"

    const-string v2, "PLAYER_FACTORY avos=1 forced=1"

    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    return-object v0

    :fallback
    const-string v1, "NovaIso"

    const-string v2, "PLAYER_FACTORY avos_unavailable=1 fallback_android=1"

    invoke-static {v1, v2}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I

    return-object v0

    :normal
    invoke-static {p0, p1}, Lcom/archos/medialib/MediaFactory;->createPlayer(Landroid/content/Context;Z)Lcom/archos/medialib/IMediaPlayer;

    move-result-object v0

    return-object v0
.end method
.method public static seekTo(Lcom/archos/mediacenter/video/player/Player;I)V
    .locals 3

    invoke-static {p1}, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->shouldSkipInitialZeroSeek(I)Z

    move-result v0

    if-eqz v0, :normal_seek

    const-string v1, "NovaIso"

    const-string v2, "SEEK_ZERO_SKIP iso=1"

    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    return-void

    :normal_seek
    invoke-virtual {p0, p1}, Lcom/archos/mediacenter/video/player/Player;->seekTo(I)V

    return-void
.end method
'''

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

.field private static final CAPACITY:I = 0x2000000
.field private static final CHUNK:I = 0x40000
.field private static final LOW_WATERMARK:I = 0x200000
.field private static final START_WATERMARK:I = 0x800000
.field private static final TAG:Ljava/lang/String; = "NovaNetBuf"

.field private volatile buffering:Z
.field private volatile closed:Z
.field private volatile eof:Z
.field private volatile failure:Ljava/io/IOException;
.field private final pipeIn:Ljava/io/PipedInputStream;
.field private final pipeOut:Ljava/io/PipedOutputStream;
.field private final source:Ljava/io/InputStream;
.field private stage:I
.field private target:I

.method private constructor <init>(Ljava/io/InputStream;)V
    .locals 5

    invoke-direct {p0}, Ljava/io/InputStream;-><init>()V

    iput-object p1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->source:Ljava/io/InputStream;

    const/4 v0, 0x1
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    const v0, 0x800000
    iput v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->target:I

    new-instance v0, Ljava/io/PipedInputStream;
    const v1, 0x2000000
    invoke-direct {v0, v1}, Ljava/io/PipedInputStream;-><init>(I)V
    iput-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;

    new-instance v1, Ljava/io/PipedOutputStream;
    invoke-direct {v1, v0}, Ljava/io/PipedOutputStream;-><init>(Ljava/io/PipedInputStream;)V
    iput-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeOut:Ljava/io/PipedOutputStream;

    new-instance v2, Ljava/lang/Thread;
    const-string v3, "Nova WebDAV read-ahead"
    invoke-direct {v2, p0, v3}, Ljava/lang/Thread;-><init>(Ljava/lang/Runnable;Ljava/lang/String;)V
    const/4 v4, 0x1
    invoke-virtual {v2, v4}, Ljava/lang/Thread;->setDaemon(Z)V
    invoke-virtual {v2}, Ljava/lang/Thread;->start()V

    return-void
.end method

.method public static wrap(Landroid/net/Uri;Ljava/io/InputStream;Z)Ljava/io/InputStream;
    .locals 5

    if-eqz p1, :return_original
    if-eqz p2, :return_original
    if-eqz p0, :return_original

    invoke-virtual {p0}, Landroid/net/Uri;->getScheme()Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :return_original

    const-string v1, "webdav"
    invoke-virtual {v1, v0}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-nez v2, :wrap_stream

    const-string v1, "webdavs"
    invoke-virtual {v1, v0}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-eqz v2, :return_original

    :wrap_stream
    :try_start_0
    new-instance v2, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
    invoke-direct {v2, p1}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;-><init>(Ljava/io/InputStream;)V

    const-string v3, "NovaNetBuf"
    const-string v4, "READ_AHEAD_ON webdav cap=32MiB low=2MiB start=8MiB rebuffer=16/24/28MiB"
    invoke-static {v3, v4}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    return-object v2
    :try_end_0
    .catch Ljava/io/IOException; {:try_start_0 .. :try_end_0} :catch_io
    .catch Ljava/lang/OutOfMemoryError; {:try_start_0 .. :try_end_0} :catch_oom

    :catch_io
    move-exception v2
    const-string v3, "NovaNetBuf"
    const-string v4, "READ_AHEAD_INIT_FAIL fallback"
    invoke-static {v3, v4, v2}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I
    return-object p1

    :catch_oom
    move-exception v2
    const-string v3, "NovaNetBuf"
    const-string v4, "READ_AHEAD_OOM fallback"
    invoke-static {v3, v4, v2}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I

    :return_original
    return-object p1
.end method

.method private awaitReady()V
    .locals 5

    :loop
    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    if-nez v0, :return

    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->available()I
    move-result v0

    iget-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    if-nez v1, :waiting

    const v1, 0x200000
    if-gt v0, v1, :return

    const/4 v1, 0x1
    iput-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    iget v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->stage:I
    add-int/lit8 v1, v1, 0x1
    const/4 v2, 0x3
    if-le v1, v2, :stage_ok
    move v1, v2

    :stage_ok
    iput v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->stage:I

    const/4 v2, 0x1
    if-ne v1, v2, :stage_two
    const v2, 0x1000000
    const-string v3, "BUFFER_LOW stage=1 target=16MiB"
    goto :set_target

    :stage_two
    const/4 v2, 0x2
    if-ne v1, v2, :stage_three
    const v2, 0x1800000
    const-string v3, "BUFFER_LOW stage=2 target=24MiB"
    goto :set_target

    :stage_three
    const v2, 0x1c00000
    const-string v3, "BUFFER_LOW stage=3 target=28MiB"

    :set_target
    iput v2, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->target:I
    const-string v4, "NovaNetBuf"
    invoke-static {v4, v3}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    :waiting
    iget-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z
    if-nez v1, :return

    iget v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->target:I
    if-lt v0, v1, :wait_more

    const/4 v1, 0x0
    iput-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    const-string v1, "NovaNetBuf"
    const-string v2, "BUFFER_READY"
    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    return-void

    :wait_more
    const-wide/32 v1, 0x989680
    invoke-static {v1, v2}, Ljava/util/concurrent/locks/LockSupport;->parkNanos(J)V
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

.method public read()I
    .locals 2

    invoke-direct {p0}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->awaitReady()V

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

.method public read([BII)I
    .locals 2

    invoke-direct {p0}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->awaitReady()V

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
    .locals 2

    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    if-eqz v0, :actual
    const/4 v0, 0x0
    return v0

    :actual
    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->available()I
    move-result v0
    return v0
.end method

.method public skip(J)J
    .locals 2

    invoke-direct {p0}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->awaitReady()V

    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0, p1, p2}, Ljava/io/PipedInputStream;->skip(J)J
    move-result-wide v0
    return-wide v0
.end method

.method public close()V
    .locals 2

    const/4 v0, 0x1
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z

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

STREAM_SESSION_POLICY_SMALI = r'''.method private shouldUseNetworkReadAhead()Z
    .locals 5

    iget-boolean v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->supersedableMediaRequest:Z
    if-eqz v0, :no

    iget-boolean v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->partialResponse:Z
    if-eqz v0, :yes

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

    for field in ('supersedableMediaRequest:Z', 'partialResponse:Z',
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


def patch_initial_zero_seek_player_service_text(text: str) -> tuple[str, str]:
    wrapper = (
        'Lcom/archos/mediacenter/video/player/IsoPlayerFactory;->seekTo'
        '(Lcom/archos/mediacenter/video/player/Player;I)V'
    )
    if wrapper in text:
        return text, 'already-applied'

    methods = []
    for m in METHOD_RE.finditer(text):
        first = m.group(0).splitlines()[0]
        if ' postPreparedAndVideoDb()V' in first:
            methods.append(m)
    if len(methods) != 1:
        raise RuntimeError(f'PlayerService.postPreparedAndVideoDb missing/ambiguous: {len(methods)}')

    m = methods[0]
    body = m.group(0)
    call_re = re.compile(
        r'(?P<indent>\s*)(?P<op>invoke-virtual(?:/range)?) '
        r'\{(?P<regs>[^}]+)\}, '
        r'Lcom/archos/mediacenter/video/player/Player;->seekTo\(I\)V'
    )
    hits = list(call_re.finditer(body))
    if len(hits) != 1:
        raise RuntimeError(f'PlayerService initial seek call missing/ambiguous: {len(hits)}')

    c = hits[0]
    static_op = 'invoke-static/range' if c.group('op').endswith('/range') else 'invoke-static'
    replacement = (
        c.group('indent') + static_op + ' {' + c.group('regs') + '}, ' + wrapper
    )
    new_body = body[:c.start()] + replacement + body[c.end():]
    return text[:m.start()] + new_body + text[m.end():], 'applied'


def patch_force_avos_player_text(text: str) -> tuple[str, str]:
    arm_sig = 'BlurayIsoProxy;->armForUri(Landroid/net/Uri;)V'
    factory_old = (
        'Lcom/archos/medialib/MediaFactory;->createPlayer'
        '(Landroid/content/Context;Z)Lcom/archos/medialib/IMediaPlayer;'
    )
    factory_new = (
        'Lcom/archos/mediacenter/video/player/IsoPlayerFactory;->create'
        '(Landroid/content/Context;Z)Lcom/archos/medialib/IMediaPlayer;'
    )

    methods = [m for m in METHOD_RE.finditer(text)
               if m.group(0).splitlines()[0].startswith(
                   '.method public setVideoURI(Landroid/net/Uri;Ljava/util/Map;)V')]
    if len(methods) != 1:
        raise RuntimeError(f'Player.setVideoURI missing/ambiguous: {len(methods)}')
    m = methods[0]
    body = m.group(0)
    if arm_sig not in body:
        lines = body.splitlines()
        reg_idx = next((i for i, line in enumerate(lines)
                        if line.strip().startswith(('.locals ', '.registers '))), None)
        if reg_idx is None:
            raise RuntimeError('Player.setVideoURI register declaration missing')
        lines[reg_idx + 1:reg_idx + 1] = [
            '',
            '    invoke-static {p1}, Lcom/archos/mediacenter/video/player/BlurayIsoProxy;->armForUri(Landroid/net/Uri;)V',
        ]
        new_body = '\n'.join(lines)
        text = text[:m.start()] + new_body + text[m.end():]

    old_count = text.count(factory_old)
    new_count = text.count(factory_new)
    if old_count == 1 and new_count == 0:
        text = text.replace(factory_old, factory_new, 1)
        return text, 'applied'
    if old_count == 0 and new_count == 1:
        return text, 'already-applied'
    raise RuntimeError(f'Player factory replacement conflict old={old_count} new={new_count}')


def _next_smali_dir(root: Path) -> Path:
    nums = [1]
    for p in root.glob('smali_classes*'):
        try:
            nums.append(int(p.name.removeprefix('smali_classes')))
        except ValueError:
            pass
    return root / f'smali_classes{max(nums) + 1}'

def apply(root: Path, native_dir: Path, report: Path | None = None):
    mime = _one(root.glob('smali*/com/archos/filecorelibrary/MimeUtils.smali'), 'MimeUtils')
    mime_text = mime.read_text()
    old_count = mime_text.count(MIME_OLD)
    new_count = mime_text.count(MIME_NEW)
    if old_count == 1:
        mime.write_text(mime_text.replace(MIME_OLD, MIME_NEW, 1))
        mime_status = 'applied'
    elif old_count == 0 and new_count == 1:
        mime_status = 'already-applied'
    else:
        raise RuntimeError(f'ISO MIME mapping conflict old={old_count} new={new_count}')

    player = _one(root.glob('smali*/com/archos/mediacenter/video/player/Player.smali'), 'Player')
    patched, player_status = patch_player_text(player.read_text())
    patched, player_factory_status = patch_force_avos_player_text(patched)
    player.write_text(patched)

    player_service = _one(root.glob('smali*/com/archos/mediacenter/video/player/PlayerService.smali'), 'PlayerService')
    player_service_text, player_service_status = patch_initial_zero_seek_player_service_text(player_service.read_text())
    player_service.write_text(player_service_text)

    stream_http = _one(root.glob('smali*/com/archos/filecorelibrary/StreamOverHttp.smali'), 'StreamOverHttp')
    stream_http_text, stream_http_status = patch_stream_over_http_text(stream_http.read_text())
    stream_http.write_text(stream_http_text)

    stream_session = _one(root.glob('smali*/com/archos/filecorelibrary/StreamOverHttp$HttpSession.smali'), 'StreamOverHttp.HttpSession')
    stream_session_text, stream_session_status = patch_stream_http_session_text(stream_session.read_text())
    stream_session.write_text(stream_session_text)

    proxy_hits = list(root.glob('smali*/com/archos/mediacenter/video/player/BlurayIsoProxy.smali'))
    if proxy_hits:
        if len(proxy_hits) != 1 or proxy_hits[0].read_text() != PROXY_SMALI:
            raise RuntimeError('BlurayIsoProxy class conflict')
        proxy_path = proxy_hits[0]
        proxy_status = 'already-applied'
    else:
        smali_dir = _next_smali_dir(root)
        proxy_path = smali_dir / 'com/archos/mediacenter/video/player/BlurayIsoProxy.smali'
        proxy_path.parent.mkdir(parents=True, exist_ok=True)
        proxy_path.write_text(PROXY_SMALI)
        proxy_status = 'applied'

    iso_factory_hits = list(root.glob('smali*/com/archos/mediacenter/video/player/IsoPlayerFactory.smali'))
    if iso_factory_hits:
        if len(iso_factory_hits) != 1 or iso_factory_hits[0].read_text() != ISO_FACTORY_SMALI:
            raise RuntimeError('IsoPlayerFactory class conflict')
        iso_factory_path = iso_factory_hits[0]
        iso_factory_status = 'already-applied'
    else:
        iso_factory_path = proxy_path.parent / 'IsoPlayerFactory.smali'
        iso_factory_path.write_text(ISO_FACTORY_SMALI)
        iso_factory_status = 'applied'

    read_ahead_hits = list(root.glob('smali*/com/archos/filecorelibrary/NetworkReadAheadInputStream.smali'))
    if read_ahead_hits:
        if len(read_ahead_hits) != 1 or read_ahead_hits[0].read_text() != READ_AHEAD_SMALI:
            raise RuntimeError('NetworkReadAheadInputStream class conflict')
        read_ahead_path = read_ahead_hits[0]
        read_ahead_status = 'already-applied'
    else:
        read_ahead_path = proxy_path.parents[4] / 'archos/filecorelibrary/NetworkReadAheadInputStream.smali'
        read_ahead_path.parent.mkdir(parents=True, exist_ok=True)
        read_ahead_path.write_text(READ_AHEAD_SMALI)
        read_ahead_status = 'applied'

    copied = []
    expected_abis = ('arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64')
    for abi in expected_abis:
        src = native_dir / abi / 'libnova_iso.so'
        if not src.is_file() or src.stat().st_size < 10000:
            raise RuntimeError('Missing/invalid native ISO bridge for ' + abi)
        dst = root / 'lib' / abi / 'libnova_iso.so'
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        copied.append({'abi': abi, 'size': dst.stat().st_size})

    result = {
        'status': 'PASS',
        'mime': mime_status,
        'player': player_status,
        'player_factory': player_factory_status,
        'player_service_initial_zero_seek': player_service_status,
        'stream_over_http_source_uri': stream_http_status,
        'stream_over_http_readahead': stream_session_status,
        'network_readahead': read_ahead_status,
        'proxy': proxy_status,
        'iso_player_factory': iso_factory_status,
        'proxy_path': proxy_path.relative_to(root).as_posix(),
        'iso_player_factory_path': iso_factory_path.relative_to(root).as_posix(),
        'network_readahead_path': read_ahead_path.relative_to(root).as_posix(),
        'native': copied,
        'strategy': 'Kodi-inspired WebDAV background read-ahead + persistent ISO playback Range stream; stock Nova Avos native stack preserved',
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + '\n')
    return result
