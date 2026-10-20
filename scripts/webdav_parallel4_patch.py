#!/usr/bin/env python3
"""Patch only the shared WebDAV media copy path and optional sidecar file PUT."""
from __future__ import annotations
import json
import re
from pathlib import Path
import webdav_p012_patch

OUTER = 'Lcom/archos/filecorelibrary/StreamOverHttp;'
SESSION = 'Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;'
RANGE4 = 'Lcom/archos/filecorelibrary/NovaParallelRangeInputStream;'
SOURCE = 'Lcom/archos/filecorelibrary/NovaParallelRangeInputStream$Source;'
MANAGED = 'Lcom/archos/filecorelibrary/NovaParallelRangeInputStream$ManagedSource;'
COPY_PROTO = '(Ljava/io/InputStream;Ljava/io/OutputStream;[BJLcom/archos/filecorelibrary/StreamOverHttp$HttpSession;)V'

SESSION_METHODS = f'''
.method public openRange(J)Ljava/io/InputStream;
    .locals 4
    invoke-virtual {{p0}}, {SESSION}->novaMediaResumeEligible()Z
    move-result v0
    if-nez v0, :nova_range4_open_allowed
    new-instance v0, Ljava/io/IOException;
    const-string v1, "WebDAV Range4 request cancelled before open"
    invoke-direct {{v0, v1}}, Ljava/io/IOException;-><init>(Ljava/lang/String;)V
    throw v0
    :nova_range4_open_allowed
    iget-object v0, p0, {SESSION}->this$0:{OUTER}
    invoke-virtual {{v0}}, {OUTER}->novaGetOriginUri()Landroid/net/Uri;
    move-result-object v1
    invoke-virtual {{v0, v1}}, {OUTER}->getFileEditor(Landroid/net/Uri;)Lcom/archos/filecorelibrary/FileEditor;
    move-result-object v2
    invoke-direct {{p0}}, {SESSION}->readOptions()Lcom/archos/filecorelibrary/ReadOptions;
    move-result-object v3
    invoke-virtual {{v2, p1, p2, v3}}, Lcom/archos/filecorelibrary/FileEditor;->getInputStream(JLcom/archos/filecorelibrary/ReadOptions;)Ljava/io/InputStream;
    move-result-object v0
    return-object v0
.end method

.method public cancelled()Z
    .locals 1
    invoke-virtual {{p0}}, {SESSION}->novaMediaResumeEligible()Z
    move-result v0
    xor-int/lit8 v0, v0, 0x1
    return v0
.end method

.method public publishRange4(Ljava/io/InputStream;)V
    .locals 0
    invoke-direct {{p0, p1}}, {SESSION}->publishInput(Ljava/io/InputStream;)V
    return-void
.end method

.method public capacityOwner()Ljava/lang/Object;
    .locals 1
    iget-object v0, p0, {SESSION}->this$0:{OUTER}
    return-object v0
.end method

.method public capacityPort()I
    .locals 2
    iget-object v0, p0, {SESSION}->this$0:{OUTER}
    const/4 v1, 0x0
    invoke-virtual {{v0, v1}}, {OUTER}->getUri(Ljava/lang/String;)Landroid/net/Uri;
    move-result-object v0
    invoke-virtual {{v0}}, Landroid/net/Uri;->getPort()I
    move-result v0
    return v0
.end method

.method public novaWrapRange4(Ljava/io/InputStream;J)Ljava/io/InputStream;
    .locals 6
    move-object v0, p0
    move-object v1, p1
    iget-wide v2, p0, {SESSION}->requestedStart:J
    move-wide v4, p2
    invoke-static/range {{v0 .. v5}}, {RANGE4}->maybeWrap({SOURCE}Ljava/io/InputStream;JJ)Ljava/io/InputStream;
    move-result-object v0
    return-object v0
.end method
'''

COPY_METHOD = f'''.method private novaCopyStreamRecovering{COPY_PROTO}
    .locals 8
    move-object v0, p6
    move-object v1, p1
    move-object v2, p2
    move-object v3, p3
    invoke-virtual {{p6}}, {SESSION}->novaRequestedStart()J
    move-result-wide v4
    move-wide v6, p4
    invoke-static/range {{v0 .. v7}}, {RANGE4}->copyRecovering({SOURCE}Ljava/io/InputStream;Ljava/io/OutputStream;[BJJ)V
    return-void
.end method'''


def exactly_one(root: Path, name: str) -> Path:
    found = list(root.glob('smali*/com/archos/filecorelibrary/' + name))
    if len(found) != 1:
        raise RuntimeError(f'{name}: expected 1 decoded class, got {len(found)}')
    return found[0]


def patch_outer(src: str) -> str:
    if 'novaWrapRange4(' in src or '->copyRecovering(' in src:
        raise RuntimeError('Range4 wrapper already installed')
    if 'novaCopyStreamRecovering(' not in src or 'novaMediaResumeEligible()Z' not in src:
        raise RuntimeError('Expected midstream recovery wrapper missing')
    if 'getUri(Ljava/lang/String;)Landroid/net/Uri;' not in src:
        raise RuntimeError('Expected per-media localhost URI getter')
    anchor = f'    invoke-direct/range {{p0 .. p6}}, {OUTER}->novaCopyStreamRecovering{COPY_PROTO}'
    if src.count(anchor) != 1:
        raise RuntimeError('Expected exactly one WebDAV copy call')
    injection = (f'    invoke-virtual {{p6, p1, p4, p5}}, {SESSION}->novaWrapRange4'
                 '(Ljava/io/InputStream;J)Ljava/io/InputStream;\n    move-result-object p1\n')
    src = src.replace(anchor, injection + anchor, 1)
    pattern = r'(?ms)^\.method private novaCopyStreamRecovering' + re.escape(COPY_PROTO) + r'\n.*?^\.end method$'
    if len(re.findall(pattern, src)) != 1:
        raise RuntimeError('Expected one recoverable media copy implementation')
    return re.sub(pattern, lambda _: COPY_METHOD, src, count=1)


def patch_session(src: str) -> str:
    if f'.implements {SOURCE}' in src or f'.implements {MANAGED}' in src or 'novaWrapRange4(' in src:
        raise RuntimeError('Range4 session methods already installed')
    for token in ['novaMediaResumeEligible()Z', 'novaRequestedStart()J', 'readOptions()',
                  'requestedStart:J', 'publishInput(Ljava/io/InputStream;)V',
                  'getInputStream(JLcom/archos/filecorelibrary/ReadOptions;)']:
        if token not in src:
            raise RuntimeError('Range4 prerequisite missing: ' + token)
    match = re.search(r'(?m)^\.source [^\n]+$', src) or re.search(r'(?m)^\.super [^\n]+$', src)
    if match is None:
        raise RuntimeError('HttpSession source/super header not found')
    src = src[:match.end()] + '\n.implements ' + MANAGED + src[match.end():]
    return src.rstrip() + '\n' + SESSION_METHODS


def apply(root: Path, report: Path | None = None) -> dict:
    outer = exactly_one(root, 'StreamOverHttp.smali')
    inner = exactly_one(root, 'StreamOverHttp$HttpSession.smali')
    # Validate all transformations before replacing either media class.
    updates = [(outer, patch_outer(outer.read_text(encoding='utf-8'))),
               (inner, patch_session(inner.read_text(encoding='utf-8')))]
    sidecar = webdav_p012_patch.apply_sidecar(root)
    for path, changed in updates:
        path.write_text(changed, encoding='utf-8')
    result = {'status': 'PASS', 'workers': 4, 'chunk_bytes': 1048576,
              'scope': 'WebDAV shared media input; optional resume XML PUT',
              'on_failure': 'exact delivered offset, bounded retry, re-enter Range4',
              'on_cancel_or_denied': 'no reconnect', 'sidecar': sidecar,
              'capacity_identity': 'per-media localhost port and underlying source length',
              'log_tag': 'NOVA_RANGE4', 'real_network_verified': False}
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + '\n')
    return result

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('root', type=Path)
    p.add_argument('--report', type=Path)
    args = p.parse_args()
    print(json.dumps(apply(args.root, args.report), indent=2))
