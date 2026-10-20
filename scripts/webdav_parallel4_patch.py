#!/usr/bin/env python3
"""Patch the common WebDAV media input stream only; no decoding changes."""
from __future__ import annotations
import json
import re
from pathlib import Path

OUTER = 'Lcom/archos/filecorelibrary/StreamOverHttp;'
SESSION = 'Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;'
RANGE4 = 'Lcom/archos/filecorelibrary/NovaParallelRangeInputStream;'
SOURCE = 'Lcom/archos/filecorelibrary/NovaParallelRangeInputStream$Source;'

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

def exactly_one(root: Path, name: str) -> Path:
    found = list(root.glob('smali*/com/archos/filecorelibrary/' + name))
    if len(found) != 1:
        raise RuntimeError(f'{name}: expected 1 decoded class, got {len(found)}')
    return found[0]

def patch_outer(src: str) -> str:
    if 'novaWrapRange4(' in src:
        raise RuntimeError('Range4 wrapper already installed')
    if 'novaCopyStreamRecovering(' not in src or 'novaMediaResumeEligible()Z' not in src:
        raise RuntimeError('Expected midstream recovery wrapper missing')
    anchor = (f'    invoke-direct/range {{p0 .. p6}}, {OUTER}->novaCopyStreamRecovering'
              '(Ljava/io/InputStream;Ljava/io/OutputStream;[BJLcom/archos/filecorelibrary/StreamOverHttp$HttpSession;)V')
    if src.count(anchor) != 1:
        raise RuntimeError(f'Expected exactly one WebDAV copy call, got {src.count(anchor)}')
    injection = (f'    invoke-virtual {{p6, p1, p4, p5}}, {SESSION}->novaWrapRange4'
                 '(Ljava/io/InputStream;J)Ljava/io/InputStream;\n    move-result-object p1\n')
    return src.replace(anchor, injection + anchor, 1)

def patch_session(src: str) -> str:
    if f'.implements {SOURCE}' in src or 'novaWrapRange4(' in src:
        raise RuntimeError('Range4 session methods already installed')
    for token in ['novaMediaResumeEligible()Z', 'novaRequestedStart()J',
                  'readOptions()', 'requestedStart:J',
                  'getInputStream(JLcom/archos/filecorelibrary/ReadOptions;)']:
        if token not in src:
            raise RuntimeError('Range4 prerequisite missing: ' + token)
    match = re.search(r'(?m)^\.source [^\n]+$', src)
    if match is None:
        match = re.search(r'(?m)^\.super [^\n]+$', src)
    if match is None:
        raise RuntimeError('HttpSession source/super header not found')
    src = src[:match.end()] + '\n.implements ' + SOURCE + src[match.end():]
    return src.rstrip() + '\n' + SESSION_METHODS

def apply(root: Path, report: Path | None = None) -> dict:
    outer = exactly_one(root, 'StreamOverHttp.smali')
    inner = exactly_one(root, 'StreamOverHttp$HttpSession.smali')
    updates = [(outer, patch_outer(outer.read_text(encoding='utf-8'))),
               (inner, patch_session(inner.read_text(encoding='utf-8')))]
    for path, changed in updates:
        path.write_text(changed, encoding='utf-8')
    result = {'status': 'PASS', 'workers': 4, 'chunk_bytes': 4194304,
              'scope': 'WebDAV media shared StreamOverHttp input (ISO and regular videos)',
              'on_failure': 'existing WebDAV single-stream recovery',
              'log_tag': 'NOVA_RANGE4'}
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
, src)
    if match is None:
        match = re.search(r'(?m)^\.super [^\n]+
    src = src[:match.end()] + '\n.implements ' + SOURCE + src[match.end():]
    return src.rstrip() + '\n' + SESSION_METHODS

def apply(root: Path, report: Path | None = None) -> dict:
    outer = exactly_one(root, 'StreamOverHttp.smali')
    inner = exactly_one(root, 'StreamOverHttp$HttpSession.smali')
    updates = [(outer, patch_outer(outer.read_text(encoding='utf-8'))),
               (inner, patch_session(inner.read_text(encoding='utf-8')))]
    for path, changed in updates:
        path.write_text(changed, encoding='utf-8')
    result = {'status': 'PASS', 'workers': 4, 'chunk_bytes': 4194304,
              'scope': 'WebDAV media shared StreamOverHttp input (ISO and regular videos)',
              'on_failure': 'existing WebDAV single-stream recovery',
              'log_tag': 'NOVA_RANGE4'}
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
, src)
    if match is None:
        raise RuntimeError('HttpSession source/super header not found')
    src = src[:match.end()] + '\n.implements ' + SOURCE + src[match.end():]
    return src.rstrip() + '\n' + SESSION_METHODS

def apply(root: Path, report: Path | None = None) -> dict:
    outer = exactly_one(root, 'StreamOverHttp.smali')
    inner = exactly_one(root, 'StreamOverHttp$HttpSession.smali')
    updates = [(outer, patch_outer(outer.read_text(encoding='utf-8'))),
               (inner, patch_session(inner.read_text(encoding='utf-8')))]
    for path, changed in updates:
        path.write_text(changed, encoding='utf-8')
    result = {'status': 'PASS', 'workers': 4, 'chunk_bytes': 4194304,
              'scope': 'WebDAV media shared StreamOverHttp input (ISO and regular videos)',
              'on_failure': 'existing WebDAV single-stream recovery',
              'log_tag': 'NOVA_RANGE4'}
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
