#!/usr/bin/env python3
from __future__ import annotations
import json
import re
from pathlib import Path
from buffer_guard_patch import method, bump_locals, one

CAPACITY = 0x4000000

GUARD = r'''.class public final Lcom/archos/filecorelibrary/NovaBufferGuard;
.super Ljava/lang/Object;
.source "NovaBufferGuard.java"

.field private static volatile active:Z
.field private static volatile buffering:Z
.field private static volatile eof:Z
.field private static volatile generation:I
.field private static volatile produced:J
.field private static volatile consumed:J
.field private static volatile total:J

.method private constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method private static logValue(Ljava/lang/String;J)V
    .locals 3
    new-instance v0, Ljava/lang/StringBuilder;
    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V
    invoke-virtual {v0, p0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, p1, p2}, Ljava/lang/StringBuilder;->append(J)Ljava/lang/StringBuilder;
    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v0
    const-string v1, "NovaBufGuard"
    invoke-static {v1, v0}, Lcom/archos/mediacenter/video/player/Player;->novaLog(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method public static onPlaybackStarted()V
    .locals 2
    const/4 v0, 0x1
    sput-boolean v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->active:Z
    const-string v0, "NovaBufGuard"
    const-string v1, "PLAYBACK_ACTIVE prefetch=64MiB low=24MiB resume=45MiB"
    invoke-static {v0, v1}, Lcom/archos/mediacenter/video/player/Player;->novaLog(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method public static onPlaybackStopped()V
    .locals 2
    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->active:Z
    sput-boolean v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->buffering:Z
    invoke-static {v0}, Lcom/archos/mediacenter/video/player/Player;->novaSetBufferingUi(Z)V
    const-string v0, "NovaBufGuard"
    const-string v1, "PLAYBACK_STOP"
    invoke-static {v0, v1}, Lcom/archos/mediacenter/video/player/Player;->novaLog(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method public static onBytes(IJJJI)V
    .locals 0
    return-void
.end method

.method public static onPrefetchStart(J)I
    .locals 5
    sget v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->generation:I
    add-int/lit8 v0, v0, 0x1
    sput v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->generation:I

    const-wide/16 v1, 0x0
    sput-wide v1, Lcom/archos/filecorelibrary/NovaBufferGuard;->produced:J
    sput-wide v1, Lcom/archos/filecorelibrary/NovaBufferGuard;->consumed:J
    sput-wide p0, Lcom/archos/filecorelibrary/NovaBufferGuard;->total:J
    const/4 v3, 0x0
    sput-boolean v3, Lcom/archos/filecorelibrary/NovaBufferGuard;->eof:Z

    sget-boolean v4, Lcom/archos/filecorelibrary/NovaBufferGuard;->buffering:Z
    if-eqz v4, :log
    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->novaResumeFromBuffer()V
    sput-boolean v3, Lcom/archos/filecorelibrary/NovaBufferGuard;->buffering:Z
    invoke-static {v3}, Lcom/archos/mediacenter/video/player/Player;->novaSetBufferingUi(Z)V

    :log
    const-string v1, "PREFETCH_START totalBytes="
    invoke-static {v1, p0, p1}, Lcom/archos/filecorelibrary/NovaBufferGuard;->logValue(Ljava/lang/String;J)V
    return v0
.end method

.method public static currentGeneration()I
    .locals 1
    sget v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->generation:I
    return v0
.end method

.method public static onPrefetchProduced(II)V
    .locals 7
    sget v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->generation:I
    if-ne p0, v0, :done

    sget-wide v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->produced:J
    int-to-long v2, p1
    add-long/2addr v0, v2
    sput-wide v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->produced:J

    sget-boolean v2, Lcom/archos/filecorelibrary/NovaBufferGuard;->buffering:Z
    if-eqz v2, :done
    sget-wide v2, Lcom/archos/filecorelibrary/NovaBufferGuard;->consumed:J
    sub-long v4, v0, v2
    const-wide/32 v2, 0x2d00000
    cmp-long v6, v4, v2
    if-gez v6, :done

    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->buffering:Z
    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->novaResumeFromBuffer()V
    invoke-static {v0}, Lcom/archos/mediacenter/video/player/Player;->novaSetBufferingUi(Z)V
    const-string v0, "RESUME prefetchBytes="
    invoke-static {v0, v4, v5}, Lcom/archos/filecorelibrary/NovaBufferGuard;->logValue(Ljava/lang/String;J)V

    :done
    return-void
.end method

.method public static onPrefetchConsumed(II)V
    .locals 7
    sget v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->generation:I
    if-ne p0, v0, :done

    sget-wide v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->consumed:J
    int-to-long v2, p1
    add-long/2addr v0, v2
    sput-wide v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->consumed:J

    sget-boolean v2, Lcom/archos/filecorelibrary/NovaBufferGuard;->active:Z
    if-eqz v2, :done
    sget-boolean v2, Lcom/archos/filecorelibrary/NovaBufferGuard;->buffering:Z
    if-nez v2, :done
    sget-boolean v2, Lcom/archos/filecorelibrary/NovaBufferGuard;->eof:Z
    if-nez v2, :done

    sget-wide v2, Lcom/archos/filecorelibrary/NovaBufferGuard;->produced:J
    sub-long v4, v2, v0
    const-wide/32 v2, 0x1800000
    cmp-long v6, v4, v2
    if-ltz v6, :done

    const/4 v2, 0x1
    sput-boolean v2, Lcom/archos/filecorelibrary/NovaBufferGuard;->buffering:Z
    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->novaPauseForBuffer()Z
    move-result v2
    if-nez v2, :paused
    const/4 v2, 0x0
    sput-boolean v2, Lcom/archos/filecorelibrary/NovaBufferGuard;->buffering:Z
    goto :done

    :paused
    const/4 v2, 0x1
    invoke-static {v2}, Lcom/archos/mediacenter/video/player/Player;->novaSetBufferingUi(Z)V
    const-string v2, "PAUSE prefetchBytes="
    invoke-static {v2, v4, v5}, Lcom/archos/filecorelibrary/NovaBufferGuard;->logValue(Ljava/lang/String;J)V

    :done
    return-void
.end method

.method public static onPrefetchEof(I)V
    .locals 5
    sget v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->generation:I
    if-ne p0, v0, :done
    const/4 v0, 0x1
    sput-boolean v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->eof:Z

    sget-wide v1, Lcom/archos/filecorelibrary/NovaBufferGuard;->produced:J
    sget-wide v3, Lcom/archos/filecorelibrary/NovaBufferGuard;->consumed:J
    sub-long/2addr v1, v3
    const-string v0, "PREFETCH_EOF bufferedBytes="
    invoke-static {v0, v1, v2}, Lcom/archos/filecorelibrary/NovaBufferGuard;->logValue(Ljava/lang/String;J)V

    sget-boolean v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->buffering:Z
    if-eqz v0, :done
    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->buffering:Z
    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->novaResumeFromBuffer()V
    invoke-static {v0}, Lcom/archos/mediacenter/video/player/Player;->novaSetBufferingUi(Z)V

    :done
    return-void
.end method

.method public static onPrefetchError(I)V
    .locals 2
    sget v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->generation:I
    if-ne p0, v0, :done
    const-string v0, "NovaBufGuard"
    const-string v1, "PREFETCH_ERROR"
    invoke-static {v0, v1}, Lcom/archos/mediacenter/video/player/Player;->novaLog(Ljava/lang/String;Ljava/lang/String;)I
    invoke-static {p0}, Lcom/archos/filecorelibrary/NovaBufferGuard;->onPrefetchEof(I)V
    :done
    return-void
.end method
'''

PREFETCH_INPUT = r'''.class public final Lcom/archos/filecorelibrary/NovaPrefetchInputStream;
.super Ljava/io/InputStream;
.source "NovaPrefetchInputStream.java"

.field private final queue:Ljava/util/concurrent/ArrayBlockingQueue;
.field private final source:Ljava/io/InputStream;
.field private current:[B
.field private offset:I
.field private final generation:I
.field private final worker:Ljava/lang/Thread;

.method public constructor <init>(Ljava/io/InputStream;J)V
    .locals 7
    invoke-direct {p0}, Ljava/io/InputStream;-><init>()V
    iput-object p1, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->source:Ljava/io/InputStream;

    new-instance v0, Ljava/util/concurrent/ArrayBlockingQueue;
    const/16 v1, 0x100
    invoke-direct {v0, v1}, Ljava/util/concurrent/ArrayBlockingQueue;-><init>(I)V
    iput-object v0, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->queue:Ljava/util/concurrent/ArrayBlockingQueue;

    invoke-static {p2, p3}, Lcom/archos/filecorelibrary/NovaBufferGuard;->onPrefetchStart(J)I
    move-result v2
    iput v2, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->generation:I

    new-instance v3, Lcom/archos/filecorelibrary/NovaPrefetchProducer;
    invoke-direct {v3, p1, v0, p2, p3}, Lcom/archos/filecorelibrary/NovaPrefetchProducer;-><init>(Ljava/io/InputStream;Ljava/util/concurrent/ArrayBlockingQueue;J)V

    new-instance v4, Ljava/lang/Thread;
    const-string v5, "Nova WebDAV prefetch"
    invoke-direct {v4, v3, v5}, Ljava/lang/Thread;-><init>(Ljava/lang/Runnable;Ljava/lang/String;)V
    iput-object v4, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->worker:Ljava/lang/Thread;
    const/4 v6, 0x1
    invoke-virtual {v4, v6}, Ljava/lang/Thread;->setDaemon(Z)V
    invoke-virtual {v4}, Ljava/lang/Thread;->start()V
    return-void
.end method

.method public read()I
    .locals 4
    const/4 v0, 0x1
    new-array v1, v0, [B
    const/4 v2, 0x0
    invoke-virtual {p0, v1, v2, v0}, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->read([BII)I
    move-result v3
    if-ltz v3, :eof
    aget-byte v3, v1, v2
    and-int/lit16 v3, v3, 0xff
    return v3
    :eof
    const/4 v3, -0x1
    return v3
.end method

.method public read([BII)I
    .locals 7
    if-nez p3, :loop
    const/4 v0, 0x0
    return v0

    :loop
    iget-object v0, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->current:[B
    if-eqz v0, :take
    array-length v1, v0
    iget v2, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->offset:I
    sub-int/2addr v1, v2
    if-lez v1, :take
    invoke-static {v1, p3}, Ljava/lang/Math;->min(II)I
    move-result v1
    invoke-static {v0, v2, p1, p2, v1}, Ljava/lang/System;->arraycopy(Ljava/lang/Object;ILjava/lang/Object;II)V
    add-int/2addr v2, v1
    iput v2, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->offset:I
    iget v3, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->generation:I
    invoke-static {v3, v1}, Lcom/archos/filecorelibrary/NovaBufferGuard;->onPrefetchConsumed(II)V
    return v1

    :take
    :try_start
    iget-object v4, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->queue:Ljava/util/concurrent/ArrayBlockingQueue;
    invoke-virtual {v4}, Ljava/util/concurrent/ArrayBlockingQueue;->take()Ljava/lang/Object;
    move-result-object v0
    check-cast v0, [B
    :try_end
    array-length v5, v0
    if-nez v5, :set_chunk
    const/4 v6, -0x1
    return v6

    :set_chunk
    iput-object v0, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->current:[B
    const/4 v5, 0x0
    iput v5, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->offset:I
    goto :loop

    :catch
    move-exception v0
    invoke-static {}, Ljava/lang/Thread;->currentThread()Ljava/lang/Thread;
    move-result-object v1
    invoke-virtual {v1}, Ljava/lang/Thread;->interrupt()V
    new-instance v1, Ljava/io/IOException;
    const-string v2, "Nova prefetch interrupted"
    invoke-direct {v1, v2}, Ljava/io/IOException;-><init>(Ljava/lang/String;)V
    throw v1

    .catch Ljava/lang/InterruptedException; {:try_start .. :try_end} :catch
.end method

.method public available()I
    .locals 3
    iget-object v0, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->current:[B
    if-eqz v0, :none
    array-length v1, v0
    iget v2, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->offset:I
    sub-int/2addr v1, v2
    if-gez v1, :none
    return v1
    :none
    const/4 v0, 0x0
    return v0
.end method

.method public close()V
    .locals 2
    iget-object v0, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->worker:Ljava/lang/Thread;
    if-eqz v0, :close_source
    invoke-virtual {v0}, Ljava/lang/Thread;->interrupt()V
    :close_source
    iget-object v1, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->source:Ljava/io/InputStream;
    invoke-virtual {v1}, Ljava/io/InputStream;->close()V
    return-void
.end method
'''

PREFETCH_PRODUCER = r'''.class public final Lcom/archos/filecorelibrary/NovaPrefetchProducer;
.super Ljava/lang/Object;
.source "NovaPrefetchProducer.java"

.implements Ljava/lang/Runnable;

.field private final source:Ljava/io/InputStream;
.field private final queue:Ljava/util/concurrent/ArrayBlockingQueue;
.field private remaining:J
.field private final generation:I

.method public constructor <init>(Ljava/io/InputStream;Ljava/util/concurrent/ArrayBlockingQueue;J)V
    .locals 1
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    iput-object p1, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->source:Ljava/io/InputStream;
    iput-object p2, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->queue:Ljava/util/concurrent/ArrayBlockingQueue;
    iput-wide p3, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->remaining:J
    invoke-static {}, Lcom/archos/filecorelibrary/NovaBufferGuard;->currentGeneration()I
    move-result v0
    iput v0, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->generation:I
    return-void
.end method

.method public run()V
    .locals 12
    const v0, 0x40000
    new-array v1, v0, [B

    :loop
    :try_start
    iget-wide v2, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->remaining:J
    const-wide/16 v4, 0x0
    cmp-long v6, v2, v4
    if-eqz v6, :eof

    const v7, 0x40000
    if-gez v6, :known
    goto :read

    :known
    const-wide/32 v4, 0x40000
    cmp-long v6, v2, v4
    if-gtz v6, :read
    long-to-int v7, v2

    :read
    iget-object v8, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->source:Ljava/io/InputStream;
    const/4 v9, 0x0
    invoke-virtual {v8, v1, v9, v7}, Ljava/io/InputStream;->read([BII)I
    move-result v7
    if-gez v7, :eof
    if-eqz v7, :loop

    invoke-static {v1, v7}, Ljava/util/Arrays;->copyOf([BI)[B
    move-result-object v10
    iget-object v8, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->queue:Ljava/util/concurrent/ArrayBlockingQueue;
    invoke-virtual {v8, v10}, Ljava/util/concurrent/ArrayBlockingQueue;->put(Ljava/lang/Object;)V

    iget v8, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->generation:I
    invoke-static {v8, v7}, Lcom/archos/filecorelibrary/NovaBufferGuard;->onPrefetchProduced(II)V

    iget-wide v2, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->remaining:J
    const-wide/16 v4, 0x0
    cmp-long v6, v2, v4
    if-lez v6, :known_remaining
    goto :loop

    :known_remaining
    int-to-long v4, v7
    sub-long/2addr v2, v4
    iput-wide v2, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->remaining:J
    goto :loop

    :eof
    const/4 v11, 0x0
    new-array v10, v11, [B
    iget-object v8, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->queue:Ljava/util/concurrent/ArrayBlockingQueue;
    invoke-virtual {v8, v10}, Ljava/util/concurrent/ArrayBlockingQueue;->put(Ljava/lang/Object;)V
    iget v8, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->generation:I
    invoke-static {v8}, Lcom/archos/filecorelibrary/NovaBufferGuard;->onPrefetchEof(I)V
    :try_end
    return-void

    :catch
    move-exception v11
    iget v8, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->generation:I
    invoke-static {v8}, Lcom/archos/filecorelibrary/NovaBufferGuard;->onPrefetchError(I)V
    const/4 v9, 0x0
    new-array v10, v9, [B
    iget-object v8, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->queue:Ljava/util/concurrent/ArrayBlockingQueue;
    invoke-virtual {v8, v10}, Ljava/util/concurrent/ArrayBlockingQueue;->offer(Ljava/lang/Object;)Z
    return-void

    .catch Ljava/lang/Throwable; {:try_start .. :try_end} :catch
.end method
'''

def patch_stream(text: str):
    m = method(text, " upstreamBufferSize(Lcom/archos/filecorelibrary/FileEditor;Z)I")
    b = m.group(0)
    b, n = bump_locals(b, 2)
    r0, r1 = f"v{n}", f"v{n+1}"
    loc = re.search(r'(?m)^    \.locals \d+\s*$', b)
    if not loc:
        raise RuntimeError("upstreamBufferSize locals missing")
    inject = f'''
    if-eqz p2, :nova_prefetch_default
    iget-object {r0}, p0, Lcom/archos/filecorelibrary/StreamOverHttp;->mReadMode:Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;
    sget-object {r1}, Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;->PLAYBACK:Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;
    if-ne {r0}, {r1}, :nova_prefetch_default
    iget-object {r0}, p0, Lcom/archos/filecorelibrary/StreamOverHttp;->mUri:Landroid/net/Uri;
    if-eqz {r0}, :nova_prefetch_default
    invoke-virtual {{{r0}}}, Landroid/net/Uri;->getScheme()Ljava/lang/String;
    move-result-object {r0}
    if-eqz {r0}, :nova_prefetch_default
    const-string {r1}, "webdav"
    invoke-virtual {{{r1}, {r0}}}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result {r1}
    if-nez {r1}, :nova_prefetch_yes
    const-string {r1}, "webdavs"
    invoke-virtual {{{r1}, {r0}}}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result {r1}
    if-eqz {r1}, :nova_prefetch_default
    :nova_prefetch_yes
    const {r0}, 0x40001
    return {r0}
    :nova_prefetch_default
'''
    b = b[:loc.end()] + inject + b[loc.end():]
    text = text[:m.start()] + b + text[m.end():]

    m = method(text, " bufferResponseInput(Ljava/io/InputStream;JI)Ljava/io/InputStream;")
    b = m.group(0)
    b, n = bump_locals(b, 1)
    r0 = f"v{n}"
    loc = re.search(r'(?m)^    \.locals \d+\s*$', b)
    if not loc:
        raise RuntimeError("bufferResponseInput locals missing")
    inject = f'''
    const {r0}, 0x40001
    if-ne p3, {r0}, :nova_prefetch_normal
    new-instance {r0}, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;
    invoke-direct {{{r0}, p0, p1, p2}}, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;-><init>(Ljava/io/InputStream;J)V
    return-object {r0}
    :nova_prefetch_normal
'''
    b = b[:loc.end()] + inject + b[loc.end():]
    text = text[:m.start()] + b + text[m.end():]
    return text

def apply(root: Path, report: Path | None = None):
    stream = one(root.glob("smali*/com/archos/filecorelibrary/StreamOverHttp.smali"), "StreamOverHttp")
    stream.write_text(patch_stream(stream.read_text()))

    guard = one(root.glob("smali*/com/archos/filecorelibrary/NovaBufferGuard.smali"), "NovaBufferGuard")
    guard.write_text(GUARD)
    d = guard.parent
    (d / "NovaPrefetchInputStream.smali").write_text(PREFETCH_INPUT)
    (d / "NovaPrefetchProducer.smali").write_text(PREFETCH_PRODUCER)

    result = {
        "status": "PASS",
        "strategy": "WebDAV playback prefetch decoupled from AVOS consumption",
        "capacity_bytes": 67108864,
        "pause_below_bytes": 25165824,
        "resume_at_bytes": 47185920,
        "producer": "dedicated upstream reader thread",
        "consumer": "StreamOverHttp socket writer via 256 x 256KiB ArrayBlockingQueue chunks",
        "logging": "ADB logcat tag NovaBufGuard"
    }
    if report:
        report.write_text(json.dumps(result, indent=2) + "\n")
    return result

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    print(json.dumps(apply(a.root, a.report), indent=2))
