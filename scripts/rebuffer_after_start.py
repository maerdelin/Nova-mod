from __future__ import annotations
import json,re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method [^\n]+\n.*?^\.end method', re.M|re.S)

def _one(paths,label):
    paths=list(paths)
    if len(paths)!=1: raise RuntimeError(f'{label}: expected 1, got {len(paths)}')
    return paths[0]

def _find_method(text,sig):
    hits=[m for m in METHOD_RE.finditer(text) if sig in m.group(0).splitlines()[0]]
    if len(hits)!=1: raise RuntimeError(f'{sig}: expected 1, got {len(hits)}')
    return hits[0]

REBUFFER_SMALI = r'''.class public final Lcom/archos/filecorelibrary/NovaRebufferInputStream;
.super Ljava/io/InputStream;
.source "NovaRebufferInputStream.java"

.implements Ljava/lang/Runnable;

.field private static final CAPACITY:I = 0x4000000
.field private static final CHUNK:I = 0x40000
.field private static final LOW:I = 0x1800000
.field private static final RESUME:I = 0x2d00000
.field private static volatile current:Lcom/archos/filecorelibrary/NovaRebufferInputStream;

.field private volatile active:Z
.field private volatile buffering:Z
.field private volatile closed:Z
.field private volatile eof:Z
.field private volatile failure:Ljava/io/IOException;
.field private final pipeIn:Ljava/io/PipedInputStream;
.field private final pipeOut:Ljava/io/PipedOutputStream;
.field private final source:Ljava/io/InputStream;

.method private constructor <init>(Ljava/io/InputStream;)V
    .locals 5
    .annotation system Ldalvik/annotation/Throws;
        value = {Ljava/io/IOException;}
    .end annotation

    invoke-direct {p0}, Ljava/io/InputStream;-><init>()V
    iput-object p1, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->source:Ljava/io/InputStream;

    new-instance v0, Ljava/io/PipedInputStream;
    const v1, 0x4000000
    invoke-direct {v0, v1}, Ljava/io/PipedInputStream;-><init>(I)V
    iput-object v0, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->pipeIn:Ljava/io/PipedInputStream;

    new-instance v1, Ljava/io/PipedOutputStream;
    invoke-direct {v1, v0}, Ljava/io/PipedOutputStream;-><init>(Ljava/io/PipedInputStream;)V
    iput-object v1, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->pipeOut:Ljava/io/PipedOutputStream;

    sget-object v2, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->current:Lcom/archos/filecorelibrary/NovaRebufferInputStream;
    if-eqz v2, :set_current
    const/4 v3, 0x0
    iput-boolean v3, v2, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->active:Z
    iput-boolean v3, v2, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->buffering:Z

    :set_current
    sput-object p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->current:Lcom/archos/filecorelibrary/NovaRebufferInputStream;

    new-instance v2, Ljava/lang/Thread;
    const-string v3, "Nova WebDAV prefetch"
    invoke-direct {v2, p0, v3}, Ljava/lang/Thread;-><init>(Ljava/lang/Runnable;Ljava/lang/String;)V
    const/4 v4, 0x1
    invoke-virtual {v2, v4}, Ljava/lang/Thread;->setDaemon(Z)V
    invoke-virtual {v2}, Ljava/lang/Thread;->start()V

    new-instance v2, Lcom/archos/filecorelibrary/NovaRebufferInputStream$Watchdog;
    invoke-direct {v2, p0}, Lcom/archos/filecorelibrary/NovaRebufferInputStream$Watchdog;-><init>(Lcom/archos/filecorelibrary/NovaRebufferInputStream;)V
    new-instance v3, Ljava/lang/Thread;
    const-string v0, "Nova WebDAV rebuffer watchdog"
    invoke-direct {v3, v2, v0}, Ljava/lang/Thread;-><init>(Ljava/lang/Runnable;Ljava/lang/String;)V
    invoke-virtual {v3, v4}, Ljava/lang/Thread;->setDaemon(Z)V
    invoke-virtual {v3}, Ljava/lang/Thread;->start()V
    return-void
.end method

.method public static wrap(Ljava/io/InputStream;)Ljava/io/InputStream;
    .locals 3
    if-eqz p0, :return_original
    :try_start_0
    new-instance v0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;
    invoke-direct {v0, p0}, Lcom/archos/filecorelibrary/NovaRebufferInputStream;-><init>(Ljava/io/InputStream;)V
    const-string v1, "NovaNetBuf"
    const-string v2, "PREFETCH_ON cap=64MiB startup=main-pass"
    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-object v0
    :try_end_0
    .catch Ljava/io/IOException; {:try_start_0 .. :try_end_0} :fallback

    :fallback
    move-exception v0
    const-string v1, "NovaNetBuf"
    const-string v2, "PREFETCH_INIT_FAIL fallback=main"
    invoke-static {v1, v2, v0}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I
    :return_original
    return-object p0
.end method

.method public static onPlaybackStarted()V
    .locals 3
    sget-object v0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->current:Lcom/archos/filecorelibrary/NovaRebufferInputStream;
    if-eqz v0, :done
    const/4 v1, 0x1
    iput-boolean v1, v0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->active:Z
    const-string v1, "NovaNetBuf"
    const-string v2, "PROTECTION_ACTIVE after_native_start"
    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    :done
    return-void
.end method

.method public static onPlaybackStopped()V
    .locals 2
    sget-object v0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->current:Lcom/archos/filecorelibrary/NovaRebufferInputStream;
    if-eqz v0, :done
    const/4 v1, 0x0
    iput-boolean v1, v0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->active:Z
    iput-boolean v1, v0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->buffering:Z
    :done
    return-void
.end method

.method private monitorLoop()V
    .locals 5
    :loop
    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->closed:Z
    if-nez v0, :done
    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->active:Z
    if-eqz v0, :sleep

    iget-object v0, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->available()I
    move-result v0

    iget-boolean v1, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->buffering:Z
    if-eqz v1, :not_buffering

    iget-boolean v1, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->eof:Z
    if-nez v1, :resume_now
    const v1, 0x2d00000
    if-le v0, v1, :sleep

    :resume_now
    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->novaResumeFromBuffer()V
    const/4 v1, 0x0
    iput-boolean v1, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->buffering:Z
    const-string v2, "NovaNetBuf"
    const-string v3, "RESUME buffer>45MiB_or_eof"
    invoke-static {v2, v3}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    goto :sleep

    :not_buffering
    iget-boolean v1, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->eof:Z
    if-nez v1, :sleep
    const v1, 0x1800000
    if-ge v0, v1, :sleep

    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->novaPauseForBuffer()Z
    move-result v1
    if-eqz v1, :sleep
    const/4 v1, 0x1
    iput-boolean v1, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->buffering:Z
    const-string v2, "NovaNetBuf"
    const-string v3, "PAUSE buffer<24MiB"
    invoke-static {v2, v3}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    :sleep
    const-wide/32 v1, 0x4c4b40
    invoke-static {v1, v2}, Ljava/util/concurrent/locks/LockSupport;->parkNanos(J)V
    goto :loop

    :done
    return-void
.end method

.method public run()V
    .locals 5
    const v0, 0x40000
    new-array v0, v0, [B
    :loop
    iget-boolean v1, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->closed:Z
    if-nez v1, :finish
    :try_start_0
    iget-object v1, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->source:Ljava/io/InputStream;
    const/4 v2, 0x0
    array-length v3, v0
    invoke-virtual {v1, v0, v2, v3}, Ljava/io/InputStream;->read([BII)I
    move-result v1
    if-ltz v1, :finish
    if-eqz v1, :loop
    iget-object v3, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->pipeOut:Ljava/io/PipedOutputStream;
    invoke-virtual {v3, v0, v2, v1}, Ljava/io/OutputStream;->write([BII)V
    goto :loop
    :try_end_0
    .catch Ljava/io/IOException; {:try_start_0 .. :try_end_0} :iofail

    :iofail
    move-exception v1
    iput-object v1, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->failure:Ljava/io/IOException;

    :finish
    const/4 v1, 0x1
    iput-boolean v1, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->eof:Z
    :try_start_1
    iget-object v1, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->pipeOut:Ljava/io/PipedOutputStream;
    invoke-virtual {v1}, Ljava/io/PipedOutputStream;->close()V
    :try_end_1
    .catch Ljava/io/IOException; {:try_start_1 .. :try_end_1} :done
    :done
    return-void
.end method

.method public read()I
    .locals 2
    iget-object v0, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->read()I
    move-result v0
    if-ltz v0, :check_failure
    return v0
    :check_failure
    iget-object v1, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->failure:Ljava/io/IOException;
    if-eqz v1, :ret
    throw v1
    :ret
    return v0
.end method

.method public read([BII)I
    .locals 2
    iget-object v0, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0, p1, p2, p3}, Ljava/io/PipedInputStream;->read([BII)I
    move-result v0
    if-ltz v0, :check_failure
    return v0
    :check_failure
    iget-object v1, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->failure:Ljava/io/IOException;
    if-eqz v1, :ret
    throw v1
    :ret
    return v0
.end method

.method public available()I
    .locals 1
    iget-object v0, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->available()I
    move-result v0
    return v0
.end method

.method public skip(J)J
    .locals 2
    iget-object v0, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0, p1, p2}, Ljava/io/PipedInputStream;->skip(J)J
    move-result-wide v0
    return-wide v0
.end method

.method public close()V
    .locals 2
    const/4 v0, 0x1
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->closed:Z
    const/4 v0, 0x0
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->active:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->buffering:Z
    :try_start_0
    iget-object v0, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->source:Ljava/io/InputStream;
    invoke-virtual {v0}, Ljava/io/InputStream;->close()V
    :try_end_0
    .catch Ljava/io/IOException; {:try_start_0 .. :try_end_0} :after_source
    :after_source
    :try_start_1
    iget-object v0, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->close()V
    :try_end_1
    .catch Ljava/io/IOException; {:try_start_1 .. :try_end_1} :after_in
    :after_in
    :try_start_2
    iget-object v0, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->pipeOut:Ljava/io/PipedOutputStream;
    invoke-virtual {v0}, Ljava/io/PipedOutputStream;->close()V
    :try_end_2
    .catch Ljava/io/IOException; {:try_start_2 .. :try_end_2} :done
    :done
    return-void
.end method

.method public static access$monitor(Lcom/archos/filecorelibrary/NovaRebufferInputStream;)V
    .locals 0
    invoke-direct {p0}, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->monitorLoop()V
    return-void
.end method

.method public static main([Ljava/lang/String;)V
    .locals 2
    const-class v0, Lcom/archos/filecorelibrary/NovaRebufferInputStream;
    invoke-virtual {v0}, Ljava/lang/Class;->getName()Ljava/lang/String;
    move-result-object v1
    const-class v0, Lcom/archos/mediacenter/video/player/Player;
    invoke-virtual {v0}, Ljava/lang/Class;->getName()Ljava/lang/String;
    move-result-object v1
    return-void
.end method
'''

WATCHDOG_SMALI = r'''.class final Lcom/archos/filecorelibrary/NovaRebufferInputStream$Watchdog;
.super Ljava/lang/Object;
.source "NovaRebufferInputStream.java"

.implements Ljava/lang/Runnable;

.field private final owner:Lcom/archos/filecorelibrary/NovaRebufferInputStream;

.method public constructor <init>(Lcom/archos/filecorelibrary/NovaRebufferInputStream;)V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    iput-object p1, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream$Watchdog;->owner:Lcom/archos/filecorelibrary/NovaRebufferInputStream;
    return-void
.end method

.method public run()V
    .locals 1
    iget-object v0, p0, Lcom/archos/filecorelibrary/NovaRebufferInputStream$Watchdog;->owner:Lcom/archos/filecorelibrary/NovaRebufferInputStream;
    invoke-static {v0}, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->access$monitor(Lcom/archos/filecorelibrary/NovaRebufferInputStream;)V
    return-void
.end method
'''

SESSION_METHOD = r'''.method public shouldUseNovaRebuffer()Z
    .locals 6
    iget-boolean v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->supersedableMediaRequest:Z
    if-eqz v0, :no

    iget-object v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->this$0:Lcom/archos/filecorelibrary/StreamOverHttp;
    invoke-static {v0}, Lcom/archos/filecorelibrary/StreamOverHttp;->m(Lcom/archos/filecorelibrary/StreamOverHttp;)Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;
    move-result-object v0
    sget-object v1, Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;->PLAYBACK:Lcom/archos/filecorelibrary/StreamOverHttp$ReadMode;
    if-ne v0, v1, :no

    iget-object v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->this$0:Lcom/archos/filecorelibrary/StreamOverHttp;
    invoke-static {v0}, Lcom/archos/filecorelibrary/StreamOverHttp;->p(Lcom/archos/filecorelibrary/StreamOverHttp;)Landroid/net/Uri;
    move-result-object v0
    if-eqz v0, :no
    invoke-virtual {v0}, Landroid/net/Uri;->getScheme()Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :no
    const-string v1, "webdav"
    invoke-virtual {v1, v0}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v1
    if-nez v1, :size_check
    const-string v1, "webdavs"
    invoke-virtual {v1, v0}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v1
    if-eqz v1, :no

    :size_check
    iget-boolean v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->partialResponse:Z
    if-eqz v0, :full
    iget-wide v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->requestedEnd:J
    iget-wide v2, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->requestedStart:J
    sub-long/2addr v0, v2
    const-wide/16 v2, 0x1
    add-long/2addr v0, v2
    goto :compare

    :full
    iget-wide v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->length:J
    const-wide/16 v2, 0x0
    cmp-long v4, v0, v2
    if-ltz v4, :yes

    :compare
    const-wide/32 v2, 0x800000
    cmp-long v4, v0, v2
    if-gez v4, :no

    :yes
    const/4 v0, 0x1
    return v0
    :no
    const/4 v0, 0x0
    return v0
.end method
'''

PLAYER_METHODS = r'''.method public static novaPauseForBuffer()Z
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
    const/4 v3, 0x1
    sput-boolean v3, Lcom/archos/mediacenter/video/player/Player;->sNovaRebufferPaused:Z
    const-string v0, "NovaNetBuf"
    const-string v1, "PLAYER_PAUSE nativePause=1"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return v3
    :no
    const/4 v0, 0x0
    return v0
.end method

.method public static novaResumeFromBuffer()V
    .locals 4
    sget-boolean v0, Lcom/archos/mediacenter/video/player/Player;->sNovaRebufferPaused:Z
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
    sput-boolean v3, Lcom/archos/mediacenter/video/player/Player;->sNovaRebufferPaused:Z
    const-string v0, "NovaNetBuf"
    const-string v1, "PLAYER_RESUME nativeStart=1"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
    :clear
    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/mediacenter/video/player/Player;->sNovaRebufferPaused:Z
    :done
    return-void
.end method

.method public static novaCancelRebufferPause()V
    .locals 1
    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/mediacenter/video/player/Player;->sNovaRebufferPaused:Z
    return-void
.end method
'''

def patch_player(text):
    if 'novaPauseForBuffer()Z' in text: return text,'already'
    anchor='.field public static sPlayer:Lcom/archos/mediacenter/video/player/Player;\n'
    if text.count(anchor)!=1: raise RuntimeError('sPlayer anchor')
    text=text.replace(anchor,anchor+'\n.field private static volatile sNovaRebufferPaused:Z\n',1)

    m=_find_method(text,' start(I)V'); b=m.group(0)
    anchor2='    invoke-interface {v3}, Lcom/archos/medialib/IMediaPlayer;->start()V\n\n    iput v0, p0, Lcom/archos/mediacenter/video/player/Player;->mCurrentState:I'
    if b.count(anchor2)!=1: raise RuntimeError('start anchor')
    b=b.replace(anchor2,anchor2+'\n\n    invoke-static {}, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->onPlaybackStarted()V',1)
    text=text[:m.start()]+b+text[m.end():]

    for sig in (' pause(I)V',' stopPlayback()V'):
        m=_find_method(text,sig); b=m.group(0)
        loc=b.find('.locals '); nl=b.find('\n',loc)
        inj='\n\n    invoke-static {}, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->onPlaybackStopped()V\n    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->novaCancelRebufferPause()V'
        b=b[:nl]+inj+b[nl:]
        text=text[:m.start()]+b+text[m.end():]

    m=_find_method(text,' onCompletion(Lcom/archos/medialib/IMediaPlayer;)V'); b=m.group(0)
    loc=b.find('.locals '); nl=b.find('\n',loc)
    inj='\n\n    invoke-static {}, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->onPlaybackStopped()V\n    invoke-static {}, Lcom/archos/mediacenter/video/player/Player;->novaCancelRebufferPause()V'
    b=b[:nl]+inj+b[nl:]
    text=text[:m.start()]+b+text[m.end():]
    return text.rstrip()+'\n\n'+PLAYER_METHODS+'\n','applied'

def patch_session(text):
    if 'shouldUseNovaRebuffer()Z' in text: return text,'already'
    return text.rstrip()+'\n\n'+SESSION_METHOD+'\n','applied'

def patch_stream(text):
    if 'NovaRebufferInputStream;->wrap' in text: return text,'already'
    m=_find_method(text,' sendResponse(Ljava/net/Socket;Ljava/lang/String;Ljava/lang/String;Ljava/util/Properties;Ljava/io/InputStream;J[BLjava/lang/String;Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;)V')
    b=m.group(0)
    anchor='    invoke-static {v2, v14, v15, v9}, Lcom/archos/filecorelibrary/StreamOverHttp;->bufferResponseInput(Ljava/io/InputStream;JI)Ljava/io/InputStream;\n\n    move-result-object v9'
    if b.count(anchor)!=1: raise RuntimeError('sendResponse buffer anchor')
    repl=anchor+'\n\n    if-eqz p10, :nova_wrap_done\n    invoke-virtual/range {p10 .. p10}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->shouldUseNovaRebuffer()Z\n    move-result v10\n    if-eqz v10, :nova_wrap_done\n    invoke-static {v9}, Lcom/archos/filecorelibrary/NovaRebufferInputStream;->wrap(Ljava/io/InputStream;)Ljava/io/InputStream;\n    move-result-object v9\n    :nova_wrap_done'
    b=b.replace(anchor,repl,1)
    return text[:m.start()]+b+text[m.end():],'applied'

def _next_smali(root):
    nums=[]
    for p in root.glob('smali_classes*'):
        try: nums.append(int(p.name.replace('smali_classes','')))
        except: pass
    n=max(nums+[1])+1
    d=root/f'smali_classes{n}'; d.mkdir(parents=True,exist_ok=True); return d

def apply(root:Path, report:Path|None=None):
    player=_one(root.glob('smali*/com/archos/mediacenter/video/player/Player.smali'),'Player')
    t,ps=patch_player(player.read_text()); player.write_text(t)
    sess=_one(root.glob('smali*/com/archos/filecorelibrary/StreamOverHttp$HttpSession.smali'),'Session')
    t,ss=patch_session(sess.read_text()); sess.write_text(t)
    stream=_one(root.glob('smali*/com/archos/filecorelibrary/StreamOverHttp.smali'),'Stream')
    t,sts=patch_stream(stream.read_text()); stream.write_text(t)
    d=_next_smali(root)
    p=d/'com/archos/filecorelibrary/NovaRebufferInputStream.smali'; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(REBUFFER_SMALI)
    w=p.parent/'NovaRebufferInputStream$Watchdog.smali'; w.write_text(WATCHDOG_SMALI)
    result={'status':'PASS','player':ps,'session':ss,'stream':sts,'startup':'main path unchanged; protection activates only after IMediaPlayer.start','low_mib':24,'resume_mib':45,'capacity_mib':64,'forbidden_old_terms_absent':all(x not in (t+REBUFFER_SMALI) for x in ('initialHold','beforeNativeStart','awaitBudget','bufferStartHeldCurrent'))}
    if report: report.write_text(json.dumps(result,indent=2)+'\n')
    return result
