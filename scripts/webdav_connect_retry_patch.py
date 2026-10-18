#!/usr/bin/env python3
"""Bounded retries for transient WebDAV upstream connection failures in StreamOverHttp.

Only patches the original Java localhost HTTP-bridge open phase. It does not
touch libavos, decoding, buffering, video surfaces or HDMI audio callbacks.
Fails closed if the original class or method shape changes.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re

OUTER = 'Lcom/archos/filecorelibrary/StreamOverHttp;'
INNER = 'Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;'

OUTER_HELPER = '''
.method public novaWebdavOrigin()Z
    .locals 2
    iget-object v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp;->mUri:Landroid/net/Uri;
    if-eqz v0, :nova_not_webdav
    invoke-virtual {v0}, Landroid/net/Uri;->getScheme()Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :nova_not_webdav
    const-string v1, "webdav"
    invoke-virtual {v0, v1}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v1
    if-nez v1, :nova_is_webdav
    const-string v1, "webdavs"
    invoke-virtual {v0, v1}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v1
    if-nez v1, :nova_is_webdav
    :nova_not_webdav
    const/4 v0, 0x0
    return v0
    :nova_is_webdav
    const/4 v0, 0x1
    return v0
.end method
'''

INNER_HELPERS = '''
.method private static novaTransientConnectionFailure(Ljava/lang/Throwable;)Z
    .locals 3
    const/4 v0, 0x0
    :nova_cause_loop
    if-eqz p0, :nova_not_transient
    const/16 v1, 0x8
    if-ge v0, v1, :nova_not_transient
    instance-of v1, p0, Ljava/net/SocketTimeoutException;
    if-nez v1, :nova_is_transient
    instance-of v1, p0, Ljava/net/SocketException;
    if-nez v1, :nova_is_transient
    instance-of v1, p0, Ljava/net/UnknownHostException;
    if-nez v1, :nova_is_transient
    invoke-virtual {p0}, Ljava/lang/Throwable;->getCause()Ljava/lang/Throwable;
    move-result-object v2
    if-eq v2, p0, :nova_not_transient
    move-object p0, v2
    add-int/lit8 v0, v0, 0x1
    goto :nova_cause_loop
    :nova_is_transient
    const/4 v0, 0x1
    return v0
    :nova_not_transient
    const/4 v0, 0x0
    return v0
.end method

.method private openInputStream()V
    .locals 7
    const/4 v0, 0x0
    :nova_retry_attempt
    :nova_try_open_begin
    invoke-direct {p0}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->novaOpenInputStreamOnce()V
    :nova_try_open_end
    .catch Ljava/lang/Exception; {:nova_try_open_begin .. :nova_try_open_end} :nova_caught_open
    return-void
    :nova_caught_open
    move-exception v1
    invoke-direct {p0}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->isCancelled()Z
    move-result v2
    if-nez v2, :nova_no_retry
    iget-object v2, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->this$0:Lcom/archos/filecorelibrary/StreamOverHttp;
    invoke-virtual {v2}, Lcom/archos/filecorelibrary/StreamOverHttp;->novaWebdavOrigin()Z
    move-result v2
    if-eqz v2, :nova_no_retry
    invoke-static {v1}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->novaTransientConnectionFailure(Ljava/lang/Throwable;)Z
    move-result v2
    if-eqz v2, :nova_no_retry
    const/4 v2, 0x3
    if-ge v0, v2, :nova_no_retry
    add-int/lit8 v0, v0, 0x1
    invoke-direct {p0}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->takeInput()Ljava/io/InputStream;
    move-result-object v2
    invoke-direct {p0, v2}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->closeInput(Ljava/io/InputStream;)V
    const-string v2, "NOVA_WEBDAV_RETRY"
    new-instance v3, Ljava/lang/StringBuilder;
    invoke-direct {v3}, Ljava/lang/StringBuilder;-><init>()V
    const-string v4, "Transient upstream connection failed; retry "
    invoke-virtual {v3, v4}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v3
    invoke-virtual {v3, v0}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    move-result-object v3
    const-string v4, "/3"
    invoke-virtual {v3, v4}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v3
    invoke-virtual {v3}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v3
    invoke-static {v2, v3, v1}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I
    const-wide/16 v3, 0x190
    int-to-long v5, v0
    mul-long/2addr v3, v5
    invoke-static {v3, v4}, Ljava/lang/Thread;->sleep(J)V
    goto :nova_retry_attempt
    :nova_no_retry
    throw v1
.end method
'''

def _patch_outer(source: str) -> str:
    if 'novaWebdavOrigin()Z' in source:
        raise RuntimeError('WebDAV origin helper already installed')
    if not re.search(r'(?m)^\.class [^\n]*' + re.escape(OUTER) + r'\s*$', source):
        raise RuntimeError('Unexpected outer StreamOverHttp class')
    if not re.search(r'(?m)^\.field [^\n]*\bmUri:Landroid/net/Uri;\s*$', source):
        raise RuntimeError('Original StreamOverHttp.mUri not found')
    return source.rstrip() + '\n' + OUTER_HELPER

def _patch_inner(source: str) -> str:
    if 'novaOpenInputStreamOnce()V' in source or 'novaTransientConnectionFailure' in source:
        raise RuntimeError('WebDAV retry wrapper already installed')
    if not re.search(r'(?m)^\.class [^\n]*' + re.escape(INNER) + r'\s*$', source):
        raise RuntimeError('Unexpected HttpSession class')
    for token in (
        'this$0:Lcom/archos/filecorelibrary/StreamOverHttp;',
        'isCancelled()Z',
        'takeInput()Ljava/io/InputStream;',
        'closeInput(Ljava/io/InputStream;)V',
    ):
        if token not in source:
            raise RuntimeError('Missing expected HttpSession member: ' + token)
    original = re.compile(r'(?m)^(\.method (?:[^\n]*\s)?)(openInputStream)(\(\)V\s*)$')
    matches = list(original.finditer(source))
    if len(matches) != 1:
        raise RuntimeError(f'Expected one original openInputStream()V, found {len(matches)}')
    if not re.search(r'(?m)^\s*invoke-direct\s+\{p0\},\s*'
                     + re.escape(INNER) + r'->openInputStream\(\)V\s*$', source):
        raise RuntimeError('Expected original run() to invoke private openInputStream()V')
    new = original.sub(lambda m: m.group(1) + 'novaOpenInputStreamOnce' + m.group(3), source, count=1)
    return new.rstrip() + '\n' + INNER_HELPERS

def apply(decoded_root: Path, report: Path | None = None) -> dict:
    paths = {}
    for name in ('StreamOverHttp.smali', 'StreamOverHttp$HttpSession.smali'):
        matches = list(decoded_root.glob('smali*/com/archos/filecorelibrary/' + name))
        if len(matches) != 1:
            raise RuntimeError(f'Expected one {name}, found {len(matches)}')
        paths[name] = matches[0]
    outer_src = paths['StreamOverHttp.smali'].read_text(encoding='utf-8')
    inner_src = paths['StreamOverHttp$HttpSession.smali'].read_text(encoding='utf-8')
    outer = _patch_outer(outer_src)
    inner = _patch_inner(inner_src)
    paths['StreamOverHttp.smali'].write_text(outer, encoding='utf-8')
    paths['StreamOverHttp$HttpSession.smali'].write_text(inner, encoding='utf-8')
    result = {
        'status': 'PASS',
        'scope': 'StreamOverHttp.smali and StreamOverHttp$HttpSession.smali only',
        'scheme': ['webdav', 'webdavs'],
        'max_extra_retries': 3,
        'max_total_connection_attempts': 4,
        'backoff_ms': [400, 800, 1200],
        'retry_exceptions': ['SocketTimeoutException', 'SocketException', 'UnknownHostException'],
        'error_handling': 'original after retries exhausted',
        'cancellation_and_superseding_requests': 'honored',
        'midstream_http_body_retry': False,
    }
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result

def main():
    p = argparse.ArgumentParser()
    p.add_argument('decoded_root', type=Path)
    p.add_argument('--report', type=Path)
    args = p.parse_args()
    print(json.dumps(apply(args.decoded_root, args.report), indent=2))

if __name__ == '__main__':
    main()
