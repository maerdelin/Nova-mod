#!/usr/bin/env python3
"""Remove the Range4 runtime bridge after all historical APK patches.

The old patch remains a tested intermediate transformation, not shipped code.
Only these two media-session classes change; network validation, native code,
ISO lifecycle and UI patches remain byte-for-byte outside this transformation.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

OLD = 'NovaParallelRangeInputStream'
NEW = 'NovaSingleStreamInputStream'
SESSION = 'Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;'
BASE = 'Lcom/archos/filecorelibrary/'

def once(text, old, new, label):
    if text.count(old) != 1:
        raise RuntimeError(f'{label}: expected one anchor, got {text.count(old)}')
    return text.replace(old, new, 1)

def remove_method(text, signature):
    pattern = r'(?ms)^\.method [^\n]* ' + re.escape(signature) + r'\n.*?^\.end method\n?'
    if len(re.findall(pattern, text)) != 1:
        raise RuntimeError('Expected exactly one removable method: ' + signature)
    return re.sub(pattern, '', text, count=1)

def outer_text(text):
    wrapper = ('    invoke-virtual {p6, p1, p4, p5}, ' + SESSION
               + '->novaWrapRange4(Ljava/io/InputStream;J)Ljava/io/InputStream;\n'
               + '    move-result-object p1\n')
    text = once(text, wrapper, '', 'remove four-lane wrapper call')
    if text.count(BASE + OLD + ';->copyRecovering(') != 1:
        raise RuntimeError('Expected one production media-copy bridge')
    return text.replace(OLD, NEW)

def session_text(text):
    text = remove_method(text, 'novaWrapRange4(Ljava/io/InputStream;J)Ljava/io/InputStream;')
    text = remove_method(text, 'capacityOwner()Ljava/lang/Object;')
    text = remove_method(text, 'capacityPort()I')
    if ('.implements ' + BASE + OLD + '$ManagedSource;') not in text:
        raise RuntimeError('Expected old managed source interface')
    text = text.replace(OLD, NEW)
    text = once(text, 'publishRange4(Ljava/io/InputStream;)V',
                'publishSingle(Ljava/io/InputStream;)V', 'rename single ownership hook')
    return text.replace('WebDAV Range4 request cancelled before open',
                        'WebDAV single-stream request cancelled before open')

def one(root, filename):
    paths = list(root.glob('smali*/com/archos/filecorelibrary/' + filename))
    if len(paths) != 1: raise RuntimeError('Expected one class: ' + filename)
    return paths[0]

def verify(root):
    for p in root.glob('smali*/**/*.smali'):
        text = p.read_text(encoding='utf-8')
        if OLD in text or 'novaWrapRange4(' in text or 'publishRange4(' in text:
            raise RuntimeError('Parallel runtime reference still present: ' + str(p))
    outer = one(root, 'StreamOverHttp.smali').read_text()
    inner = one(root, 'StreamOverHttp$HttpSession.smali').read_text()
    if outer.count(BASE + NEW + ';->copyRecovering(') != 1:
        raise RuntimeError('Single stream is not the unique media-copy target')
    if ('.implements ' + BASE + NEW + '$ManagedSource;') not in inner:
        raise RuntimeError('Single-stream cancellation ownership is missing')
    if 'publishSingle(Ljava/io/InputStream;)V' not in inner:
        raise RuntimeError('Single-stream input publication is missing')
    if 'requestReparse=0' not in inner and 'novaOpenInputStreamOnce()V' not in inner:
        raise RuntimeError('Existing request-parse-once repair missing')

def apply(root, report=None):
    outer = one(root, 'StreamOverHttp.smali')
    inner = one(root, 'StreamOverHttp$HttpSession.smali')
    changes = [(outer, outer_text(outer.read_text())), (inner, session_text(inner.read_text()))]
    for p, text in changes: p.write_text(text, encoding='utf-8')
    verify(root)
    result = {'status': 'PASS', 'mode': 'single-continuous', 'parallel_workers': 0,
              'connections_per_copy_session': 1, 'range_partitioning': False,
              'java_range4_staging_window': 'removed', 'native_buffer_policy': 'unchanged',
              'request_validation_and_credentials': 'unchanged',
              'cancel_and_bounded_read_recovery': 'preserved',
              'real_device_throughput_verified': False}
    if report: report.write_text(json.dumps(result, indent=2) + '\n')
    return result
