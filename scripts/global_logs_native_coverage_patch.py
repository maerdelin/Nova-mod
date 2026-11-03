#!/usr/bin/env python3
"""Complete JNI and direct-native logcat gating after global_logs_native_patch.py.

Pinned AVOS v6.6 has JNI LOGD/LOGV/LOGE outside the AVOS serprintf gate,
plus direct REG_LOGW/JNI_LOGW loggers. Keep playback calls unchanged.
The final audit rejects newly introduced unguarded Android log writers.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

MARK = 'NOVA_GLOBAL_LOGS_JNI_GUARD_V2'


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: expected exactly one source anchor, got {count}')
    return source.replace(old, new, 1)


def gate_native_direct_logs(root: Path) -> None:
    flag = root / 'Include/nova_global_flag.h'
    if not flag.is_file():
        raise RuntimeError('Native gate header must be installed before JNI logging patch')

    hdr = root / 'jni/libavosjni/libavos.h'
    source = hdr.read_text()
    source = replace_once(
        source, '#include "android/log.h"',
        '#include "android/log.h"\n#include "../../Include/nova_global_flag.h" /* ' + MARK + ' */',
        'JNI shared gate include')
    for level, priority in [('D', 'DEBUG'), ('V', 'VERBOSE'), ('E', 'ERROR')]:
        old = f'#define LOG{level}(...) __android_log_print(ANDROID_LOG_{priority}, LOG_TAG, ##__VA_ARGS__);'
        new = (f'#define LOG{level}(...) do {{ if (nova_global_log_enabled()) '
               f'__android_log_print(ANDROID_LOG_{priority}, LOG_TAG, ##__VA_ARGS__); }} while (0)')
        source = replace_once(source, old, new, 'JNI LOG' + level)
    hdr.write_text(source)

    registry = root / 'Source/sub_engine_registry.c'
    source = registry.read_text()
    source = replace_once(source, '#include "sub_engine_registry.h"',
                          '#include "sub_engine_registry.h"\n#include "../Include/nova_global_flag.h" /* ' + MARK + ' */',
                          'subtitle registry gate include')
    source = replace_once(
        source, '#define REG_LOGW(...) __android_log_print(ANDROID_LOG_WARN, REG_TAG, __VA_ARGS__)',
        '#define REG_LOGW(...) do { if (nova_global_log_enabled()) __android_log_print(ANDROID_LOG_WARN, REG_TAG, __VA_ARGS__); } while (0)',
        'subtitle registry diagnostic logger')
    registry.write_text(source)

    subtitle_jni = root / 'Source/jni_sub_engine.c'
    source = subtitle_jni.read_text()
    source = replace_once(source, '#include "jni_sub_engine.h"',
                          '#include "jni_sub_engine.h"\n#include "../Include/nova_global_flag.h" /* ' + MARK + ' */',
                          'subtitle JNI gate include')
    source = replace_once(
        source, '#define JNI_LOGW(...) __android_log_print(ANDROID_LOG_WARN, JNI_TAG, __VA_ARGS__)',
        '#define JNI_LOGW(...) do { if (nova_global_log_enabled()) __android_log_print(ANDROID_LOG_WARN, JNI_TAG, __VA_ARGS__); } while (0)',
        'subtitle JNI diagnostic logger')
    subtitle_jni.write_text(source)

    audit_raw_android_loggers(root)


def audit_raw_android_loggers(root: Path) -> None:
    """Fail before compilation if native AVOS/JNI gains another raw logcat sink."""
    expected = {
        'Source/log_android.c',
        'Source/sub_engine_registry.c',
        'Source/jni_sub_engine.c',
        'jni/libavosjni/libavos.h',
    }
    found = set()
    paths = list((root / 'Source').rglob('*.c'))
    paths += list((root / 'Source').rglob('*.h'))
    paths += list((root / 'jni/libavosjni').rglob('*.c'))
    paths += list((root / 'jni/libavosjni').rglob('*.h'))
    for path in paths:
        rel = path.relative_to(root).as_posix()
        text = path.read_text(errors='replace')
        for index, line in enumerate(text.splitlines(), 1):
            if not re.search(r'__android_log_(?:print|write|vprint)\s*\(', line):
                continue
            found.add(rel)
            if rel not in expected:
                raise RuntimeError(f'Unexpected ungated Android native log writer {rel}:{index}')
            if rel == 'Source/log_android.c':
                if not re.search(r'__android_log_vprint\s*\(', line) or 'nova_diag_on()?' not in line:
                    raise RuntimeError(f'Unprotected AVOS log_android writer {rel}:{index}')
            elif 'nova_global_log_enabled()' not in line:
                raise RuntimeError(f'Unprotected direct Android logger {rel}:{index}')
    if found != expected:
        raise RuntimeError(f'Native logger source set changed: found={sorted(found)} expected={sorted(expected)}')
    for name in ('jni/libavosjni/libavos.c', 'jni/libavosjni/avos_media_player.c',
                 'jni/libavosjni/avos_media_metadata_retriever.c'):
        if '#include "libavos.h"' not in (root / name).read_text():
            raise RuntimeError(f'JNI logger bypasses guarded libavos.h: {name}')


def audit_transport_logs(transport: Path) -> None:
    source = transport.read_text()
    for name, priority in [('LOGI', 'INFO'), ('LOGE', 'ERROR')]:
        anchor = (f'#define {name}(...) do {{ if(nova_global_log_enabled()) '
                  f'__android_log_print(ANDROID_LOG_{priority},TAG,__VA_ARGS__); }} while(0)')
        if anchor not in source:
            raise RuntimeError('Transport ' + name + ' gate missing or changed')
    for index, line in enumerate(source.splitlines(), 1):
        if '__android_log_' in line and 'nova_global_log_enabled()' not in line:
            raise RuntimeError(f'Transport raw Android logger bypasses gate at line {index}')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--native', required=True, type=Path)
    parser.add_argument('--transport', required=True, type=Path)
    args = parser.parse_args()
    gate_native_direct_logs(args.native)
    audit_transport_logs(args.transport)
    print(MARK + '=PASS JNI, subtitle JNI, registry, AVOS and Transport logcat writers')


if __name__ == '__main__':
    main()
