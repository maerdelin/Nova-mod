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
    if-eqz v4, :store
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
    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->nativeClose()V
    return-void
.end method
'''


PROXY_RESOLVE = r'''
.method public static declared-synchronized resolve(Landroid/net/Uri;)Landroid/net/Uri;
    .locals 12
    if-eqz p0, :return_original
    sget-boolean v0, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->sForceAvos:Z
    if-eqz v0, :return_original
    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->nativeClose()V
    invoke-static {p0}, Lcom/archos/filecorelibrary/webdav/WebdavFile2;->uriToHttp(Landroid/net/Uri;)Landroid/net/Uri;
    move-result-object v1
    if-eqz v1, :fail
    invoke-virtual {v1}, Landroid/net/Uri;->toString()Ljava/lang/String;
    move-result-object v2
    const-string v3, ""
    invoke-static {}, Lcom/archos/filecorelibrary/samba/NetworkCredentialsDatabase;->getInstance()Lcom/archos/filecorelibrary/samba/NetworkCredentialsDatabase;
    move-result-object v4
    invoke-virtual {p0}, Landroid/net/Uri;->toString()Ljava/lang/String;
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
    const-string v11, "Authorization: Basic "
    invoke-virtual {v10, v11}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v10
    invoke-virtual {v10, v9}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v10
    const-string v11, "\r\n"
    invoke-virtual {v10, v11}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v10
    invoke-virtual {v10}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v3
    :open
    sget-boolean v0, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->sIso:Z
    invoke-static {v2, v3, v0}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->nativeOpen(Ljava/lang/String;Ljava/lang/String;Z)Ljava/lang/String;
    move-result-object v2
    if-eqz v2, :fail
    invoke-static {v2}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;
    move-result-object p0
    return-object p0
    :fail
    new-instance v0, Ljava/lang/RuntimeException;
    const-string v1, "Unable to open direct native transport"
    invoke-direct {v0, v1}, Ljava/lang/RuntimeException;-><init>(Ljava/lang/String;)V
    throw v0
    :return_original
    return-object p0
.end method

.method private static native nativeOpen(Ljava/lang/String;Ljava/lang/String;Z)Ljava/lang/String;
.end method
.method public static native nativeClose()V
.end method
'''
