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
import xml.etree.ElementTree as ET
import granular as g
import check_upstream as upstream
import iso_patch

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

def preserve_payload(selected: Path, rebuilt: Path, avos_dir: Path, reports: Path):
    with zipfile.ZipFile(selected) as a, zipfile.ZipFile(rebuilt) as b:
        if b.testzip() is not None or len(b.namelist()) != len(set(b.namelist())):
            raise g.Conflict('Rebuilt APK has invalid/duplicate entries')
        keep = [n for n in a.namelist() if n.startswith(('lib/', 'assets/')) and not n.endswith('/')]
        allowed = {f'lib/{abi}/libavos.so' for abi in ('arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64')}
        changed = [n for n in keep if n not in b.namelist() or a.read(n) != b.read(n)]
        unexpected = [n for n in changed if n not in allowed]
        if unexpected:
            raise g.Conflict('Unexpected upstream native/asset payload change: ' + str(unexpected[:10]))
        if set(changed) != allowed:
            raise g.Conflict('Expected exactly four ISO-aware libavos replacements, got: ' + str(changed))
        for abi in ('arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64'):
            name = f'lib/{abi}/libavos.so'
            expected = (avos_dir / abi / 'libavos.so').read_bytes()
            if b.read(name) != expected:
                raise g.Conflict('Rebuilt APK libavos mismatch for ' + abi)
        if b.getinfo('resources.arsc').compress_type != zipfile.ZIP_STORED:
            raise g.Conflict('resources.arsc must be stored uncompressed')
    g.write_json(reports / 'upstream-payload.json', {'status': 'PASS', 'native_and_asset_entries_preserved': len(keep)})


def verify_roundtrip(expected: Path, actual: Path, report: Path):
    """Strict round-trip verification, tolerating only DEX jumbo encoding of MimeUtils strings."""
    sa = g.resource_map(expected)
    sb = g.resource_map(actual)
    ia = g.class_index(expected)
    ib = g.class_index(actual)
    bad = []
    if ia.keys() != ib.keys():
        bad.append('class set differs')
    mime = 'Lcom/archos/filecorelibrary/MimeUtils;'
    for name in ia.keys() & ib.keys():
        a = ia[name].read_text()
        b = ib[name].read_text()
        if name == mime:
            a = a.replace('const-string/jumbo', 'const-string')
            b = b.replace('const-string/jumbo', 'const-string')
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
            if g.logical_xml(ET.parse(expected / path).getroot()) != g.logical_xml(ET.parse(actual / path).getroot()):
                bad.append(path)

    # ISO-specific invariants are checked independently, so this tolerance cannot hide the feature.
    for root, label in ((expected, 'expected'), (actual, 'roundtrip')):
        mf = next(iter(root.glob('smali*/com/archos/filecorelibrary/MimeUtils.smali')), None)
        if mf is None:
            bad.append(label + ': MimeUtils missing')
        else:
            t = mf.read_text()
            if t.count('"video/x-bluray-iso"') != 1 or '"application/x-iso9660-image"' in t:
                bad.append(label + ': ISO MIME mapping invalid')
        pf = next(iter(root.glob('smali*/com/archos/mediacenter/video/player/Player.smali')), None)
        if pf is None or pf.read_text().count('BlurayIsoProxy;->resolve') != 1:
            bad.append(label + ': Player ISO resolver injection invalid')
        proxies = list(root.glob('smali*/com/archos/mediacenter/video/player/BlurayIsoProxy.smali'))
        if len(proxies) != 1 or 'nativeOpen(Ljava/lang/String;)Ljava/lang/String;' not in proxies[0].read_text():
            bad.append(label + ': BlurayIsoProxy invalid')
        for abi in ('arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64'):
            so = root / 'lib' / abi / 'libnova_iso.so'
            if not so.is_file() or so.stat().st_size < 10000:
                bad.append(label + ': missing native ' + abi)

    result = {
        'status': 'FAIL' if bad else 'PASS',
        'classes_compared': len(ia),
        'xml_files_compared': len(aa),
        'differences': sorted(bad),
        'comparison': 'strict logical roundtrip; MimeUtils only normalizes const-string vs const-string/jumbo',
        'runtime_tested': False,
    }
    g.write_json(report, result)
    if bad:
        raise g.Conflict('Logical verification failed: ' + str(bad[:20]))
    print(json.dumps(result, indent=2))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk', type=Path, required=True)
    p.add_argument('--metadata', type=Path, required=True)
    p.add_argument('--apktool', type=Path, required=True)
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--reports', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--iso-native', type=Path, required=True)
    p.add_argument('--avos-native', type=Path, required=True)
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
    iso_patch.apply(candidate, args.iso_native, args.avos_native, args.reports / 'iso-patch.json')
    if generated and selected['downloaded_sha256'] == json.loads((ROOT / 'baseline/manifest.json').read_text())['upstream_sha256']:
        g.verify(args.work / 'reference-mod', candidate, args.reports / 'candidate-baseline.json')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    run('java', '-Xmx4g', '-jar', args.apktool, 'b', candidate, '-o', args.output)
    decoded = args.work / 'roundtrip'
    decode(args.apktool, args.output, decoded)
    verify_roundtrip(candidate, decoded, args.reports / 'roundtrip.json')
    preserve_payload(args.apk, args.output, args.avos_native, args.reports)
    shutil.copyfile(SPEC, args.reports / SPEC.name)
    g.write_json(args.reports / 'build.json', {'status': 'PASS', 'upstream': selected,
        'patch_stats': patch['stats'], 'patch_sha256': upstream.sha256_file(SPEC),
        'whole_module_replacements': 0, 'spec_bootstrapped': generated,
        'bluray_iso_support': True,
        'native_module_replacement': 'libavos.so rebuilt from exact official v6.5.5 source; ISO-only probe branch',
        'unsigned_output_is_internal_only': True, 'runtime_tested': False})
    print('GRANULAR_BUILD=PASS; unsigned internal output must be signed and install-tested before publication')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('::error::' + str(exc), file=sys.stderr)
        raise
