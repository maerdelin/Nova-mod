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

def _next_smali_dir(root: Path) -> Path:
    nums = [1]
    for p in root.glob('smali_classes*'):
        try:
            nums.append(int(p.name.removeprefix('smali_classes')))
        except ValueError:
            pass
    return root / f'smali_classes{max(nums) + 1}'

def apply(root: Path, native_dir: Path, avos_dir: Path, report: Path | None = None):
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
    player.write_text(patched)

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

    copied = []
    avos_copied = []
    expected_abis = ('arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64')
    for abi in expected_abis:
        src = native_dir / abi / 'libnova_iso.so'
        if not src.is_file() or src.stat().st_size < 10000:
            raise RuntimeError('Missing/invalid native ISO bridge for ' + abi)
        dst = root / 'lib' / abi / 'libnova_iso.so'
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        copied.append({'abi': abi, 'size': dst.stat().st_size})

        avos_src = avos_dir / abi / 'libavos.so'
        if not avos_src.is_file():
            raise RuntimeError('Missing ISO-aware libavos for ' + abi)
        avos_bytes = avos_src.read_bytes()
        if not avos_bytes.startswith(b'\x7fELF'):
            raise RuntimeError('ISO-aware libavos is not ELF for ' + abi)
        if b'nova_iso=1' not in avos_bytes or b'skip_estimate_duration_from_pts' not in avos_bytes:
            raise RuntimeError('ISO-aware FFmpeg markers missing from libavos for ' + abi)
        avos_dst = root / 'lib' / abi / 'libavos.so'
        if not avos_dst.is_file():
            raise RuntimeError('Official libavos target missing for ' + abi)
        shutil.copyfile(avos_src, avos_dst)
        avos_copied.append({'abi': abi, 'size': avos_dst.stat().st_size})

    result = {
        'status': 'PASS',
        'mime': mime_status,
        'player': player_status,
        'proxy': proxy_status,
        'proxy_path': proxy_path.relative_to(root).as_posix(),
        'native': copied,
        'iso_aware_avos': avos_copied,
        'strategy': 'WebDAV StreamOverHttp -> libbluray -> ISO-marked localhost MPEG-TS -> ISO-only FFmpeg fast probe',
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + '\n')
    return result
