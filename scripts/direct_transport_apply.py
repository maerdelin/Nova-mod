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
