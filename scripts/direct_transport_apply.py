# direct transport APK integration

from __future__ import annotations
import argparse, re, shutil, subprocess
from pathlib import Path

METHOD_RE = re.compile(r'^\.method [^\n]+\n.*?^\.end method', re.M | re.S)
AWAIT_RE = re.compile(
    r'^(?P<indent>\s*)invoke-static(?:/range)? \{(?P<regs>[^}]+)\}, '
    r'Lcom/archos/filecorelibrary/NetworkInitialization;->awaitReadyForSmb'
    r'\(Landroid/net/Uri;Landroid/content/Context;\)V\s*$',
    re.M,
)


# Native thread scheduling is restored in source before compilation.
# Fixed machine-code address patching would corrupt recompiled libavos.so.

def one(paths, label):
    xs=list(paths)
    if len(xs)!=1:
        raise RuntimeError(f"{label}: expected one, got {len(xs)}")
    return xs[0]

def run(*args):
    subprocess.run([str(x) for x in args], check=True)

def next_smali(root):
    nums=[1]
    for p in root.glob("smali_classes*"):
        try:
            nums.append(int(p.name.replace("smali_classes","")))
        except ValueError:
            pass
    return root/f"smali_classes{max(nums)+1}"


PROXY_HEAD = r'''.class public final Lcom/archos/mediacenter/video/player/DirectTransportProxy;
.super Ljava/lang/Object;
.source "DirectTransportProxy.java"

.field private static sForceAvos:Z
.field private static sIso:Z
.field private static sSkipInitialZeroSeek:Z

.method static constructor <clinit>()V
    .locals 1
    const-string v0, "nova_transport"
    invoke-static {v0}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V
    return-void
.end method

.method private constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public static armForUri(Landroid/net/Uri;)V
    .locals 5
    const/4 v0, 0x0
    const/4 v1, 0x0
    if-eqz p0, :store
    invoke-virtual {p0}, Landroid/net/Uri;->getScheme()Ljava/lang/String;
    move-result-object v2
    if-eqz v2, :store
    const-string v3, "webdav"
    invoke-virtual {v2, v3}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v4
    if-nez v4, :remote
    const-string v3, "webdavs"
    invoke-virtual {v2, v3}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v4
    if-eqz v4, :remote
    const-string v3, "novatransport"
    invoke-virtual {v2, v3}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v4
    if-eqz v4, :store
    const/4 v0, 0x1
    invoke-virtual {p0}, Landroid/net/Uri;->toString()Ljava/lang/String;
    move-result-object v2
    const-string v3, "&nova_iso=1&"
    invoke-virtual {v2, v3}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v1
    goto :store
    :remote
    const/4 v0, 0x1
    invoke-virtual {p0}, Landroid/net/Uri;->getPath()Ljava/lang/String;
    move-result-object v2
    if-eqz v2, :store
    sget-object v3, Ljava/util/Locale;->ROOT:Ljava/util/Locale;
    invoke-virtual {v2, v3}, Ljava/lang/String;->toLowerCase(Ljava/util/Locale;)Ljava/lang/String;
    move-result-object v2
    const-string v3, ".iso"
    invoke-virtual {v2, v3}, Ljava/lang/String;->endsWith(Ljava/lang/String;)Z
    move-result v1
    :store
    sput-boolean v0, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->sForceAvos:Z
    sput-boolean v1, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->sIso:Z
    sput-boolean v1, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->sSkipInitialZeroSeek:Z
    return-void
.end method

.method public static shouldForceAvos()Z
    .locals 1
    sget-boolean v0, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->sForceAvos:Z
    return v0
.end method

.method public static isNonIsoDirectWebdav()Z
    .locals 1
    # NOVA_NONISO_DUP_ZERO_SKIP_V1: non-ISO WebDAV/direct files only.
    # Preserve the separate original ISO one-shot zero-seek rule.
    sget-boolean v0, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->sForceAvos:Z
    if-eqz v0, :noniso_no
    sget-boolean v0, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->sIso:Z
    if-nez v0, :noniso_no
    const/4 v0, 0x1
    return v0
    :noniso_no
    const/4 v0, 0x0
    return v0
.end method

.method public static shouldSkipInitialZeroSeek(I)Z
    .locals 1
    sget-boolean v0, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->sIso:Z
    if-eqz v0, :no
    sget-boolean v0, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->sSkipInitialZeroSeek:Z
    if-eqz v0, :no
    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->sSkipInitialZeroSeek:Z
    if-nez p0, :no
    const/4 v0, 0x1
    return v0
    :no
    const/4 v0, 0x0
    return v0
.end method

.method public static declared-synchronized close()V
    .locals 0
    invoke-static {}, Lcom/archos/mediacenter/video/player/WeakStartProxy;->cancel()V
    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->nativeClose()V
    return-void
.end method
'''


DIRECT_RANGE_HTTP = r'''.class public final Lcom/archos/mediacenter/video/player/DirectRangeHttp;
.super Ljava/lang/Object;
.source "DirectRangeHttp.java"

.method private constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public static open(Ljava/lang/String;Ljava/lang/String;J)Ljava/net/HttpURLConnection;
    .locals 14
    if-eqz p0, :fail
    new-instance v0, Ljava/net/URL;
    invoke-direct {v0, p0}, Ljava/net/URL;-><init>(Ljava/lang/String;)V
    move-object v1, v0
    const/4 v2, 0x0
    # NOVA_STARTUP_DEEP_V1: bounded first attempt and canonical slow fallback.
    const/4 v10, 0x0

    :redirect_loop
    const/4 v3, 0x6
    if-ge v2, v3, :fail
    invoke-virtual {v1}, Ljava/net/URL;->openConnection()Ljava/net/URLConnection;
    move-result-object v4
    check-cast v4, Ljava/net/HttpURLConnection;
    const/4 v5, 0x0
    invoke-virtual {v4, v5}, Ljava/net/HttpURLConnection;->setInstanceFollowRedirects(Z)V
    const/16 v5, 0x2710
    if-nez v10, :full_timeout
    const/16 v5, 0xbb8
    :full_timeout
    invoke-virtual {v4, v5}, Ljava/net/URLConnection;->setConnectTimeout(I)V
    invoke-virtual {v4, v5}, Ljava/net/URLConnection;->setReadTimeout(I)V
    const-string v5, "GET"
    invoke-virtual {v4, v5}, Ljava/net/HttpURLConnection;->setRequestMethod(Ljava/lang/String;)V
    new-instance v8, Ljava/lang/StringBuilder;
    invoke-direct {v8}, Ljava/lang/StringBuilder;-><init>()V
    const-string v9, "bytes="
    invoke-virtual {v8, v9}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v8
    move-wide/from16 v11, p2
    invoke-virtual {v8, v11, v12}, Ljava/lang/StringBuilder;->append(J)Ljava/lang/StringBuilder;
    move-result-object v8
    const-string v9, "-"
    invoke-virtual {v8, v9}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v8
    invoke-virtual {v8}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v9
    const-string v5, "Range"
    invoke-virtual {v4, v5, v9}, Ljava/net/URLConnection;->setRequestProperty(Ljava/lang/String;Ljava/lang/String;)V
    if-eqz p1, :response
    invoke-virtual {p1}, Ljava/lang/String;->isEmpty()Z
    move-result v5
    if-nez v5, :response
    invoke-static {v0, v1}, Lcom/archos/mediacenter/video/player/DirectRedirectResolver;->sameOrigin(Ljava/net/URL;Ljava/net/URL;)Z
    move-result v5
    if-eqz v5, :response
    const-string v5, "Authorization"
    invoke-virtual {v4, v5, p1}, Ljava/net/URLConnection;->setRequestProperty(Ljava/lang/String;Ljava/lang/String;)V

    :response
    :try_response_start
    invoke-virtual {v4}, Ljava/net/HttpURLConnection;->getResponseCode()I
    move-result v6
    :try_response_end
    .catch Ljava/net/SocketTimeoutException; {:try_response_start .. :try_response_end} :retry_stalled
    const/16 v7, 0x12d
    if-eq v6, v7, :redirect
    const/16 v7, 0x12e
    if-eq v6, v7, :redirect
    const/16 v7, 0x12f
    if-eq v6, v7, :redirect
    const/16 v7, 0x133
    if-eq v6, v7, :redirect
    const/16 v7, 0x134
    if-eq v6, v7, :redirect
    return-object v4

    :redirect
    const-string v7, "Location"
    invoke-virtual {v4, v7}, Ljava/net/URLConnection;->getHeaderField(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v7
    invoke-virtual {v4}, Ljava/net/HttpURLConnection;->disconnect()V
    if-eqz v7, :fail
    new-instance v8, Ljava/net/URL;
    invoke-direct {v8, v1, v7}, Ljava/net/URL;-><init>(Ljava/net/URL;Ljava/lang/String;)V
    move-object v1, v8
    const/4 v10, 0x0
    add-int/lit8 v2, v2, 0x1
    goto :redirect_loop

    :retry_stalled
    move-exception v7
    invoke-virtual {v4}, Ljava/net/HttpURLConnection;->disconnect()V
    if-nez v10, :fail
    const/4 v10, 0x1
    goto :redirect_loop

    :fail
    const/4 v0, 0x0
    return-object v0
.end method

# Real Android app_process smoke entrypoint: checks that a redirect token is
# used once by the *actual rebuilt Smali*, and that the returned bytes match.
.method public static main([Ljava/lang/String;)V
    .locals 11
    const/4 v0, 0x0
    aget-object v1, p0, v0
    const/4 v0, 0x1
    aget-object v2, p0, v0
    const/4 v0, 0x2
    aget-object v6, p0, v0
    invoke-static {v6}, Ljava/lang/Long;->parseLong(Ljava/lang/String;)J
    move-result-wide v3
    invoke-static {v1, v2, v3, v4}, Lcom/archos/mediacenter/video/player/DirectRangeHttp;->open(Ljava/lang/String;Ljava/lang/String;J)Ljava/net/HttpURLConnection;
    move-result-object v5
    if-eqz v5, :failure
    invoke-virtual {v5}, Ljava/net/HttpURLConnection;->getResponseCode()I
    move-result v6
    const/16 v7, 0xce
    if-ne v6, v7, :failure
    invoke-virtual {v5}, Ljava/net/URLConnection;->getInputStream()Ljava/io/InputStream;
    move-result-object v6
    const/4 v0, 0x1
    new-array v7, v0, [B
    const/4 v8, 0x0
    invoke-virtual {v6, v7, v8, v0}, Ljava/io/InputStream;->read([BII)I
    move-result v9
    if-ne v9, v0, :failure
    aget-byte v9, v7, v8
    and-int/lit16 v9, v9, 0xff
    const/4 v0, 0x3
    aget-object v10, p0, v0
    invoke-static {v10}, Ljava/lang/Integer;->parseInt(Ljava/lang/String;)I
    move-result v10
    if-ne v9, v10, :failure
    invoke-virtual {v6}, Ljava/io/InputStream;->close()V
    invoke-virtual {v5}, Ljava/net/HttpURLConnection;->disconnect()V
    sget-object v0, Ljava/lang/System;->out:Ljava/io/PrintStream;
    const-string v1, "NOVA_SINGLE_GET_ANDROID_PASS"
    invoke-virtual {v0, v1}, Ljava/io/PrintStream;->println(Ljava/lang/String;)V
    return-void
    :failure
    new-instance v0, Ljava/lang/RuntimeException;
    const-string v1, "NOVA_SINGLE_GET_ANDROID_FAILED"
    invoke-direct {v0, v1}, Ljava/lang/RuntimeException;-><init>(Ljava/lang/String;)V
    throw v0
.end method

'''

PROXY_RESOLVE = r'''
.method public static resolve(Landroid/net/Uri;)Landroid/net/Uri;
    .locals 16
    if-eqz p0, :return_original
    # Already resolved on a background worker: never close/reopen it on UI.
    move-object/from16 v6, p0
    invoke-virtual {v6}, Landroid/net/Uri;->getScheme()Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :return_original
    const-string v1, "novatransport"
    invoke-virtual {v0, v1}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v1
    if-nez v1, :return_original
    const-string v1, "webdav"
    invoke-virtual {v0, v1}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v1
    if-nez v1, :open_direct
    const-string v1, "webdavs"
    invoke-virtual {v0, v1}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v1
    if-eqz v1, :return_original
    :open_direct
    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->nativeClose()V
    move-object/from16 v6, p0
    invoke-static {v6}, Lcom/archos/filecorelibrary/webdav/WebdavFile2;->uriToHttp(Landroid/net/Uri;)Landroid/net/Uri;
    move-result-object v1
    if-eqz v1, :fail
    invoke-virtual {v1}, Landroid/net/Uri;->toString()Ljava/lang/String;
    move-result-object v2
    const-string v3, ""
    invoke-static {}, Lcom/archos/filecorelibrary/samba/NetworkCredentialsDatabase;->getInstance()Lcom/archos/filecorelibrary/samba/NetworkCredentialsDatabase;
    move-result-object v4
    move-object/from16 v6, p0
    invoke-virtual {v6}, Landroid/net/Uri;->toString()Ljava/lang/String;
    move-result-object v5
    invoke-virtual {v4, v5}, Lcom/archos/filecorelibrary/samba/NetworkCredentialsDatabase;->getCredential(Ljava/lang/String;)Lcom/archos/filecorelibrary/samba/NetworkCredentialsDatabase$Credential;
    move-result-object v6
    if-nez v6, :cred_ready
    invoke-virtual {v4, v2}, Lcom/archos/filecorelibrary/samba/NetworkCredentialsDatabase;->getCredential(Ljava/lang/String;)Lcom/archos/filecorelibrary/samba/NetworkCredentialsDatabase$Credential;
    move-result-object v6
    :cred_ready
    if-eqz v6, :open
    invoke-virtual {v6}, Lcom/archos/filecorelibrary/samba/NetworkCredentialsDatabase$Credential;->getUsername()Ljava/lang/String;
    move-result-object v7
    invoke-virtual {v6}, Lcom/archos/filecorelibrary/samba/NetworkCredentialsDatabase$Credential;->getPassword()Ljava/lang/String;
    move-result-object v8
    if-eqz v7, :open
    if-eqz v8, :open
    new-instance v9, Ljava/lang/StringBuilder;
    invoke-direct {v9}, Ljava/lang/StringBuilder;-><init>()V
    invoke-virtual {v9, v7}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v9
    const-string v10, ":"
    invoke-virtual {v9, v10}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v9
    invoke-virtual {v9, v8}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v9
    invoke-virtual {v9}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v9
    sget-object v10, Ljava/nio/charset/StandardCharsets;->UTF_8:Ljava/nio/charset/Charset;
    invoke-virtual {v9, v10}, Ljava/lang/String;->getBytes(Ljava/nio/charset/Charset;)[B
    move-result-object v9
    const/4 v10, 0x2
    invoke-static {v9, v10}, Landroid/util/Base64;->encodeToString([BI)Ljava/lang/String;
    move-result-object v9
    new-instance v10, Ljava/lang/StringBuilder;
    invoke-direct {v10}, Ljava/lang/StringBuilder;-><init>()V
    const-string v11, "Basic "
    invoke-virtual {v10, v11}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v10
    invoke-virtual {v10, v9}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v10
    invoke-virtual {v10}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v3
    :open
    # Preserve canonical logical WebDAV origin and its own-origin credential.
    # The final CDN redirect may expire during long playback.
    move-object v14, v2
    move-object v15, v3
    # Only MKV gets a live single Range GET; TS MP4 ISO use Run687 resolver.
    move-object/from16 v6, p0
    invoke-virtual {v6}, Landroid/net/Uri;->getPath()Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :nova_legacy_redirect
    sget-object v13, Ljava/util/Locale;->ROOT:Ljava/util/Locale;
    invoke-virtual {v0, v13}, Ljava/lang/String;->toLowerCase(Ljava/util/Locale;)Ljava/lang/String;
    move-result-object v0
    const-string v13, ".mkv"
    invoke-virtual {v0, v13}, Ljava/lang/String;->endsWith(Ljava/lang/String;)Z
    move-result v0
    if-eqz v0, :nova_legacy_redirect
    goto :nova_mkv_single_get
    :nova_legacy_redirect
    invoke-static {v2, v3}, Lcom/archos/mediacenter/video/player/DirectRedirectResolver;->resolve(Ljava/lang/String;Ljava/lang/String;)[Ljava/lang/String;
    move-result-object v12
    if-eqz v12, :fail
    const/4 v13, 0x0
    aget-object v2, v12, v13
    const/4 v13, 0x1
    aget-object v3, v12, v13
    if-eqz v3, :no_final_auth
    invoke-virtual {v3}, Ljava/lang/String;->isEmpty()Z
    move-result v13
    if-nez v13, :no_final_auth
    new-instance v10, Ljava/lang/StringBuilder;
    invoke-direct {v10}, Ljava/lang/StringBuilder;-><init>()V
    const-string v11, "Authorization: "
    invoke-virtual {v10, v11}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v10
    invoke-virtual {v10, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v10
    const-string v11, "\r\n"
    invoke-virtual {v10, v11}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v10
    invoke-virtual {v10}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v3
    goto :native_open
    :no_final_auth
    const-string v3, ""
    :native_open
    # Avoid races with another pending source changing global sIso.
    move-object/from16 v6, p0
    invoke-virtual {v6}, Landroid/net/Uri;->getPath()Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :native_not_iso
    sget-object v13, Ljava/util/Locale;->ROOT:Ljava/util/Locale;
    invoke-virtual {v0, v13}, Ljava/lang/String;->toLowerCase(Ljava/util/Locale;)Ljava/lang/String;
    move-result-object v0
    const-string v13, ".iso"
    invoke-virtual {v0, v13}, Ljava/lang/String;->endsWith(Ljava/lang/String;)Z
    move-result v0
    goto :native_iso_ready
    :native_not_iso
    const/4 v0, 0x0
    :native_iso_ready
    invoke-static {v2, v3, v0, v14, v15}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->nativeOpen(Ljava/lang/String;Ljava/lang/String;ZLjava/lang/String;Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2
    if-eqz v2, :fail
    invoke-static {v2}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;
    move-result-object p0
    return-object p0
    :nova_mkv_single_get
    const/4 v0, 0x0
    move-object v2, v14
    const-string v3, ""
    goto :native_iso_ready
    :fail
    new-instance v0, Ljava/lang/RuntimeException;
    const-string v1, "Unable to open direct native transport"
    invoke-direct {v0, v1}, Ljava/lang/RuntimeException;-><init>(Ljava/lang/String;)V
    throw v0
    :return_original
    return-object p0
.end method

.method private static native nativeOpen(Ljava/lang/String;Ljava/lang/String;ZLjava/lang/String;Ljava/lang/String;)Ljava/lang/String;
.end method
.method public static native nativeClose()V
.end method
'''


WEAK_START = r'''.class public final Lcom/archos/mediacenter/video/player/WeakStartProxy;
.super Ljava/lang/Object;
.implements Ljava/lang/Runnable;
.source "WeakStartProxy.java"

.field private static sGeneration:I
.field private final mPlayer:Lcom/archos/mediacenter/video/player/Player;
.field private final mSource:Landroid/net/Uri;
.field private final mGeneration:I
.field private mResolved:Landroid/net/Uri;

.method private constructor <init>(Lcom/archos/mediacenter/video/player/Player;Landroid/net/Uri;I)V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    iput-object p1, p0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->mPlayer:Lcom/archos/mediacenter/video/player/Player;
    iput-object p2, p0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->mSource:Landroid/net/Uri;
    iput p3, p0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->mGeneration:I
    return-void
.end method

.method private static declared-synchronized next()I
    .locals 1
    sget v0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->sGeneration:I
    add-int/lit8 v0, v0, 0x1
    sput v0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->sGeneration:I
    return v0
.end method

.method public static declared-synchronized cancel()V
    .locals 1
    sget v0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->sGeneration:I
    add-int/lit8 v0, v0, 0x1
    sput v0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->sGeneration:I
    return-void
.end method

.method private static declared-synchronized current(I)Z
    .locals 1
    sget v0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->sGeneration:I
    if-ne p0, v0, :stale
    const/4 v0, 0x1
    return v0
    :stale
    const/4 v0, 0x0
    return v0
.end method

.method public static maybeStart(Lcom/archos/mediacenter/video/player/Player;Landroid/net/Uri;)Z
    .locals 5
    if-eqz p1, :normal
    invoke-virtual {p1}, Landroid/net/Uri;->getScheme()Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :normal
    const-string v1, "webdav"
    invoke-virtual {v0, v1}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-nez v2, :remote
    const-string v1, "webdavs"
    invoke-virtual {v0, v1}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-eqz v2, :normal
    :remote
    invoke-static {}, Lcom/archos/mediacenter/video/player/WeakStartProxy;->next()I
    move-result v3
    new-instance v4, Lcom/archos/mediacenter/video/player/WeakStartProxy;
    invoke-direct {v4, p0, p1, v3}, Lcom/archos/mediacenter/video/player/WeakStartProxy;-><init>(Lcom/archos/mediacenter/video/player/Player;Landroid/net/Uri;I)V
    new-instance v0, Ljava/lang/Thread;
    invoke-direct {v0, v4}, Ljava/lang/Thread;-><init>(Ljava/lang/Runnable;)V
    invoke-virtual {v0}, Ljava/lang/Thread;->start()V
    const/4 v0, 0x1
    return v0
    :normal
    # A resolved URI must KEEP its newly opened native session.
    if-eqz p1, :cancel_previous
    invoke-virtual {p1}, Landroid/net/Uri;->getScheme()Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :cancel_previous
    const-string v1, "novatransport"
    invoke-virtual {v0, v1}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-nez v2, :continue_normal
    :cancel_previous
    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->close()V
    :continue_normal
    const/4 v0, 0x0
    return v0
.end method

.method public run()V
    .locals 6
    invoke-static {}, Landroid/os/Looper;->myLooper()Landroid/os/Looper;
    move-result-object v0
    invoke-static {}, Landroid/os/Looper;->getMainLooper()Landroid/os/Looper;
    move-result-object v1
    if-eq v0, v1, :apply

    :background_retry
    iget v0, p0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->mGeneration:I
    invoke-static {v0}, Lcom/archos/mediacenter/video/player/WeakStartProxy;->current(I)Z
    move-result v0
    if-eqz v0, :done
    iget-object v0, p0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->mSource:Landroid/net/Uri;
    invoke-static {v0}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->armForUri(Landroid/net/Uri;)V
    :try_start
    invoke-static {v0}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->resolve(Landroid/net/Uri;)Landroid/net/Uri;
    move-result-object v1
    iput-object v1, p0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->mResolved:Landroid/net/Uri;
    :try_end
    .catch Ljava/lang/Exception; {:try_start .. :try_end} :retry_open
    goto :post_main
    :retry_open
    move-exception v1
    const-string v2, "NOVA_WEAKNET"
    const-string v3, "Waiting for network source; retrying"
    invoke-static {v2, v3, v1}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I
    move-result v2
    iget v0, p0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->mGeneration:I
    invoke-static {v0}, Lcom/archos/mediacenter/video/player/WeakStartProxy;->current(I)Z
    move-result v0
    if-eqz v0, :done
    const-wide/16 v2, 0x3e8
    invoke-static {v2, v3}, Landroid/os/SystemClock;->sleep(J)V
    goto :background_retry
    :post_main
    new-instance v0, Landroid/os/Handler;
    invoke-static {}, Landroid/os/Looper;->getMainLooper()Landroid/os/Looper;
    move-result-object v1
    invoke-direct {v0, v1}, Landroid/os/Handler;-><init>(Landroid/os/Looper;)V
    invoke-virtual {v0, p0}, Landroid/os/Handler;->post(Ljava/lang/Runnable;)Z
    move-result v1
    return-void

    :apply
    iget v0, p0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->mGeneration:I
    invoke-static {v0}, Lcom/archos/mediacenter/video/player/WeakStartProxy;->current(I)Z
    move-result v0
    if-eqz v0, :done
    iget-object v0, p0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->mResolved:Landroid/net/Uri;
    if-eqz v0, :fail_main
    iget-object v1, p0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->mPlayer:Lcom/archos/mediacenter/video/player/Player;
    const/4 v2, 0x0
    invoke-virtual {v1, v0, v2}, Lcom/archos/mediacenter/video/player/Player;->setVideoURI(Landroid/net/Uri;Ljava/util/Map;)V
    return-void
    :fail_main
    iget-object v0, p0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->mPlayer:Lcom/archos/mediacenter/video/player/Player;
    const/4 v1, 0x0
    const/4 v2, 0x1
    const/4 v3, 0x0
    invoke-virtual {v0, v1, v2, v3, v1}, Lcom/archos/mediacenter/video/player/Player;->onError(Lcom/archos/medialib/IMediaPlayer;IILjava/lang/String;)Z
    move-result v0
    :done
    return-void
.end method
'''

FACTORY = r'''.class public final Lcom/archos/mediacenter/video/player/DirectPlayerFactory;
.super Ljava/lang/Object;
.source "DirectPlayerFactory.java"

.method private constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public static create(Landroid/content/Context;Z)Lcom/archos/medialib/IMediaPlayer;
    .locals 2
    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->shouldForceAvos()Z
    move-result v0
    if-eqz v0, :normal
    const/4 v0, 0x1
    invoke-static {p0, v0}, Lcom/archos/medialib/MediaFactory;->createPlayer(Landroid/content/Context;Z)Lcom/archos/medialib/IMediaPlayer;
    move-result-object v0
    instance-of v1, v0, Lcom/archos/medialib/AvosMediaPlayer;
    if-eqz v1, :return_player
    if-nez p1, :return_player
    const/4 v1, 0x0
    invoke-static {v1}, Lcom/archos/medialib/LibAvos;->setDecoder(I)V
    :return_player
    return-object v0
    :normal
    invoke-static {p0, p1}, Lcom/archos/medialib/MediaFactory;->createPlayer(Landroid/content/Context;Z)Lcom/archos/medialib/IMediaPlayer;
    move-result-object v0
    return-object v0
.end method

.method public static seekTo(Lcom/archos/mediacenter/video/player/Player;I)V
    .locals 3
    # Existing ISO one-shot rule is preserved exactly.
    invoke-static {p1}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->shouldSkipInitialZeroSeek(I)Z
    move-result v0
    if-nez v0, :done

    # NOVA_NONISO_DUP_ZERO_SKIP_V1: only PlayerService startup position
    # invokes this wrapper. User DPAD/manual seek calls Player directly.
    if-nez p1, :delegate
    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->isNonIsoDirectWebdav()Z
    move-result v0
    if-eqz v0, :delegate
    invoke-virtual {p0}, Lcom/archos/mediacenter/video/player/Player;->isInPlaybackState()Z
    move-result v0
    if-eqz v0, :delegate
    invoke-virtual {p0}, Lcom/archos/mediacenter/video/player/Player;->isBusy()Z
    move-result v0
    if-nez v0, :delegate
    invoke-virtual {p0}, Lcom/archos/mediacenter/video/player/Player;->getDuration()I
    move-result v0
    if-lez v0, :delegate
    invoke-virtual {p0}, Lcom/archos/mediacenter/video/player/Player;->getCurrentPosition()I
    move-result v0
    if-nez v0, :delegate

    # Retain existing MKV keyframe, decoder and RAW buffer. Normal
    # PlayerService startup continues after this single redundant call.
    const-string v0, "NovaStartupSeek"
    const-string v1, "NOVA_NONISO_DUP_ZERO_SKIP_V1: prepared 0ms; preserve RAW and begin playback"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    move-result v2
    goto :done

    :delegate
    invoke-virtual {p0, p1}, Lcom/archos/mediacenter/video/player/Player;->seekTo(I)V
    :done
    return-void
.end method
'''

REDIRECT_RESOLVER = r'''.class public final Lcom/archos/mediacenter/video/player/DirectRedirectResolver;
.super Ljava/lang/Object;
.source "DirectRedirectResolver.java"

.method private constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public static sameOrigin(Ljava/net/URL;Ljava/net/URL;)Z
    .locals 4
    if-eqz p0, :no
    if-eqz p1, :no
    invoke-virtual {p0}, Ljava/net/URL;->getProtocol()Ljava/lang/String;
    move-result-object v0
    invoke-virtual {p1}, Ljava/net/URL;->getProtocol()Ljava/lang/String;
    move-result-object v1
    if-eqz v0, :no
    if-eqz v1, :no
    invoke-virtual {v0, v1}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-eqz v2, :no
    invoke-virtual {p0}, Ljava/net/URL;->getHost()Ljava/lang/String;
    move-result-object v0
    invoke-virtual {p1}, Ljava/net/URL;->getHost()Ljava/lang/String;
    move-result-object v1
    if-eqz v0, :no
    if-eqz v1, :no
    invoke-virtual {v0, v1}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-eqz v2, :no
    invoke-virtual {p0}, Ljava/net/URL;->getPort()I
    move-result v0
    if-ltz v0, :p0_default
    goto :p0_done
    :p0_default
    invoke-virtual {p0}, Ljava/net/URL;->getDefaultPort()I
    move-result v0
    :p0_done
    invoke-virtual {p1}, Ljava/net/URL;->getPort()I
    move-result v1
    if-ltz v1, :p1_default
    goto :p1_done
    :p1_default
    invoke-virtual {p1}, Ljava/net/URL;->getDefaultPort()I
    move-result v1
    :p1_done
    if-ne v0, v1, :no
    const/4 v0, 0x1
    return v0
    :no
    const/4 v0, 0x0
    return v0
.end method

.method public static resolve(Ljava/lang/String;Ljava/lang/String;)[Ljava/lang/String;
    .locals 11
    if-eqz p0, :fail
    new-instance v0, Ljava/net/URL;
    invoke-direct {v0, p0}, Ljava/net/URL;-><init>(Ljava/lang/String;)V
    move-object v1, v0
    move-object v2, p1
    const/4 v3, 0x0
    # NOVA_STARTUP_FOURFIX_V1: per-hop first wait 3s, one retry with 10s.
    # Retain the old full 10s timeout as the single fallback.
    const/4 v10, 0x0
    :loop
    const/4 v4, 0x6
    if-ge v3, v4, :fail
    invoke-virtual {v1}, Ljava/net/URL;->openConnection()Ljava/net/URLConnection;
    move-result-object v4
    check-cast v4, Ljava/net/HttpURLConnection;
    const/4 v5, 0x0
    invoke-virtual {v4, v5}, Ljava/net/HttpURLConnection;->setInstanceFollowRedirects(Z)V
    const/16 v5, 0x2710
    if-nez v10, :resolver_full_read_wait
    const/16 v5, 0xbb8
    :resolver_full_read_wait
    # NOVA_STARTUP_DEEP_V1: apply the same timeout to connection + read.
    invoke-virtual {v4, v5}, Ljava/net/URLConnection;->setConnectTimeout(I)V
    invoke-virtual {v4, v5}, Ljava/net/URLConnection;->setReadTimeout(I)V
    const-string v5, "GET"
    invoke-virtual {v4, v5}, Ljava/net/HttpURLConnection;->setRequestMethod(Ljava/lang/String;)V
    const-string v5, "Range"
    const-string v6, "bytes=0-0"
    invoke-virtual {v4, v5, v6}, Ljava/net/URLConnection;->setRequestProperty(Ljava/lang/String;Ljava/lang/String;)V
    if-eqz v2, :response
    invoke-virtual {v2}, Ljava/lang/String;->isEmpty()Z
    move-result v5
    if-nez v5, :response
    invoke-static {v0, v1}, Lcom/archos/mediacenter/video/player/DirectRedirectResolver;->sameOrigin(Ljava/net/URL;Ljava/net/URL;)Z
    move-result v5
    if-eqz v5, :drop_auth
    const-string v5, "Authorization"
    invoke-virtual {v4, v5, v2}, Ljava/net/URLConnection;->setRequestProperty(Ljava/lang/String;Ljava/lang/String;)V
    goto :response
    :drop_auth
    const-string v2, ""
    :response
    :try_start_resolver_http
    invoke-virtual {v4}, Ljava/net/HttpURLConnection;->getResponseCode()I
    move-result v5
    :try_end_resolver_http
    .catch Ljava/net/SocketTimeoutException; {:try_start_resolver_http .. :try_end_resolver_http} :catch_resolver_stalled
    const/16 v6, 0xc8
    if-eq v5, v6, :success
    const/16 v6, 0xce
    if-eq v5, v6, :success
    const/16 v6, 0x12d
    if-eq v5, v6, :redirect
    const/16 v6, 0x12e
    if-eq v5, v6, :redirect
    const/16 v6, 0x12f
    if-eq v5, v6, :redirect
    const/16 v6, 0x133
    if-eq v5, v6, :redirect
    const/16 v6, 0x134
    if-eq v5, v6, :redirect
    invoke-virtual {v4}, Ljava/net/HttpURLConnection;->disconnect()V
    goto :fail
    :redirect
    const-string v6, "Location"
    invoke-virtual {v4, v6}, Ljava/net/URLConnection;->getHeaderField(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v6
    if-eqz v6, :redirect_fail
    new-instance v7, Ljava/net/URL;
    invoke-direct {v7, v1, v6}, Ljava/net/URL;-><init>(Ljava/net/URL;Ljava/lang/String;)V
    invoke-static {v0, v7}, Lcom/archos/mediacenter/video/player/DirectRedirectResolver;->sameOrigin(Ljava/net/URL;Ljava/net/URL;)Z
    move-result v8
    if-nez v8, :keep_auth
    const-string v2, ""
    :keep_auth
    invoke-virtual {v4}, Ljava/net/HttpURLConnection;->disconnect()V
    move-object v1, v7
    const/4 v10, 0x0
    add-int/lit8 v3, v3, 0x1
    goto :loop
    :redirect_fail
    invoke-virtual {v4}, Ljava/net/HttpURLConnection;->disconnect()V
    goto :fail
    :success
    const/4 v5, 0x2
    new-array v5, v5, [Ljava/lang/String;
    const/4 v6, 0x0
    invoke-virtual {v1}, Ljava/net/URL;->toString()Ljava/lang/String;
    move-result-object v7
    aput-object v7, v5, v6
    const/4 v6, 0x1
    aput-object v2, v5, v6
    invoke-virtual {v4}, Ljava/net/HttpURLConnection;->disconnect()V
    return-object v5
    :fail
    const/4 v0, 0x0
    return-object v0
    :catch_resolver_stalled
    move-exception v6
    invoke-virtual {v4}, Ljava/net/HttpURLConnection;->disconnect()V
    if-nez v10, :fail
    const/4 v10, 0x1
    goto :loop
.end method
'''

def patch_player(text):
    methods=[m for m in METHOD_RE.finditer(text)
             if "NetworkInitialization;->awaitReadyForSmb" in m.group(0)
             and "IMediaPlayer;->setDataSource" in m.group(0)]
    if len(methods)!=1:
        raise RuntimeError("player source method ambiguous")
    m=methods[0]
    body=m.group(0)
    a=AWAIT_RE.search(body)
    if not a:
        raise RuntimeError("awaitReadyForSmb anchor missing")
    uri=a.group("regs").strip().split("..",1)[0].split(",",1)[0].strip()
    inject=(a.group(0)+"\n\n"+a.group("indent")
        +f"invoke-static {{{uri}}}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->resolve(Landroid/net/Uri;)Landroid/net/Uri;\n"
        +a.group("indent")+f"move-result-object {uri}")
    text=text[:m.start()]+body[:a.start()]+inject+body[a.end():]+text[m.end():]

    targets=[m for m in METHOD_RE.finditer(text)
             if m.group(0).splitlines()[0].startswith(
                 ".method public setVideoURI(Landroid/net/Uri;Ljava/util/Map;)V")]
    if len(targets)!=1:
        raise RuntimeError("setVideoURI missing")
    m=targets[0]
    lines=m.group(0).splitlines()
    ri=next(i for i,l in enumerate(lines)
            if l.strip().startswith((".locals ", ".registers ")))
    lines[ri+1:ri+1]=[
        "",
        "    invoke-static {p1}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->armForUri(Landroid/net/Uri;)V",
    ]
    text=text[:m.start()]+"\n".join(lines)+text[m.end():]

    old=("Lcom/archos/medialib/MediaFactory;->createPlayer"
         "(Landroid/content/Context;Z)Lcom/archos/medialib/IMediaPlayer;")
    new=("Lcom/archos/mediacenter/video/player/DirectPlayerFactory;->create"
         "(Landroid/content/Context;Z)Lcom/archos/medialib/IMediaPlayer;")
    if text.count(old)!=1:
        raise RuntimeError("player factory anchor changed")
    return patch_player_uri_gate(text.replace(old,new,1))


def patch_player_uri_gate(text):
    """Gate WebDAV at the verified Player.setVideoURI entry point.

    This is independent of how the current upstream APK compiles
    PlayerService.onStreamingUriOK(). The remote job runs on a worker and
    reenters setVideoURI with the resolved novatransport:// URL on UI.
    """
    targets=[m for m in METHOD_RE.finditer(text)
             if m.group(0).splitlines()[0].startswith(
                 ".method public setVideoURI(Landroid/net/Uri;Ljava/util/Map;)V")]
    if len(targets)!=1:
        raise RuntimeError("Player.setVideoURI weak-start gate ambiguous")
    m=targets[0]
    lines=m.group(0).splitlines()
    ri=next(i for i,l in enumerate(lines)
            if l.strip().startswith((".locals ", ".registers ")))
    method_declaration=lines[ri].strip()
    if method_declaration.startswith(".locals "):
        old_locals=int(method_declaration.split()[1])
        lines[ri]="    .locals "+str(old_locals+1)
    else:
        old_registers=int(method_declaration.split()[1])
        # instance method p0 + Uri p1 + Map p2: exactly 3 parameter words
        if old_registers < 3:
            raise RuntimeError("Invalid Player.setVideoURI register count")
        old_locals=old_registers-3
        lines[ri]="    .registers "+str(old_registers+1)
    tmp=f"v{old_locals}"
    lines[ri+1:ri+1]=[
        "",
        "    # NOVA_WEAK_START: do not run network/ISO scan synchronously on UI.",
        "    invoke-static/range {p0 .. p1}, Lcom/archos/mediacenter/video/player/WeakStartProxy;->maybeStart(Lcom/archos/mediacenter/video/player/Player;Landroid/net/Uri;)Z",
        f"    move-result {tmp}",
        f"    if-eqz {tmp}, :nova_weak_start_sync",
        "    return-void",
        "    :nova_weak_start_sync",
    ]
    return text[:m.start()]+"\n".join(lines)+text[m.end():]


def patch_service_async_start(text):
    """Move WebDAV connection/ISO title scan off the Android main thread.

    Only the already-existing initial setVideoURI(null headers) is rerouted.
    Playback state, decoder setup, and normal non-WebDAV start stay on UI.
    """
    ms=[m for m in METHOD_RE.finditer(text)
        if " onStreamingUriOK()V" in m.group(0).splitlines()[0]]
    if len(ms)!=1:
        raise RuntimeError("onStreamingUriOK missing")
    m=ms[0]
    body=m.group(0)
    pattern=re.compile(
        r'(?P<op>invoke-virtual) \{(?P<regs>[^}]+)\}, '
        r'Lcom/archos/mediacenter/video/player/Player;->setVideoURI'
        r'\(Landroid/net/Uri;Ljava/util/Map;\)V')
    hits=list(pattern.finditer(body))
    if len(hits)!=1:
        raise RuntimeError("onStreamingUriOK initial video open ambiguous")
    hit=hits[0]
    regs=[part.strip() for part in hit.group("regs").split(",")]
    if len(regs)!=3:
        raise RuntimeError("onStreamingUriOK must pass Player, URI, null-map")
    new=("invoke-static {"+regs[0]+", "+regs[1]+"}, "
         "Lcom/archos/mediacenter/video/player/WeakStartProxy;->start"
         "(Lcom/archos/mediacenter/video/player/Player;Landroid/net/Uri;)V")
    body=body[:hit.start()]+new+body[hit.end():]
    return text[:m.start()]+body+text[m.end():]

def _startup_seek_position_reg(invoke_op, raw_regs):
    """Find the position operand without allocating or overwriting registers."""
    if invoke_op.endswith("/range"):
        m = re.fullmatch(r'([vp])(\d+)\s*\.\.\s*([vp])(\d+)', raw_regs)
        if not m or m.group(1) != m.group(3) or int(m.group(4)) != int(m.group(2)) + 1:
            raise RuntimeError("unexpected startup Seek /range registers")
        return m.group(3) + m.group(4)
    regs = [x.strip() for x in raw_regs.split(",")]
    if len(regs) != 2 or not all(re.fullmatch(r'[vp]\d+', x) for x in regs):
        raise RuntimeError("unexpected startup Seek registers")
    return regs[1]


def patch_service(text):
    """Do NOT originate an unnecessary zero-position startup seek.

    Every format uses postPreparedAndVideoDb. The 0ms fresh-start position
    is already the stream's natural initial position. All positive resume
    requests still delegate to the EXACT main-branch factory and all other
    Player.seekTo call sites remain untouched.
    """
    wrapper=("Lcom/archos/mediacenter/video/player/DirectPlayerFactory;->seekTo"
             "(Lcom/archos/mediacenter/video/player/Player;I)V")
    methods=[m for m in METHOD_RE.finditer(text)
             if " postPreparedAndVideoDb()V" in m.group(0).splitlines()[0]]
    if len(methods)!=1:
        raise RuntimeError("postPreparedAndVideoDb missing/ambiguous")
    m=methods[0]
    body=m.group(0)
    if "NOVA_STARTUP_ZERO_NO_REQUEST_V1" in body:
        raise RuntimeError("startup zero source patch already applied")
    pat=re.compile(
        r'(?P<indent>[ \t]*)(?P<op>invoke-virtual(?:/range)?) '
        r'\{(?P<regs>[^}]+)\}, '
        r'Lcom/archos/mediacenter/video/player/Player;->seekTo\(I\)V')
    hits=list(pat.finditer(body))
    if len(hits)!=1:
        raise RuntimeError("initial seek anchor changed")
    h=hits[0]
    position=_startup_seek_position_reg(h.group("op"),h.group("regs"))
    op="invoke-static/range" if h.group("op").endswith("/range") else "invoke-static"
    indent=h.group("indent")
    label=":nova_startup_zero_no_request_done"
    if label in body:
        raise RuntimeError("startup zero label collision")
    repl=(indent+"# NOVA_STARTUP_ZERO_NO_REQUEST_V1: skip originating Seek(0)\n"
          +indent+"if-eqz "+position+", "+label+"\n"
          +indent+op+" {"+h.group("regs")+"}, "+wrapper+"\n"
          +indent+label)
    return text[:m.start()]+body[:h.start()]+repl+body[h.end():]+text[m.end():]


def patch_resume_ctx_initial_zero(text):
    """The separate pre-prepared resume context must also not emit Seek(0).

    A stopped video may queue position 0 for onPrepared when setStartTime
    is unavailable. This skips only the redundant 0ms re-seek; positive
    resume and every later user seek are entirely unchanged.
    """
    methods=[m for m in METHOD_RE.finditer(text)
             if " onPrepared()V" in m.group(0).splitlines()[0]]
    if len(methods)!=1:
        raise RuntimeError("Player$ResumeCtx.onPrepared missing/ambiguous")
    m=methods[0]
    body=m.group(0)
    if "NOVA_RESUME_ZERO_NO_REQUEST_V1" in body:
        raise RuntimeError("resume zero source patch already applied")
    pat=re.compile(
        r'(?P<indent>[ \t]*)(?P<op>invoke-virtual(?:/range)?) '
        r'\{(?P<regs>[^}]+)\}, '
        r'Lcom/archos/mediacenter/video/player/Player;->seekTo\(I\)V')
    hits=list(pat.finditer(body))
    if len(hits)!=1:
        raise RuntimeError("ResumeCtx initial seek anchor changed")
    h=hits[0]
    position=_startup_seek_position_reg(h.group("op"),h.group("regs"))
    indent=h.group("indent")
    label=":nova_resume_zero_no_request_done"
    if label in body:
        raise RuntimeError("resume zero label collision")
    repl=(indent+"# NOVA_RESUME_ZERO_NO_REQUEST_V1: 0ms is natural start\n"
          +indent+"if-eqz "+position+", "+label+"\n"
          +indent+h.group("op")+" {"+h.group("regs")+"}, "
          +"Lcom/archos/mediacenter/video/player/Player;->seekTo(I)V\n"
          +indent+label)
    return text[:m.start()]+body[:h.start()]+repl+body[h.end():]+text[m.end():]


def smali_super_descriptor(text):
    hits=[]
    for raw in text.splitlines():
        line=raw.strip()
        if not line.startswith(".super "):
            continue
        parts=line.split(None,1)
        if len(parts)==2 and parts[1].startswith("L") and parts[1].endswith(";"):
            hits.append(parts[1])
    if len(hits)!=1:
        raise RuntimeError("PlayerActivity .super descriptor ambiguous: "+repr(hits))
    return hits[0]


def patch_activity_back(text):
    methods=[m for m in METHOD_RE.finditer(text)
             if " onBackPressed()V" in m.group(0).splitlines()[0]]
    if methods:
        if len(methods)!=1:
            raise RuntimeError("PlayerActivity.onBackPressed ambiguous")
        m=methods[0]
        body=m.group(0)
        if "DirectTransportProxy;->close()V" not in body:
            lines=body.splitlines()
            ri=next(i for i,l in enumerate(lines)
                    if l.strip().startswith((".locals ", ".registers ")))
            lines[ri+1:ri+1]=[
                "",
                "    # NOVA_DIRECT_BACK_EXIT: only reached when controller did not consume BACK.",
                "    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->close()V",
            ]
            body="\n".join(lines)
            text=text[:m.start()]+body+text[m.end():]
    else:
        super_desc=smali_super_descriptor(text)
        method=f"""
.method public onBackPressed()V
    .locals 0
    # NOVA_DIRECT_BACK_EXIT: only reached when controller did not consume BACK.
    invoke-static {{}}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->close()V
    invoke-super {{p0}}, {super_desc}->onBackPressed()V
    return-void
.end method
"""
        text=text.rstrip()+"\n\n"+method.strip()+"\n"

    if "NOVA_DIRECT_BACK_EXIT" not in text:
        raise RuntimeError("PlayerActivity back exit hook missing")
    if "DirectTransportProxy;->close()V" not in text:
        raise RuntimeError("PlayerActivity back close missing")
    return text

def patch_activity_stop(text):
    methods=[m for m in METHOD_RE.finditer(text)
             if " onStop()V" in m.group(0).splitlines()[0]]
    if len(methods)!=1:
        raise RuntimeError("PlayerActivity.onStop missing")
    m=methods[0]
    body=m.group(0)
    if "DirectTransportProxy;->close()V" in body:
        raise RuntimeError("PlayerActivity direct close already present")

    lines=body.splitlines()
    ri=next((i for i,l in enumerate(lines)
             if l.strip().startswith(".locals ")), None)
    if ri is None:
        raise RuntimeError("PlayerActivity.onStop must use .locals")
    locals_count=int(lines[ri].strip().split()[1])
    tmp=f"v{locals_count}"
    lines[ri]="    .locals "+str(locals_count+1)

    stop_call=("invoke-direct {p0}, "
               "Lcom/archos/mediacenter/video/player/PlayerActivity;->stop()V")
    hits=[i for i,l in enumerate(lines) if stop_call in l]
    if len(hits)!=1:
        raise RuntimeError("PlayerActivity.onStop stop anchor changed")
    i=hits[0]
    inject=[
        "    # NOVA_DIRECT_LIFECYCLE: activity teardown owns transport close.",
        f"    iget-boolean {tmp}, p0, Lcom/archos/mediacenter/video/player/PlayerActivity;->mLaunchFloatingPlayer:Z",
        f"    if-nez {tmp}, :nova_direct_keep_transport_on_stop",
        "    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->close()V",
        "    :nova_direct_keep_transport_on_stop",
    ]
    lines[i:i]=inject
    out="\n".join(lines)
    for token in (
        "NOVA_DIRECT_LIFECYCLE",
        "mLaunchFloatingPlayer:Z",
        "DirectTransportProxy;->close()V",
        "->stop()V",
    ):
        if token not in out:
            raise RuntimeError("PlayerActivity lifecycle postcondition missing: "+token)
    if out.index("DirectTransportProxy;->close()V") > out.index(stop_call):
        raise RuntimeError("direct transport close must precede PlayerActivity.stop")
    return text[:m.start()]+out+text[m.end():]


def verify_release_ownership(text):
    # release() is also invoked by finalize() on old player instances. It must
    # never close the process-global current session: the native AVOS source
    # already aborts only its own transport_generation during stream_stop.
    methods=[m for m in METHOD_RE.finditer(text)
             if " release()V" in m.group(0).splitlines()[0]]
    if len(methods)!=1:
        raise RuntimeError("AvosMediaPlayer.release missing")
    body=methods[0].group(0)
    if "DirectTransportProxy;->close()V" in body:
        raise RuntimeError("AvosMediaPlayer.release must not close global transport")
    return text


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--apktool",type=Path,required=True)
    ap.add_argument("--native-root",type=Path,required=True)
    ap.add_argument("--work",type=Path,required=True)
    args=ap.parse_args()

    root=args.work/"direct-final"
    if root.exists():
        shutil.rmtree(root)
    run("java","-Xmx4g","-jar",args.apktool,"d","--no-debug-info","-f",
        args.source,"-o",root)

    mime=one(root.glob("smali*/com/archos/filecorelibrary/MimeUtils.smali"),"MimeUtils")
    mt=mime.read_text()
    if '"application/x-iso9660-image"' in mt:
        mt=mt.replace('"application/x-iso9660-image"','"video/x-bluray-iso"',1)
    mime.write_text(mt)

    player=one(root.glob("smali*/com/archos/mediacenter/video/player/Player.smali"),"Player")
    player.write_text(patch_player(player.read_text()))
    service=one(root.glob("smali*/com/archos/mediacenter/video/player/PlayerService.smali"),"PlayerService")
    service.write_text(patch_service(service.read_text()))
    resume=one(root.glob("smali*/com/archos/mediacenter/video/player/Player$ResumeCtx.smali"),"Player$ResumeCtx")
    resume.write_text(patch_resume_ctx_initial_zero(resume.read_text()))
    activity=one(root.glob("smali*/com/archos/mediacenter/video/player/PlayerActivity.smali"),"PlayerActivity")
    activity_text=patch_activity_back(activity.read_text())
    activity.write_text(patch_activity_stop(activity_text))
    avos=one(root.glob("smali*/com/archos/medialib/AvosMediaPlayer.smali"),"AvosMediaPlayer")
    verify_release_ownership(avos.read_text())

    smali_dir=next_smali(root)/"com/archos/mediacenter/video/player"
    smali_dir.mkdir(parents=True,exist_ok=True)
    (smali_dir/"DirectTransportProxy.smali").write_text(PROXY_HEAD+PROXY_RESOLVE)
    (smali_dir/"DirectPlayerFactory.smali").write_text(FACTORY)
    (smali_dir/"DirectRedirectResolver.smali").write_text(REDIRECT_RESOLVER)
    (smali_dir/"DirectRangeHttp.smali").write_text(DIRECT_RANGE_HTTP)
    (smali_dir/"WeakStartProxy.smali").write_text(WEAK_START)
    from startup_loading_diag_patch import apply_smali_trace
    apply_smali_trace(root)

    for abi in ("arm64-v8a","armeabi-v7a","x86","x86_64"):
        src=args.native_root/abi/"libnova_transport.so"
        if not src.is_file():
            raise RuntimeError("missing transport library for "+abi)
        dst=root/"lib"/abi/"libnova_transport.so"
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(src,dst)

    # Pass through the rebuilt AVOS libraries unchanged. Their producer and
    # playback thread schedulers are already no-ops in native source.
    for abi in ("arm64-v8a", "armeabi-v7a", "x86", "x86_64"):
        avos=root/"lib"/abi/"libavos.so"
        if not avos.is_file():
            raise RuntimeError("missing rebuilt libavos for "+abi)

    args.output.parent.mkdir(parents=True,exist_ok=True)
    run("java","-Xmx4g","-jar",args.apktool,"b",root,"-o",args.output)

    # Hard fail if the new payload accidentally contains the legacy ISO proxy.
    probe=(root/"smali_classes999"/"never")
    all_text="\n".join(p.read_text(errors="ignore")
                       for p in root.glob("smali*/com/archos/mediacenter/video/player/*.smali"))
    for forbidden in (
        "Bluray" + "IsoProxy",
        "NovaIso" + "SourceClose",
        "NovaIso" + "NativeClose",
    ):
        if forbidden in all_text:
            raise RuntimeError("legacy ISO transport residue: "+forbidden)

    print("DIRECT_TRANSPORT_APPLY=PASS")

if __name__=="__main__":
    main()
