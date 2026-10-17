#!/usr/bin/env python3
from __future__ import annotations
import json, re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method [^\n]+\n.*?^\.end method', re.M | re.S)

def one(paths, label):
    xs=list(paths)
    if len(xs)!=1:
        raise RuntimeError(f"{label}: expected 1, got {len(xs)}")
    return xs[0]

def method(text, sig):
    xs=[m for m in METHOD_RE.finditer(text) if sig in m.group(0).splitlines()[0]]
    if len(xs)!=1:
        raise RuntimeError(f"{sig}: expected 1, got {len(xs)}")
    return xs[0]

def bump_locals(block, extra=1):
    m=re.search(r'(?m)^    \.locals (\d+)\s*$', block)
    if not m:
        raise RuntimeError("method has no .locals")
    n=int(m.group(1))
    block=block[:m.start(1)]+str(n+extra)+block[m.end(1):]
    return block, n

GUARD = r'''.class public final Lcom/archos/filecorelibrary/NovaBufferGuard;
.super Ljava/lang/Object;
.source "NovaBufferGuard.java"

.implements Ljava/lang/Runnable;

.field private static final TAG:Ljava/lang/String; = "NovaBufGuard"
.field private static final LOW_MS:J = 0xbb8L
.field private static final RESUME_MS:J = 0x1388L
.field private static final ARM_PROGRESS_MS:I = 0x3e8
.field private static final RANGE_GRACE_MS:J = 0x3e8L

.field private static volatile active:Z
.field private static volatile armed:Z
.field private static volatile buffering:Z
.field private static volatile threadStarted:Z
.field private static volatile activeRequestId:I
.field private static volatile playbackStartPos:I
.field private static volatile rangeStart:J
.field private static volatile rangeDelivered:J
.field private static volatile deliveredAbs:J
.field private static volatile mediaLength:J
.field private static volatile lastRangeChangeMs:J
.field private static volatile lastLogMs:J

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public static onBytes(IJJJI)V
    .locals 8

    sget v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->activeRequestId:I
    if-eq v0, p0, :same_range

    sput p0, Lcom/archos/filecorelibrary/NovaBufferGuard;->activeRequestId:I
    sput-wide p1, Lcom/archos/filecorelibrary/NovaBufferGuard;->rangeStart:J
    sput-wide p5, Lcom/archos/filecorelibrary/NovaBufferGuard;->mediaLength:J
    const-wide/16 v0, 0x0
    sput-wide v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->rangeDelivered:J
    sput-wide p1, Lcom/archos/filecorelibrary/NovaBufferGuard;->deliveredAbs:J
    invoke-static {}, Landroid/os/SystemClock;->uptimeMillis()J
    move-result-wide v0
    sput-wide v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->lastRangeChangeMs:J

    new-instance v2, Ljava/lang/StringBuilder;
    invoke-direct {v2}, Ljava/lang/StringBuilder;-><init>()V
    const-string v3, "RANGE id="
    invoke-virtual {v2, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v2, p0}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    const-string v3, " start="
    invoke-virtual {v2, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v2, p1, p2}, Ljava/lang/StringBuilder;->append(J)Ljava/lang/StringBuilder;
    const-string v3, " end="
    invoke-virtual {v2, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v2, p3, p4}, Ljava/lang/StringBuilder;->append(J)Ljava/lang/StringBuilder;
    const-string v3, " length="
    invoke-virtual {v2, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v2, p5, p6}, Ljava/lang/StringBuilder;->append(J)Ljava/lang/StringBuilder;
    invoke-virtual {v2}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v2
    const-string v3, "NovaBufGuard"
    invoke-static {v3, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    :same_range
    sget-wide v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->rangeDelivered:J
    int-to-long v2, p7
    add-long/2addr v0, v2
    sput-wide v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->rangeDelivered:J
    sget-wide v2, Lcom/archos/filecorelibrary/NovaBufferGuard;->rangeStart:J
    add-long/2addr v2, v0
    sput-wide v2, Lcom/archos/filecorelibrary/NovaBufferGuard;->deliveredAbs:J
    return-void
.end method

.method public static onPlaybackStarted()V
    .locals 5
    const/4 v0, 0x1
    sput-boolean v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->active:Z
    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->buffering:Z
    sput-boolean v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->armed:Z

    sget-object v1, Lcom/archos/mediacenter/video/player/Player;->sPlayer:Lcom/archos/mediacenter/video/player/Player;
    if-eqz v1, :thread
    invoke-virtual {v1}, Lcom/archos/mediacenter/video/player/Player;->getCurrentPosition()I
    move-result v2
    sput v2, Lcom/archos/filecorelibrary/NovaBufferGuard;->playbackStartPos:I

    :thread
    sget-boolean v1, Lcom/archos/filecorelibrary/NovaBufferGuard;->threadStarted:Z
    if-nez v1, :log
    const/4 v4, 0x1
    sput-boolean v4, Lcom/archos/filecorelibrary/NovaBufferGuard;->threadStarted:Z
    new-instance v1, Lcom/archos/filecorelibrary/NovaBufferGuard;
    invoke-direct {v1}, Lcom/archos/filecorelibrary/NovaBufferGuard;-><init>()V
    new-instance v2, Ljava/lang/Thread;
    const-string v3, "Nova buffer guard"
    invoke-direct {v2, v1, v3}, Ljava/lang/Thread;-><init>(Ljava/lang/Runnable;Ljava/lang/String;)V
    const/4 v4, 0x1
    invoke-virtual {v2, v4}, Ljava/lang/Thread;->setDaemon(Z)V
    invoke-virtual {v2}, Ljava/lang/Thread;->start()V

    :log
    const-string v1, "NovaBufGuard"
    const-string v2, "PLAYBACK_ACTIVE startup=main-pass low=3000ms resume=5000ms"
    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method public static onPlaybackStopped()V
    .locals 2
    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->active:Z
    sput-boolean v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->armed:Z
    sput-boolean v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->buffering:Z
    invoke-static {v0}, Lcom/archos/mediacenter/video/player/Player;->novaSetBufferingUi(Z)V
    const-string v0, "NovaBufGuard"
    const-string v1, "PLAYBACK_STOP"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method private static logState(IJJZ)V
    .locals 6
    invoke-static {}, Landroid/os/SystemClock;->uptimeMillis()J
    move-result-wide v0
    sget-wide v2, Lcom/archos/filecorelibrary/NovaBufferGuard;->lastLogMs:J
    sub-long v2, v0, v2
    const-wide/16 v4, 0x3e8
    cmp-long v2, v2, v4
    if-gez v2, :done
    sput-wide v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->lastLogMs:J

    new-instance v0, Ljava/lang/StringBuilder;
    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V
    const-string v1, "STATE posMs="
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, p0}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    const-string v1, " delivered="
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, p1, p2}, Ljava/lang/StringBuilder;->append(J)Ljava/lang/StringBuilder;
    const-string v1, " aheadMs="
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, p3, p4}, Ljava/lang/StringBuilder;->append(J)Ljava/lang/StringBuilder;
    const-string v1, " buffering="
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, p5}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;
    const-string v1, " armed="
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    sget-boolean v2, Lcom/archos/filecorelibrary/NovaBufferGuard;->armed:Z
    invoke-virtual {v0, v2}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;
    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v0
    const-string v1, "NovaBufGuard"
    invoke-static {v1, v0}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    :done
    return-void
.end method

.method public run()V
    .locals 16

    :loop
    const-wide/16 v0, 0xfa
    invoke-static {v0, v1}, Landroid/os/SystemClock;->sleep(J)V

    sget-boolean v0, Lcom/archos/filecorelibrary/NovaBufferGuard;->active:Z
    if-eqz v0, :loop

    sget-object v0, Lcom/archos/mediacenter/video/player/Player;->sPlayer:Lcom/archos/mediacenter/video/player/Player;
    if-eqz v0, :loop

    invoke-virtual {v0}, Lcom/archos/mediacenter/video/player/Player;->getDuration()I
    move-result v1
    if-lez v1, :loop

    invoke-virtual {v0}, Lcom/archos/mediacenter/video/player/Player;->getCurrentPosition()I
    move-result v2
    if-ltz v2, :loop

    sget-wide v3, Lcom/archos/filecorelibrary/NovaBufferGuard;->mediaLength:J
    const-wide/16 v5, 0x0
    cmp-long v7, v3, v5
    if-lez v7, :loop

    sget-wide v5, Lcom/archos/filecorelibrary/NovaBufferGuard;->deliveredAbs:J

    int-to-long v7, v2
    mul-long/2addr v7, v3
    int-to-long v9, v1
    div-long/2addr v7, v9

    sub-long v11, v5, v7
    const-wide/16 v13, 0x0
    cmp-long v15, v11, v13
    if-ltz v15, :ahead_nonnegative
    const-wide/16 v11, 0x0

    :ahead_nonnegative
    int-to-long v9, v1
    mul-long/2addr v11, v9
    div-long/2addr v11, v3

    sget-boolean v13, Lcom/archos/filecorelibrary/NovaBufferGuard;->buffering:Z
    invoke-static {v2, v5, v6, v11, v12, v13}, Lcom/archos/filecorelibrary/NovaBufferGuard;->logState(IJJZ)V

    invoke-static {}, Landroid/os/SystemClock;->uptimeMillis()J
    move-result-wide v9
    sget-wide v13, Lcom/archos/filecorelibrary/NovaBufferGuard;->lastRangeChangeMs:J
    sub-long/2addr v9, v13
    const-wide/16 v13, 0x3e8
    cmp-long v15, v9, v13
    if-ltz v15, :arm_check
    goto :loop

    :arm_check
    sget-boolean v9, Lcom/archos/filecorelibrary/NovaBufferGuard;->armed:Z
    if-nez v9, :enforce
    sget v9, Lcom/archos/filecorelibrary/NovaBufferGuard;->playbackStartPos:I
    sub-int v9, v2, v9
    const/16 v10, 0x3e8
    if-ge v9, v10, :arm_now
    const-wide/16 v9, 0x1388
    cmp-long v13, v11, v9
    if-ltz v13, :arm_now
    goto :loop

    :arm_now
    const/4 v9, 0x1
    sput-boolean v9, Lcom/archos/filecorelibrary/NovaBufferGuard;->armed:Z
    const-string v9, "NovaBufGuard"
    const-string v10, "GUARD_ARMED after-normal-playback"
    invoke-static {v9, v10}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    :enforce
    sget-boolean v9, Lcom/archos/filecorelibrary/NovaBufferGuard;->buffering:Z
    if-eqz v9, :not_buffering

    const-wide/16 v9, 0x1388
    cmp-long v13, v11, v9
    if-gez v13, :loop

    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->novaResumeFromBuffer()V
    const/4 v9, 0x0
    sput-boolean v9, Lcom/archos/filecorelibrary/NovaBufferGuard;->buffering:Z
    invoke-static {v9}, Lcom/archos/mediacenter/video/player/Player;->novaSetBufferingUi(Z)V
    const-string v9, "NovaBufGuard"
    const-string v10, "RESUME ahead>=5000ms"
    invoke-static {v9, v10}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    goto :loop

    :not_buffering
    const-wide/16 v9, 0xbb8
    cmp-long v13, v11, v9
    if-ltz v13, :loop

    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->novaPauseForBuffer()Z
    move-result v9
    if-eqz v9, :loop
    const/4 v9, 0x1
    sput-boolean v9, Lcom/archos/filecorelibrary/NovaBufferGuard;->buffering:Z
    invoke-static {v9}, Lcom/archos/mediacenter/video/player/Player;->novaSetBufferingUi(Z)V
    const-string v9, "NovaBufGuard"
    const-string v10, "PAUSE ahead<3000ms"
    invoke-static {v9, v10}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    goto :loop
.end method
'''

UI_RUNNABLE = r'''.class final Lcom/archos/mediacenter/video/player/NovaBufferUiRunnable;
.super Ljava/lang/Object;
.source "NovaBufferUiRunnable.java"

.implements Ljava/lang/Runnable;

.field private final owner:Lcom/archos/mediacenter/video/player/PlayerActivity;
.field private final show:Z

.method public constructor <init>(Lcom/archos/mediacenter/video/player/PlayerActivity;Z)V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    iput-object p1, p0, Lcom/archos/mediacenter/video/player/NovaBufferUiRunnable;->owner:Lcom/archos/mediacenter/video/player/PlayerActivity;
    iput-boolean p2, p0, Lcom/archos/mediacenter/video/player/NovaBufferUiRunnable;->show:Z
    return-void
.end method

.method public run()V
    .locals 2
    iget-object v0, p0, Lcom/archos/mediacenter/video/player/NovaBufferUiRunnable;->owner:Lcom/archos/mediacenter/video/player/PlayerActivity;
    iget-boolean v1, p0, Lcom/archos/mediacenter/video/player/NovaBufferUiRunnable;->show:Z
    invoke-virtual {v0, v1}, Lcom/archos/mediacenter/video/player/PlayerActivity;->novaApplyBufferingUi(Z)V
    return-void
.end method
'''

PLAYER_EXTRA = r'''.method public static novaPauseForBuffer()Z
    .locals 4
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
    const-string v0, "NovaBufGuard"
    const-string v1, "PLAYER_NATIVE_PAUSE"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    const/4 v0, 0x1
    return v0
    :no
    const/4 v0, 0x0
    return v0
.end method

.method public static novaResumeFromBuffer()V
    .locals 3
    sget-object v0, Lcom/archos/mediacenter/video/player/Player;->sPlayer:Lcom/archos/mediacenter/video/player/Player;
    if-eqz v0, :done
    iget v1, v0, Lcom/archos/mediacenter/video/player/Player;->mTargetState:I
    const/4 v2, 0x5
    if-ne v1, v2, :done
    iget v1, v0, Lcom/archos/mediacenter/video/player/Player;->mCurrentState:I
    if-ne v1, v2, :done
    iget-object v1, v0, Lcom/archos/mediacenter/video/player/Player;->mMediaPlayer:Lcom/archos/medialib/IMediaPlayer;
    if-eqz v1, :done
    invoke-interface {v1}, Lcom/archos/medialib/IMediaPlayer;->start()V
    const-string v0, "NovaBufGuard"
    const-string v1, "PLAYER_NATIVE_RESUME"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    :done
    return-void
.end method

.method public static novaSetBufferingUi(Z)V
    .locals 2
    sget-object v0, Lcom/archos/mediacenter/video/player/Player;->sPlayer:Lcom/archos/mediacenter/video/player/Player;
    if-eqz v0, :done
    iget-object v0, v0, Lcom/archos/mediacenter/video/player/Player;->mContext:Landroid/content/Context;
    instance-of v1, v0, Lcom/archos/mediacenter/video/player/PlayerActivity;
    if-eqz v1, :done
    check-cast v0, Lcom/archos/mediacenter/video/player/PlayerActivity;
    invoke-virtual {v0, p0}, Lcom/archos/mediacenter/video/player/PlayerActivity;->novaSetBufferingUi(Z)V
    :done
    return-void
.end method
'''

ACTIVITY_EXTRA = r'''.method public novaSetBufferingUi(Z)V
    .locals 2
    new-instance v0, Lcom/archos/mediacenter/video/player/NovaBufferUiRunnable;
    invoke-direct {v0, p0, p1}, Lcom/archos/mediacenter/video/player/NovaBufferUiRunnable;-><init>(Lcom/archos/mediacenter/video/player/PlayerActivity;Z)V
    invoke-virtual {p0, v0}, Landroid/app/Activity;->runOnUiThread(Ljava/lang/Runnable;)V
    return-void
.end method

.method public novaApplyBufferingUi(Z)V
    .locals 2
    iget-object v0, p0, Lcom/archos/mediacenter/video/player/PlayerActivity;->mProgressView:Landroid/view/View;
    if-eqz v0, :done
    if-eqz p1, :hide
    const/4 v1, 0x0
    invoke-virtual {v0, v1}, Landroid/view/View;->setVisibility(I)V
    goto :done
    :hide
    const/16 v1, 0x8
    invoke-virtual {v0, v1}, Landroid/view/View;->setVisibility(I)V
    :done
    return-void
.end method
'''

SESSION_EXTRA = r'''.method public novaDelivered(I)V
    .locals 8
    if-lez p1, :done

    iget-boolean v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->supersedableMediaRequest:Z
    if-eqz v0, :done

    iget-object v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->this$0:Lcom/archos/filecorelibrary/StreamOverHttp;
    invoke-static {v0}, Lcom/archos/filecorelibrary/StreamOverHttp;->m(Lcom/archos/filecorelibrary/StreamOverHttp;)Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;
    move-result-object v1
    sget-object v2, Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;->PLAYBACK:Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;
    if-ne v1, v2, :done

    invoke-static {v0}, Lcom/archos/filecorelibrary/StreamOverHttp;->p(Lcom/archos/filecorelibrary/StreamOverHttp;)Landroid/net/Uri;
    move-result-object v1
    if-eqz v1, :done
    invoke-virtual {v1}, Landroid/net/Uri;->getScheme()Ljava/lang/String;
    move-result-object v1
    if-eqz v1, :done
    const-string v2, "webdav"
    invoke-virtual {v2, v1}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-nez v2, :eligible
    const-string v2, "webdavs"
    invoke-virtual {v2, v1}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-eqz v2, :done

    :eligible
    iget v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->requestId:I
    iget-wide v1, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->requestedStart:J
    iget-wide v3, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->requestedEnd:J
    iget-wide v5, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->length:J
    move v7, p1
    invoke-static/range {v0 .. v7}, Lcom/archos/filecorelibrary/NovaBufferGuard;->onBytes(IJJJI)V
    :done
    return-void
.end method
'''

def patch_player(text):
    if "novaPauseForBuffer()Z" in text:
        return text, "already"

    m=method(text, " setVideoURI(Landroid/net/Uri;Ljava/util/Map;)V")
    b=m.group(0)
    b, newreg=bump_locals(b,1)
    reg=f"v{newreg}"
    mm=re.search(r'invoke-virtual \{([^}]+)\}, Landroid/net/Uri;->getScheme\(\)Ljava/lang/String;\n\s*move-result-object ([vp]\d+)', b)
    if not mm:
        raise RuntimeError("setVideoURI scheme anchor not found")
    scheme=mm.group(2)
    inject=f'''\n    const-string {reg}, "webdav"\n    invoke-virtual {{{reg}, {scheme}}}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z\n    move-result {reg}\n    if-nez {reg}, :nova_big_buffer\n    const-string {reg}, "webdavs"\n    invoke-virtual {{{reg}, {scheme}}}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z\n    move-result {reg}\n    if-eqz {reg}, :nova_default_buffer\n    :nova_big_buffer\n    const/16 {reg}, 0x80\n    invoke-static {{{reg}}}, Lcom/archos/medialib/LibAvos;->setStreamBufferSize(I)V\n    goto :nova_buffer_done\n    :nova_default_buffer\n    const/16 {reg}, 0x18\n    invoke-static {{{reg}}}, Lcom/archos/medialib/LibAvos;->setStreamBufferSize(I)V\n    :nova_buffer_done\n'''
    pos=mm.end()
    b=b[:pos]+inject+b[pos:]
    text=text[:m.start()]+b+text[m.end():]

    m=method(text," start(I)V"); b=m.group(0)
    anchor='    invoke-interface {v3}, Lcom/archos/medialib/IMediaPlayer;->start()V'
    if anchor not in b:
        raise RuntimeError("Player.start native start anchor missing")
    # activate only after original current-state assignment, not before native start
    idx=b.find(anchor)
    state_idx=b.find('->mCurrentState:I', idx)
    if state_idx<0:
        raise RuntimeError("Player.start state anchor missing")
    line_end=b.find('\n', state_idx)
    b=b[:line_end+1]+'    invoke-static {}, Lcom/archos/filecorelibrary/NovaBufferGuard;->onPlaybackStarted()V\n'+b[line_end+1:]
    text=text[:m.start()]+b+text[m.end():]

    for sig in (" pause(I)V"," stopPlayback()V"," onCompletion(Lcom/archos/medialib/IMediaPlayer;)V"):
        m=method(text,sig); b=m.group(0)
        loc=re.search(r'(?m)^    \.locals \d+\s*$',b)
        if not loc: raise RuntimeError(sig+" locals missing")
        b=b[:loc.end()]+'\n    invoke-static {}, Lcom/archos/filecorelibrary/NovaBufferGuard;->onPlaybackStopped()V'+b[loc.end():]
        text=text[:m.start()]+b+text[m.end():]

    return text.rstrip()+"\n\n"+PLAYER_EXTRA+"\n","applied"

def patch_activity(text):
    if "novaSetBufferingUi(Z)V" in text:
        return text,"already"
    return text.rstrip()+"\n\n"+ACTIVITY_EXTRA+"\n","applied"

def patch_session(text):
    if "novaDelivered(I)V" in text:
        return text,"already"
    return text.rstrip()+"\n\n"+SESSION_EXTRA+"\n","applied"

def patch_stream(text):
    if "HttpSession;->novaDelivered(I)V" in text:
        return text,"already"
    m=method(text," copyStream(Ljava/io/InputStream;Ljava/io/OutputStream;[BJLcom/archos/filecorelibrary/StreamOverHttp$HttpSession;)V")
    b=m.group(0)
    # Find the socket write and recover the count register from {out, buf, 0, count}.
    matches=list(re.finditer(r'invoke-virtual \{[^}]*?\}, Ljava/io/OutputStream;->write\(\[BII\)V',b))
    if len(matches)!=1:
        raise RuntimeError(f"copyStream write anchor count={len(matches)}")
    line=matches[0].group(0)
    regs=re.search(r'\{([^}]*)\}',line).group(1).replace(" ","").split(",")
    count_reg=regs[-1]
    ins='\n    if-eqz p6, :nova_delivered_done\n    invoke-virtual {p6, '+count_reg+'}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->novaDelivered(I)V\n    :nova_delivered_done'
    b=b[:matches[0].end()]+ins+b[matches[0].end():]
    return text[:m.start()]+b+text[m.end():],"applied"

def next_smali(root):
    nums=[]
    for p in root.glob("smali_classes*"):
        try: nums.append(int(p.name.replace("smali_classes","")))
        except: pass
    n=max(nums+[1])+1
    d=root/f"smali_classes{n}"
    d.mkdir(parents=True,exist_ok=True)
    return d

def apply(root:Path, report:Path|None=None):
    player=one(root.glob("smali*/com/archos/mediacenter/video/player/Player.smali"),"Player")
    t,ps=patch_player(player.read_text()); player.write_text(t)

    activity=one(root.glob("smali*/com/archos/mediacenter/video/player/PlayerActivity.smali"),"PlayerActivity")
    t,acts=patch_activity(activity.read_text()); activity.write_text(t)

    session=one(root.glob("smali*/com/archos/filecorelibrary/StreamOverHttp$HttpSession.smali"),"HttpSession")
    t,ss=patch_session(session.read_text()); session.write_text(t)

    stream=one(root.glob("smali*/com/archos/filecorelibrary/StreamOverHttp.smali"),"StreamOverHttp")
    t,sts=patch_stream(stream.read_text()); stream.write_text(t)

    d=next_smali(root)
    gp=d/"com/archos/filecorelibrary/NovaBufferGuard.smali"
    gp.parent.mkdir(parents=True,exist_ok=True)
    gp.write_text(GUARD)
    up=d/"com/archos/mediacenter/video/player/NovaBufferUiRunnable.smali"
    up.parent.mkdir(parents=True,exist_ok=True)
    up.write_text(UI_RUNNABLE)

    result={
      "status":"PASS","player":ps,"activity":acts,"session":ss,"stream":sts,
      "policy":{
        "startup":"unchanged; guard activates only after IMediaPlayer.start and mCurrentState PLAYING",
        "webdav_native_buffer_mib":128,
        "low_ms":3000,"resume_ms":5000,"range_grace_ms":1000,
        "measurement":"absolute bytes delivered by StreamOverHttp to AVOS localhost socket, mapped to media time using file length/duration",
        "ui":"reuse PlayerActivity native progress overlay"
      }
    }
    if report:
        report.write_text(json.dumps(result,indent=2)+"\n")
    return result

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("root",type=Path)
    p.add_argument("--report",type=Path)
    a=p.parse_args()
    print(json.dumps(apply(a.root,a.report),indent=2))


def verify_roundtrip(expected: Path, actual: Path, report: Path, g):
    sa = g.resource_map(expected)
    sb = g.resource_map(actual)
    ia = g.class_index(expected)
    ib = g.class_index(actual)
    bad = []
    if ia.keys() != ib.keys():
        bad.append("class set differs")
    for name in ia.keys() & ib.keys():
        a = ia[name].read_text().replace("const-string/jumbo", "const-string")
        b = ib[name].read_text().replace("const-string/jumbo", "const-string")
        if a != b and g.logical_class(a, sa) != g.logical_class(b, sb):
            bad.append(name)
    aa = {x.relative_to(expected).as_posix() for x in expected.rglob("*.xml")
          if x.relative_to(expected).as_posix().startswith(("res/", "AndroidManifest.xml"))}
    bb = {x.relative_to(actual).as_posix() for x in actual.rglob("*.xml")
          if x.relative_to(actual).as_posix().startswith(("res/", "AndroidManifest.xml"))}
    if aa != bb:
        bad.append("XML resource set differs")
    for path in aa & bb:
        if (expected/path).read_bytes() != (actual/path).read_bytes():
            if g.logical_xml(g.ET.parse(expected/path).getroot()) != g.logical_xml(g.ET.parse(actual/path).getroot()):
                bad.append(path)
    result = {
        "status": "FAIL" if bad else "PASS",
        "classes_compared": len(ia),
        "xml_files_compared": len(aa),
        "differences": sorted(bad),
        "comparison": "logical roundtrip with const-string/jumbo normalization",
        "runtime_tested": False,
    }
    g.write_json(report, result)
    if bad:
        raise g.Conflict("Buffer-guard roundtrip failed: " + str(bad[:20]))
    print(json.dumps(result, indent=2))
    return result
