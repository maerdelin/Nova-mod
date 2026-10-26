#!/usr/bin/env python3
"""Build from the selected latest APK, applying only granular operations.
Old binary overlay is used ONLY for one-time reference extraction/verification.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
import granular as g
import check_upstream as upstream
import buffer_guard_patch
import audio_route_no_rebuild_patch
import tv_track_width_patch
import tv_small_card_spacing_patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / 'patches/v982-granular.json'
EXPECTED_STATS = {'classes': 26, 'methods': 40, 'instruction_hunks': 110,
                  'field_declarations': 2, 'xml_files': 11, 'xml_operations': 37}

def run(*args):
    subprocess.run([str(x) for x in args], check=True)

def decode(jar: Path, apk: Path, directory: Path):
    run('java', '-Xmx4g', '-jar', jar, 'd', '--no-debug-info', '-f', apk, '-o', directory)

def bootstrap(jar: Path, work: Path, selected: Path, reports: Path):
    import build as reference
    manifest = json.loads((ROOT / 'baseline/manifest.json').read_text())
    old = work / 'reference-official.apk'
    if upstream.sha256_file(selected) == manifest['upstream_sha256']:
        shutil.copyfile(selected, old)
    else:
        upstream.download_file(manifest['upstream_url'], old)
    if upstream.sha256_file(old) != manifest['upstream_sha256']:
        raise g.Conflict('Reference source digest mismatch')
    modified = work / 'reference-mod-UNSIGNED.apk'
    reference.build(old, modified)
    decode(jar, old, work / 'reference-old')
    decode(jar, modified, work / 'reference-mod')
    with zipfile.ZipFile(old) as a, zipfile.ZipFile(modified) as b:
        for n in sorted(set(a.namelist()) | set(b.namelist())):
            if n == 'META-INF/MANIFEST.MF' or n.startswith('META-INF/') and n.upper().endswith(('.SF', '.RSA', '.DSA', '.EC')):
                continue
            x = a.read(n) if n in a.namelist() else None
            y = b.read(n) if n in b.namelist() else None
            if x != y and not (n.endswith('.dex') or n == 'resources.arsc' or n == 'AndroidManifest.xml' or n.startswith('res/') and n.endswith('.xml')):
                raise g.Conflict('Unrepresented baseline payload change: ' + n)
    patch = g.extract(work / 'reference-old', work / 'reference-mod', SPEC)
    if any(patch['stats'].get(k) != v for k, v in EXPECTED_STATS.items()):
        raise g.Conflict('Extracted patch scope differs from the reviewed reference')
    shutil.copytree(work / 'reference-old', work / 'reference-test')
    g.apply(work / 'reference-test', patch)
    g.verify(work / 'reference-mod', work / 'reference-test', reports / 'baseline-equivalence.json')
    g.write_json(reports / 'bootstrap.json', {'status': 'PASS', 'generated_spec': True, 'stats': patch['stats']})

def overlay_native(candidate: Path, native_root: Path, reports: Path):
    expected = {}
    for abi_dir in sorted((candidate / 'lib').iterdir()):
        if not abi_dir.is_dir():
            continue
        dst = abi_dir / 'libavos.so'
        if not dst.is_file():
            continue
        src = native_root / abi_dir.name / 'libavos.so'
        if not src.is_file():
            raise g.Conflict(f'Missing rebuilt libavos.so for ABI {abi_dir.name}: {src}')
        before = upstream.sha256_file(dst)
        shutil.copyfile(src, dst)
        after = upstream.sha256_file(dst)
        if before == after:
            raise g.Conflict(f'Rebuilt libavos.so for {abi_dir.name} is byte-identical to official payload')
        expected[f'lib/{abi_dir.name}/libavos.so'] = {
            'official_sha256': before,
            'rebuilt_sha256': after,
        }
    if not expected:
        raise g.Conflict('No lib/<abi>/libavos.so entries found in decoded APK')
    g.write_json(reports / 'native-overlay.json', {
        'status': 'PASS',
        'changed_entries': expected,
        'only_library_replaced': 'libavos.so',
    })


def preserve_payload(selected: Path, rebuilt: Path, reports: Path):
    with zipfile.ZipFile(selected) as a, zipfile.ZipFile(rebuilt) as b:
        if b.testzip() is not None or len(b.namelist()) != len(set(b.namelist())):
            raise g.Conflict('Rebuilt APK has invalid/duplicate entries')
        keep = [n for n in a.namelist() if n.startswith(('lib/', 'assets/')) and not n.endswith('/')]
        allowed = {n for n in keep if n.startswith('lib/') and n.endswith('/libavos.so')}
        changed = {n for n in keep if n not in b.namelist() or a.read(n) != b.read(n)}
        unexpected = sorted(changed - allowed)
        missing = sorted(allowed - changed)
        if unexpected:
            raise g.Conflict('Unexpected native/asset payload changes: ' + str(unexpected[:10]))
        if missing:
            raise g.Conflict('Expected rebuilt libavos.so did not change: ' + str(missing))
        if b.getinfo('resources.arsc').compress_type != zipfile.ZIP_STORED:
            raise g.Conflict('resources.arsc must be stored uncompressed')
    g.write_json(reports / 'upstream-payload.json', {
        'status': 'PASS',
        'preserved_native_and_asset_entries': len(keep) - len(allowed),
        'replaced_libavos_entries': sorted(allowed),
        'unexpected_changes': [],
    })

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk', type=Path, required=True)
    p.add_argument('--metadata', type=Path, required=True)
    p.add_argument('--apktool', type=Path, required=True)
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--reports', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--native-lib-root', type=Path, required=True,
                   help='Directory containing <abi>/libavos.so rebuilt from patched aos-avos')
    args = p.parse_args()
    selected = upstream.load_selection(args.metadata, args.apk)
    args.work.mkdir(parents=True, exist_ok=True)
    args.reports.mkdir(parents=True, exist_ok=True)
    generated = not SPEC.is_file()
    if generated:
        bootstrap(args.apktool, args.work, args.apk, args.reports)
    patch = json.loads(SPEC.read_text())
    if any(patch['stats'].get(k) != v for k, v in EXPECTED_STATS.items()):
        raise g.Conflict('Unexpected patch operation scope')
    candidate = args.work / 'candidate'
    decode(args.apktool, args.apk, candidate)
    g.apply(candidate, patch, args.reports / 'patch-application.json')
    buffer_guard_patch.apply(candidate, args.reports / 'buffer-guard.json')
    audio_route_no_rebuild_patch.apply(candidate, args.reports / 'audio-route-no-rebuild.json')
    tv_track_width_patch.apply(candidate, args.reports / 'tv-track-popup-width.json')
    tv_small_card_spacing_patch.apply(candidate, args.reports / 'tv-small-card-gap.json')
    overlay_native(candidate, args.native_lib_root, args.reports)
    if generated and selected['downloaded_sha256'] == json.loads((ROOT / 'baseline/manifest.json').read_text())['upstream_sha256']:
        g.verify(args.work / 'reference-mod', candidate, args.reports / 'candidate-baseline.json')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    run('java', '-Xmx4g', '-jar', args.apktool, 'b', candidate, '-o', args.output)
    decoded = args.work / 'roundtrip'
    decode(args.apktool, args.output, decoded)
    g.verify(candidate, decoded, args.reports / 'roundtrip.json')
    preserve_payload(args.apk, args.output, args.reports)
    shutil.copyfile(SPEC, args.reports / SPEC.name)
    g.write_json(args.reports / 'build.json', {'status': 'PASS', 'upstream': selected,
        'patch_stats': patch['stats'], 'patch_sha256': upstream.sha256_file(SPEC),
        'whole_module_replacements': 0, 'native_replacements': ['libavos.so'],
        'native_rebuffer_control': 'pre-demux raw source: dynamic 2X low / 5X resume; fixed 128MiB producer wall independent of playback state',
        'packet_handoff_mib': 24,
        'webdav_transport': 'direct native transport is applied after granular base; no StreamOverHttp playback tuning',
        'spec_bootstrapped': generated,
        'unsigned_output_is_internal_only': True, 'runtime_tested': False})
    print('GRANULAR_BUILD=PASS; unsigned internal output must be signed and install-tested before publication')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('::error::' + str(exc), file=sys.stderr)
        raise
