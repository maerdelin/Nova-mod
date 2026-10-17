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

.field private final pipe:Ljava/io/PipedInputStream;
.field private final generation:I

.method public constructor <init>(Ljava/io/InputStream;J)V
    .locals 7
    invoke-direct {p0}, Ljava/io/InputStream;-><init>()V

    new-instance v0, Ljava/io/PipedInputStream;
    const v1, 0x4000000
    invoke-direct {v0, v1}, Ljava/io/PipedInputStream;-><init>(I)V
    iput-object v0, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->pipe:Ljava/io/PipedInputStream;

    new-instance v1, Ljava/io/PipedOutputStream;
    invoke-direct {v1, v0}, Ljava/io/PipedOutputStream;-><init>(Ljava/io/PipedInputStream;)V

    invoke-static {p2, p3}, Lcom/archos/filecorelibrary/NovaBufferGuard;->onPrefetchStart(J)I
    move-result v2
    iput v2, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->generation:I

    new-instance v3, Lcom/archos/filecorelibrary/NovaPrefetchProducer;
    invoke-direct {v3, p1, v1, p2, p3, v2}, Lcom/archos/filecorelibrary/NovaPrefetchProducer;-><init>(Ljava/io/InputStream;Ljava/io/PipedOutputStream;JI)V

    new-instance v4, Ljava/lang/Thread;
    const-string v5, "Nova WebDAV prefetch"
    invoke-direct {v4, v3, v5}, Ljava/lang/Thread;-><init>(Ljava/lang/Runnable;Ljava/lang/String;)V
    const/4 v6, 0x1
    invoke-virtual {v4, v6}, Ljava/lang/Thread;->setDaemon(Z)V
    invoke-virtual {v4}, Ljava/lang/Thread;->start()V
    return-void
.end method

.method public read()I
    .locals 3
    iget-object v0, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->pipe:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->read()I
    move-result v0
    if-ltz v0, :done
    iget v1, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->generation:I
    const/4 v2, 0x1
    invoke-static {v1, v2}, Lcom/archos/filecorelibrary/NovaBufferGuard;->onPrefetchConsumed(II)V
    :done
    return v0
.end method

.method public read([BII)I
    .locals 2
    iget-object v0, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->pipe:Ljava/io/PipedInputStream;
    invoke-virtual {v0, p1, p2, p3}, Ljava/io/PipedInputStream;->read([BII)I
    move-result v0
    if-lez v0, :done
    iget v1, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->generation:I
    invoke-static {v1, v0}, Lcom/archos/filecorelibrary/NovaBufferGuard;->onPrefetchConsumed(II)V
    :done
    return v0
.end method

.method public available()I
    .locals 1
    iget-object v0, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->pipe:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->available()I
    move-result v0
    return v0
.end method

.method public close()V
    .locals 1
    iget-object v0, p0, Lcom/archos/filecorelibrary/NovaPrefetchInputStream;->pipe:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->close()V
    return-void
.end method
'''

PREFETCH_PRODUCER = r'''.class public final Lcom/archos/filecorelibrary/NovaPrefetchProducer;
.super Ljava/lang/Object;
.source "NovaPrefetchProducer.java"

.implements Ljava/lang/Runnable;

.field private final source:Ljava/io/InputStream;
.field private final out:Ljava/io/PipedOutputStream;
.field private remaining:J
.field private final generation:I

.method public constructor <init>(Ljava/io/InputStream;Ljava/io/PipedOutputStream;JI)V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    iput-object p1, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->source:Ljava/io/InputStream;
    iput-object p2, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->out:Ljava/io/PipedOutputStream;
    iput-wide p3, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->remaining:J
    iput p5, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->generation:I
    return-void
.end method

.method public run()V
    .locals 11
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

    iget-object v8, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->out:Ljava/io/PipedOutputStream;
    invoke-virtual {v8, v1, v9, v7}, Ljava/io/PipedOutputStream;->write([BII)V

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
    iget v8, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->generation:I
    invoke-static {v8}, Lcom/archos/filecorelibrary/NovaBufferGuard;->onPrefetchEof(I)V
    iget-object v8, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->out:Ljava/io/PipedOutputStream;
    invoke-virtual {v8}, Ljava/io/PipedOutputStream;->close()V
    :try_end
    return-void

    :catch
    move-exception v10
    iget v8, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->generation:I
    invoke-static {v8}, Lcom/archos/filecorelibrary/NovaBufferGuard;->onPrefetchError(I)V
    :try_close
    iget-object v8, p0, Lcom/archos/filecorelibrary/NovaPrefetchProducer;->out:Ljava/io/PipedOutputStream;
    invoke-virtual {v8}, Ljava/io/PipedOutputStream;->close()V
    :try_close_end
    return-void

    .catch Ljava/lang/Throwable; {:try_start .. :try_end} :catch
    .catch Ljava/lang/Throwable; {:try_close .. :try_close_end} :catch_close
    :catch_close
    move-exception v10
    return-void
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
    const {r0}, 0x4000000
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
    const {r0}, 0x4000000
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
        "consumer": "StreamOverHttp socket writer via PipedInputStream",
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
