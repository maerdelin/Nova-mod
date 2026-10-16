#!/usr/bin/env python3
"""Inject only the simple WebDAV buffering hysteresis on top of main.

Policy:
- startup blocks until buffered bytes are strictly greater than 45 MiB;
- playback blocks when buffered bytes are strictly below 24 MiB;
- playback resumes only when buffered bytes are strictly greater than 45 MiB;
- producer continues in the background and the pipe itself caps queued bytes at 64 MiB.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

METHOD_RE = re.compile(r'^\.method [^\n]+\n.*?^\.end method', re.M | re.S)

def _one(paths, label):
    paths = list(paths)
    if len(paths) != 1:
        raise RuntimeError(f'{label}: expected one target, got {len(paths)}: {paths}')
    return paths[0]


STREAM_SOURCE_URI_SMALI = r'''.method public getSourceUri()Landroid/net/Uri;
    .locals 1

    iget-object v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp;->mUri:Landroid/net/Uri;

    return-object v0
.end method
'''

READ_AHEAD_SMALI = r'''.class public final Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
.super Ljava/io/InputStream;
.source "NetworkReadAheadInputStream.java"

.implements Ljava/lang/Runnable;

.field private static final CAPACITY:I = 0x4000000
.field private static final CHUNK:I = 0x40000
.field private static final LOW_WATERMARK:I = 0x1800000
.field private static final START_WATERMARK:I = 0x2d00000
.field private static final TAG:Ljava/lang/String; = "NovaNetBuf"

.field private volatile buffering:Z
.field private volatile closed:Z
.field private volatile eof:Z
.field private volatile failure:Ljava/io/IOException;
.field private final pipeIn:Ljava/io/PipedInputStream;
.field private final pipeOut:Ljava/io/PipedOutputStream;
.field private final source:Ljava/io/InputStream;
.field private stage:I
.field private target:I

.method private constructor <init>(Ljava/io/InputStream;)V
    .locals 5

    invoke-direct {p0}, Ljava/io/InputStream;-><init>()V

    iput-object p1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->source:Ljava/io/InputStream;

    const/4 v0, 0x1
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    const v0, 0x2d00000
    iput v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->target:I

    new-instance v0, Ljava/io/PipedInputStream;
    const v1, 0x4000000
    invoke-direct {v0, v1}, Ljava/io/PipedInputStream;-><init>(I)V
    iput-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;

    new-instance v1, Ljava/io/PipedOutputStream;
    invoke-direct {v1, v0}, Ljava/io/PipedOutputStream;-><init>(Ljava/io/PipedInputStream;)V
    iput-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeOut:Ljava/io/PipedOutputStream;

    new-instance v2, Ljava/lang/Thread;
    const-string v3, "Nova WebDAV read-ahead"
    invoke-direct {v2, p0, v3}, Ljava/lang/Thread;-><init>(Ljava/lang/Runnable;Ljava/lang/String;)V
    const/4 v4, 0x1
    invoke-virtual {v2, v4}, Ljava/lang/Thread;->setDaemon(Z)V
    invoke-virtual {v2}, Ljava/lang/Thread;->start()V

    return-void
.end method

.method public static wrap(Landroid/net/Uri;Ljava/io/InputStream;Z)Ljava/io/InputStream;
    .locals 5

    if-eqz p1, :return_original
    if-eqz p2, :return_original
    if-eqz p0, :return_original

    invoke-virtual {p0}, Landroid/net/Uri;->getScheme()Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :return_original

    const-string v1, "webdav"
    invoke-virtual {v1, v0}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-nez v2, :wrap_stream

    const-string v1, "webdavs"
    invoke-virtual {v1, v0}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-eqz v2, :return_original

    :wrap_stream
    :try_start_0
    new-instance v2, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;
    invoke-direct {v2, p1}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;-><init>(Ljava/io/InputStream;)V

    const-string v3, "NovaNetBuf"
    const-string v4, "READ_AHEAD_ON webdav cap=64MiB low=24MiB resume>45MiB"
    invoke-static {v3, v4}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    return-object v2
    :try_end_0
    .catch Ljava/io/IOException; {:try_start_0 .. :try_end_0} :catch_io
    .catch Ljava/lang/OutOfMemoryError; {:try_start_0 .. :try_end_0} :catch_oom

    :catch_io
    move-exception v2
    const-string v3, "NovaNetBuf"
    const-string v4, "READ_AHEAD_INIT_FAIL fallback"
    invoke-static {v3, v4, v2}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I
    return-object p1

    :catch_oom
    move-exception v2
    const-string v3, "NovaNetBuf"
    const-string v4, "READ_AHEAD_OOM fallback"
    invoke-static {v3, v4, v2}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I

    :return_original
    return-object p1
.end method

.method private awaitReady()V
    .locals 4

    :loop
    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    if-nez v0, :return

    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->available()I
    move-result v0

    iget-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    if-nez v1, :waiting

    const v1, 0x1800000
    if-ge v0, v1, :return

    const/4 v1, 0x1
    iput-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    const-string v2, "NovaNetBuf"
    const-string v3, "BUFFER_LOW available<24MiB wait>45MiB"
    invoke-static {v2, v3}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    :waiting
    iget-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z
    if-nez v1, :return

    const v1, 0x2d00000
    if-le v0, v1, :wait_more

    const/4 v1, 0x0
    iput-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z

    const-string v1, "NovaNetBuf"
    const-string v2, "BUFFER_READY available>45MiB"
    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    return-void

    :wait_more
    const-wide/32 v1, 0x989680
    invoke-static {v1, v2}, Ljava/util/concurrent/locks/LockSupport;->parkNanos(J)V
    goto :loop

    :return
    return-void
.end method

.method public run()V
    .locals 5

    const v0, 0x40000
    new-array v0, v0, [B

    :read_loop
    iget-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    if-nez v1, :finish

    :try_start_0
    iget-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->source:Ljava/io/InputStream;
    const/4 v2, 0x0
    array-length v3, v0
    invoke-virtual {v1, v0, v2, v3}, Ljava/io/InputStream;->read([BII)I
    move-result v1

    if-ltz v1, :finish
    if-eqz v1, :read_loop

    iget-object v3, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeOut:Ljava/io/PipedOutputStream;
    invoke-virtual {v3, v0, v2, v1}, Ljava/io/OutputStream;->write([BII)V
    goto :read_loop
    :try_end_0
    .catch Ljava/io/IOException; {:try_start_0 .. :try_end_0} :catch_io

    :catch_io
    move-exception v1
    iget-boolean v2, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    if-nez v2, :finish
    iput-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->failure:Ljava/io/IOException;

    :finish
    const/4 v1, 0x1
    iput-boolean v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z

    :try_start_1
    iget-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeOut:Ljava/io/PipedOutputStream;
    invoke-virtual {v1}, Ljava/io/PipedOutputStream;->close()V
    :try_end_1
    .catch Ljava/io/IOException; {:try_start_1 .. :try_end_1} :after_pipe

    :after_pipe
    :try_start_2
    iget-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->source:Ljava/io/InputStream;
    invoke-virtual {v1}, Ljava/io/InputStream;->close()V
    :try_end_2
    .catch Ljava/io/IOException; {:try_start_2 .. :try_end_2} :done

    :done
    return-void
.end method

.method public read()I
    .locals 2

    invoke-direct {p0}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->awaitReady()V

    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->read()I
    move-result v0

    if-ltz v0, :check_failure
    return v0

    :check_failure
    iget-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->failure:Ljava/io/IOException;
    if-eqz v1, :return_value
    throw v1

    :return_value
    return v0
.end method

.method public read([BII)I
    .locals 2

    invoke-direct {p0}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->awaitReady()V

    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0, p1, p2, p3}, Ljava/io/PipedInputStream;->read([BII)I
    move-result v0

    if-ltz v0, :check_failure
    return v0

    :check_failure
    iget-object v1, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->failure:Ljava/io/IOException;
    if-eqz v1, :return_value
    throw v1

    :return_value
    return v0
.end method

.method public available()I
    .locals 2

    iget-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->buffering:Z
    if-eqz v0, :actual
    const/4 v0, 0x0
    return v0

    :actual
    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->available()I
    move-result v0
    return v0
.end method

.method public skip(J)J
    .locals 2

    invoke-direct {p0}, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->awaitReady()V

    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0, p1, p2}, Ljava/io/PipedInputStream;->skip(J)J
    move-result-wide v0
    return-wide v0
.end method

.method public close()V
    .locals 2

    const/4 v0, 0x1
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->closed:Z
    iput-boolean v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->eof:Z

    :try_start_0
    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->source:Ljava/io/InputStream;
    invoke-virtual {v0}, Ljava/io/InputStream;->close()V
    :try_end_0
    .catch Ljava/io/IOException; {:try_start_0 .. :try_end_0} :after_source

    :after_source
    :try_start_1
    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeIn:Ljava/io/PipedInputStream;
    invoke-virtual {v0}, Ljava/io/PipedInputStream;->close()V
    :try_end_1
    .catch Ljava/io/IOException; {:try_start_1 .. :try_end_1} :after_in

    :after_in
    :try_start_2
    iget-object v0, p0, Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->pipeOut:Ljava/io/PipedOutputStream;
    invoke-virtual {v0}, Ljava/io/PipedOutputStream;->close()V
    :try_end_2
    .catch Ljava/io/IOException; {:try_start_2 .. :try_end_2} :done

    :done
    return-void
.end method
'''

STREAM_SESSION_POLICY_SMALI = r'''.method private shouldUseNetworkReadAhead()Z
    .locals 6

    iget-boolean v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->supersedableMediaRequest:Z
    if-eqz v0, :no

    iget-wide v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->length:J
    const-wide/32 v2, 0x800000
    cmp-long v4, v0, v2
    if-ltz v4, :no

    iget-boolean v4, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->partialResponse:Z
    if-eqz v4, :yes

    iget-wide v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->requestedEnd:J
    iget-wide v2, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->length:J
    const-wide/16 v4, 0x1
    sub-long/2addr v2, v4
    cmp-long v4, v0, v2
    if-nez v4, :no

    iget-wide v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->requestedEnd:J
    iget-wide v2, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->requestedStart:J
    sub-long/2addr v0, v2

    const-wide/32 v2, 0x800000
    cmp-long v4, v0, v2
    if-ltz v4, :no

    :yes
    const/4 v0, 0x1
    return v0

    :no
    const/4 v0, 0x0
    return v0
.end method
'''

def patch_stream_over_http_text(text: str) -> tuple[str, str]:
    sig = ' getSourceUri()Landroid/net/Uri;'
    if sig in text:
        return text, 'already-applied'
    if 'mUri:Landroid/net/Uri;' not in text:
        raise RuntimeError('StreamOverHttp.mUri missing')

    methods = []
    for m in METHOD_RE.finditer(text):
        first = m.group(0).splitlines()[0]
        if ' copyStream(' in first:
            methods.append(m)
    if len(methods) != 1:
        raise RuntimeError(f'StreamOverHttp.copyStream missing/ambiguous: {len(methods)}')
    m = methods[0]
    body = m.group(0)
    flush_re = re.compile(r'\n\s*invoke-virtual \{[^}]+\}, Ljava/io/OutputStream;->flush\(\)V')
    hits = list(flush_re.finditer(body))
    if len(hits) > 1:
        raise RuntimeError(f'StreamOverHttp per-chunk flush ambiguous: {len(hits)}')
    if hits:
        body = body[:hits[0].start()] + body[hits[0].end():]
    text = text[:m.start()] + body + text[m.end():]
    return text.rstrip() + '\n\n' + STREAM_SOURCE_URI_SMALI + '\n', 'applied'


def patch_stream_http_session_text(text: str) -> tuple[str, str]:
    wrapper = (
        'Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->wrap'
        '(Landroid/net/Uri;Ljava/io/InputStream;Z)Ljava/io/InputStream;'
    )
    policy = ' shouldUseNetworkReadAhead()Z'
    if wrapper in text and policy in text:
        return text, 'already-applied'
    if wrapper in text or policy in text:
        raise RuntimeError('Partial WebDAV read-ahead patch found')

    methods = []
    for m in METHOD_RE.finditer(text):
        first = m.group(0).splitlines()[0]
        if ' publishInput(Ljava/io/InputStream;)V' in first:
            methods.append(m)
    if len(methods) != 1:
        raise RuntimeError(f'StreamOverHttp.HttpSession.publishInput missing/ambiguous: {len(methods)}')

    for field in ('supersedableMediaRequest:Z', 'partialResponse:Z', 'length:J',
                  'requestedStart:J', 'requestedEnd:J'):
        if field not in text:
            raise RuntimeError(f'StreamOverHttp.HttpSession field missing: {field}')

    m = methods[0]
    body = m.group(0)
    lines = body.splitlines()
    decl_idx = next((i for i, line in enumerate(lines)
                     if line.strip().startswith(('.locals ', '.registers '))), None)
    if decl_idx is None:
        raise RuntimeError('StreamOverHttp.HttpSession.publishInput register declaration missing')

    decl = lines[decl_idx].strip()
    if decl.startswith('.locals '):
        old_locals = int(decl.split()[1], 0)
        lines[decl_idx] = lines[decl_idx].replace(
            '.locals ' + decl.split()[1], '.locals ' + str(old_locals + 2), 1)
    else:
        old_regs = int(decl.split()[1], 0)
        old_locals = old_regs - 2
        if old_locals < 0:
            raise RuntimeError('Invalid publishInput register count')
        lines[decl_idx] = lines[decl_idx].replace(
            '.registers ' + decl.split()[1], '.registers ' + str(old_regs + 2), 1)

    uri_reg = f'v{old_locals}'
    bool_reg = f'v{old_locals + 1}'
    injection = [
        '',
        f'    iget-object {uri_reg}, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->this$0:Lcom/archos/filecorelibrary/StreamOverHttp;',
        '',
        f'    invoke-virtual {{{uri_reg}}}, Lcom/archos/filecorelibrary/StreamOverHttp;->getSourceUri()Landroid/net/Uri;',
        '',
        f'    move-result-object {uri_reg}',
        '',
        '    invoke-direct {p0}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->shouldUseNetworkReadAhead()Z',
        '',
        f'    move-result {bool_reg}',
        '',
        f'    invoke-static {{{uri_reg}, p1, {bool_reg}}}, {wrapper}',
        '',
        '    move-result-object p1',
    ]
    lines[decl_idx + 1:decl_idx + 1] = injection
    new_body = '\n'.join(lines)
    text = text[:m.start()] + new_body + text[m.end():]
    return text.rstrip() + '\n\n' + STREAM_SESSION_POLICY_SMALI + '\n', 'applied'


def _next_smali_dir(root: Path) -> Path:
    nums = [1]
    for p in root.glob('smali_classes*'):
        try:
            nums.append(int(p.name.removeprefix('smali_classes')))
        except ValueError:
            pass
    return root / f'smali_classes{max(nums) + 1}'



def verify_roundtrip(expected: Path, actual: Path, report: Path, g):
    """Verify apktool round-trip while explicitly validating intentional WebDAV changes."""
    sa = g.resource_map(expected)
    sb = g.resource_map(actual)
    ia = g.class_index(expected)
    ib = g.class_index(actual)
    bad = []
    if ia.keys() != ib.keys():
        bad.append('class set differs')

    semantic = {
        'Lcom/archos/filecorelibrary/StreamOverHttp;',
        'Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;',
        'Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;',
    }
    for name in ia.keys() & ib.keys():
        if name in semantic:
            continue
        a = ia[name].read_text()
        b = ib[name].read_text()
        if a != b and g.logical_class(a, sa) != g.logical_class(b, sb):
            bad.append(name)

    aa = {p.relative_to(expected).as_posix() for p in expected.rglob('*.xml')
          if p.relative_to(expected).as_posix().startswith(('res/', 'AndroidManifest.xml'))}
    bb = {p.relative_to(actual).as_posix() for p in actual.rglob('*.xml')
          if p.relative_to(actual).as_posix().startswith(('res/', 'AndroidManifest.xml'))}
    if aa != bb:
        bad.append('XML resource set differs')
    for path in aa & bb:
        if (expected / path).read_bytes() != (actual / path).read_bytes():
            if g.logical_xml(g.ET.parse(expected / path).getroot()) != g.logical_xml(g.ET.parse(actual / path).getroot()):
                bad.append(path)

    for root, label in ((expected, 'expected'), (actual, 'roundtrip')):
        stream = list(root.glob('smali*/com/archos/filecorelibrary/StreamOverHttp.smali'))
        if len(stream) != 1:
            bad.append(label + ': StreamOverHttp missing/duplicate')
        else:
            st = stream[0].read_text()
            if st.count(' getSourceUri()Landroid/net/Uri;') != 1:
                bad.append(label + ': source URI bridge invalid')

        session = list(root.glob('smali*/com/archos/filecorelibrary/StreamOverHttp$HttpSession.smali'))
        if len(session) != 1:
            bad.append(label + ': HttpSession missing/duplicate')
        else:
            ss = session[0].read_text()
            wrapper = (
                'Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;->wrap'
                '(Landroid/net/Uri;Ljava/io/InputStream;Z)Ljava/io/InputStream;'
            )
            if ss.count(wrapper) != 1:
                bad.append(label + ': read-ahead wrapper count invalid')
            if ss.count(' shouldUseNetworkReadAhead()Z') != 1:
                bad.append(label + ': read-ahead policy count invalid')
            for token in ('supersedableMediaRequest:Z', 'partialResponse:Z', 'length:J',
                          'requestedStart:J', 'requestedEnd:J', 'const-wide/32 v2, 0x800000'):
                if token not in ss:
                    bad.append(label + ': HttpSession missing ' + token)

        ra = list(root.glob('smali*/com/archos/filecorelibrary/NetworkReadAheadInputStream.smali'))
        if len(ra) != 1:
            bad.append(label + ': NetworkReadAheadInputStream missing/duplicate')
        else:
            rt = ra[0].read_text()
            required = (
                '.field private static final CAPACITY:I = 0x4000000',
                '.field private static final LOW_WATERMARK:I = 0x1800000',
                '.field private static final START_WATERMARK:I = 0x2d00000',
                'const v1, 0x4000000',
                'const v1, 0x1800000',
                'const v1, 0x2d00000',
                'if-ge v0, v1, :return',
                'if-le v0, v1, :wait_more',
                'BUFFER_LOW available<24MiB wait>45MiB',
                'BUFFER_READY available>45MiB',
                'READ_AHEAD_ON webdav cap=64MiB low=24MiB resume>45MiB',
            )
            for token in required:
                if token not in rt:
                    bad.append(label + ': NetworkReadAhead missing ' + token)
            for forbidden in ('rebuffer=16/24/28MiB', 'BUFFER_LOW stage=', 'low=2MiB'):
                if forbidden in rt:
                    bad.append(label + ': old buffer policy remains ' + forbidden)

    result = {
        'status': 'FAIL' if bad else 'PASS',
        'classes_compared': len(ia),
        'xml_files_compared': len(aa),
        'differences': sorted(bad),
        'comparison': 'strict roundtrip except three intentional WebDAV classes, which use explicit 24/45/64 semantic invariants',
        'runtime_tested': False,
    }
    g.write_json(report, result)
    if bad:
        raise g.Conflict('WebDAV-aware logical verification failed: ' + str(bad[:20]))
    print(json.dumps(result, indent=2))
    return result

def apply(root: Path, report: Path | None = None):
    stream_http = _one(root.glob('smali*/com/archos/filecorelibrary/StreamOverHttp.smali'), 'StreamOverHttp')
    stream_http_text, stream_http_status = patch_stream_over_http_text(stream_http.read_text())
    stream_http.write_text(stream_http_text)

    stream_session = _one(root.glob('smali*/com/archos/filecorelibrary/StreamOverHttp$HttpSession.smali'), 'StreamOverHttp.HttpSession')
    stream_session_text, stream_session_status = patch_stream_http_session_text(stream_session.read_text())
    stream_session.write_text(stream_session_text)

    read_ahead_hits = list(root.glob('smali*/com/archos/filecorelibrary/NetworkReadAheadInputStream.smali'))
    if read_ahead_hits:
        if len(read_ahead_hits) != 1 or read_ahead_hits[0].read_text() != READ_AHEAD_SMALI:
            raise RuntimeError('NetworkReadAheadInputStream class conflict')
        read_ahead_path = read_ahead_hits[0]
        read_ahead_status = 'already-applied'
    else:
        smali_dir = _next_smali_dir(root)
        read_ahead_path = smali_dir / 'com/archos/filecorelibrary/NetworkReadAheadInputStream.smali'
        read_ahead_path.parent.mkdir(parents=True, exist_ok=True)
        read_ahead_path.write_text(READ_AHEAD_SMALI)
        read_ahead_status = 'applied'

    result = {
        'status': 'PASS',
        'stream_over_http_source_uri': stream_http_status,
        'stream_over_http_readahead': stream_session_status,
        'network_readahead': read_ahead_status,
        'network_readahead_path': read_ahead_path.relative_to(root).as_posix(),
        'capacity_mib': 64,
        'low_watermark_mib': 24,
        'resume_strictly_above_mib': 45,
        'startup_strictly_above_mib': 45,
        'strategy': 'simple byte hysteresis; consumer blocks below 24 MiB and resumes above 45 MiB; producer pipe caps queued bytes at 64 MiB',
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + '\\n')
    return result
