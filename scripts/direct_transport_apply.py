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
    .locals 1
    invoke-static {p1}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->shouldSkipInitialZeroSeek(I)Z
    move-result v0
    if-nez v0, :done
    invoke-virtual {p0, p1}, Lcom/archos/mediacenter/video/player/Player;->seekTo(I)V
    :done
    return-void
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
    return text.replace(old,new,1)

def patch_service(text):
    wrapper=("Lcom/archos/mediacenter/video/player/DirectPlayerFactory;->seekTo"
             "(Lcom/archos/mediacenter/video/player/Player;I)V")
    methods=[m for m in METHOD_RE.finditer(text)
             if " postPreparedAndVideoDb()V" in m.group(0).splitlines()[0]]
    if len(methods)!=1:
        raise RuntimeError("postPreparedAndVideoDb missing")
    m=methods[0]
    body=m.group(0)
    pat=re.compile(
        r'(?P<indent>\s*)(?P<op>invoke-virtual(?:/range)?) '
        r'\{(?P<regs>[^}]+)\}, '
        r'Lcom/archos/mediacenter/video/player/Player;->seekTo\(I\)V')
    hits=list(pat.finditer(body))
    if len(hits)!=1:
        raise RuntimeError("initial seek anchor changed")
    h=hits[0]
    op="invoke-static/range" if h.group("op").endswith("/range") else "invoke-static"
    repl=h.group("indent")+op+" {"+h.group("regs")+"}, "+wrapper
    return text[:m.start()]+body[:h.start()]+repl+body[h.end():]+text[m.end():]

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
        super_hits=re.findall(r'^\\.super\\s+(L[^;]+;)$', text, re.M)
        if len(super_hits)!=1:
            raise RuntimeError("PlayerActivity .super descriptor ambiguous")
        super_desc=super_hits[0]
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


def patch_release(text):
    methods=[m for m in METHOD_RE.finditer(text)
             if " release()V" in m.group(0).splitlines()[0]]
    if len(methods)!=1:
        raise RuntimeError("AvosMediaPlayer.release missing")
    m=methods[0]
    lines=m.group(0).splitlines()
    ri=next(i for i,l in enumerate(lines)
            if l.strip().startswith((".locals ", ".registers ")))
    lines[ri+1:ri+1]=[
        "",
        "    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->close()V",
    ]
    return text[:m.start()]+"\n".join(lines)+text[m.end():]


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
    activity=one(root.glob("smali*/com/archos/mediacenter/video/player/PlayerActivity.smali"),"PlayerActivity")
    activity_text=patch_activity_back(activity.read_text())
    activity.write_text(patch_activity_stop(activity_text))
    avos=one(root.glob("smali*/com/archos/medialib/AvosMediaPlayer.smali"),"AvosMediaPlayer")
    avos.write_text(patch_release(avos.read_text()))

    smali_dir=next_smali(root)/"com/archos/mediacenter/video/player"
    smali_dir.mkdir(parents=True,exist_ok=True)
    (smali_dir/"DirectTransportProxy.smali").write_text(PROXY_HEAD+PROXY_RESOLVE)
    (smali_dir/"DirectPlayerFactory.smali").write_text(FACTORY)

    for abi in ("arm64-v8a","armeabi-v7a","x86","x86_64"):
        src=args.native_root/abi/"libnova_transport.so"
        if not src.is_file():
            raise RuntimeError("missing transport library for "+abi)
        dst=root/"lib"/abi/"libnova_transport.so"
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(src,dst)

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
