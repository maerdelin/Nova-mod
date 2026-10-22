#!/usr/bin/env python3
"""Prove main-copy equivalence and reject removed transport payloads."""
from pathlib import Path
import argparse, copy, hashlib, json, re, zipfile
import granular as g
ROOT=Path(__file__).resolve().parents[1]
FILES=('StreamOverHttp.smali','StreamOverHttp$HttpSession.smali')
BANNED=(b'NovaParallelRangeInputStream', b'NovaSingleStreamInputStream',
        b'novaWrapRange4', b'publishRange4', b'publishSingle', b'capacityOwner',
        b'capacityPort', b'NOVA_RANGE4', b'nova_range4_capacity', b'NOVA_SINGLE',
        b'parallel_range=1', b'PREFETCH_BEGIN worker=', b'PREFETCH_READY worker=',
        b'PREFETCH_DISCARD worker=')
def sha(data): return hashlib.sha256(data).hexdigest()
def one(root,name):
    paths=list(root.glob('smali*/com/archos/filecorelibrary/'+name))
    if len(paths)!=1: raise RuntimeError('Expected one '+name)
    return paths[0]
def capture(root):
    return {name:one(root,name).read_text() for name in FILES}
def verify_source_baseline(root=ROOT):
    pin=json.loads((root/'baseline/main-transport.json').read_text())
    for name,expected in pin['source_files'].items():
        if sha((root/name).read_bytes())!=expected:
            raise RuntimeError('Pinned main source changed: '+name)
    for name,meta in pin.get('intentional_overrides',{}).items():
        data=(root/name).read_bytes()
        header=('blob '+str(len(data))+'\0').encode()
        blob=hashlib.sha1(header+data).hexdigest()
        if blob!=meta['git_blob_sha1']:
            raise RuntimeError('Intentional native override changed: '+name)
    for name in ['parallel_range4','single_stream']:
        if (root/name).exists(): raise RuntimeError('Removed source directory remains: '+name)
    removed_files=(
        root/'scripts/aggressive_download_patch.py',
        root/'tests/test_aggressive_download_architecture.py',
        root/'tests/test_native_10x_readahead.py',
    )
    for path in removed_files:
        if path.exists(): raise RuntimeError('Removed legacy file remains: '+str(path.relative_to(root)))
    native=(root/'scripts/native_rebuffer_patch.py').read_text()
    iso=(root/'scripts/iso_single_stream_qos_patch.py').read_text()
    parallel_tokens=tuple(x.replace('__','') for x in (
        'PRE__FETCH_WORKERS','iso_prefetch___worker','prefetch___threads',
        'prefetch___generation','parallel___range=1',
        'PREFETCH___BEGIN worker=','PREFETCH___READY worker=',
        'PREFETCH___DISCARD worker=',
    ))
    for token in parallel_tokens:
        if token in native or token in iso:
            raise RuntimeError('Parallel Range architecture reintroduced: '+token)
    legacy_raw=tuple(x.replace('__','') for x in (
        'NOVA_RAW___CHUNK','NOVA_RAW__10X','NOVA_RAW___10X_POLICY',
        'dynamic raw __10X','raw producer cap=__10X',
    ))
    for token in legacy_raw:
        if token in native:
            raise RuntimeError('Legacy RAW architecture remains: '+token)
    if 'NOVA_ISO_SINGLE_STREAM' not in iso or 'parallelRange=0' not in iso:
        raise RuntimeError('Single persistent ISO stream invariant missing')
    if 'uint8_t *ring;' not in native or 'NOVA_RAW_FIXED128_POLICY:' not in native:
        raise RuntimeError('Final fixed-128 RAW ring invariant missing')
    return pin

def verify(root, before, report=None):
    import webdav_safety_patch as safety
    expected={FILES[0]:before[FILES[0]], FILES[1]:safety.session_text(before[FILES[1]])}
    entries={}
    for name in FILES:
        original=g.logical_class(before[name],{})
        want=g.logical_class(expected[name],{})
        current=g.logical_class(one(root,name).read_text(),{})
        if current!=want: raise RuntimeError('Unexpected change to main transport: '+name)
        changed=[k for k in set(original['methods'])|set(want['methods']) if original['methods'].get(k)!=want['methods'].get(k)]
        if name==FILES[0] and changed: raise RuntimeError('Main byte copy replaced')
        if name==FILES[1] and changed!=['openInputStream()V']: raise RuntimeError('Session changes exceed parse-once fix: '+repr(changed))
        if original['header']!=want['header'] or original['fields']!=want['fields']:
            raise RuntimeError('Extra session interfaces or fields detected')
        entries[name]={'main_methods':len(original['methods']),'retained_methods':len(original['methods'])-len(changed),
                       'allowed_changes':changed,'main_logical_sha256':sha(json.dumps(original,sort_keys=True).encode()),
                       'result_logical_sha256':sha(json.dumps(current,sort_keys=True).encode())}
    for path in list(root.glob('smali*/**/*.smali'))+list(root.glob('lib/*/*.so')):
        data=path.read_bytes()
        for token in BANNED:
            if token in data: raise RuntimeError('Removed transport token in '+str(path)+': '+token.decode())
    result={'status':'PASS','main_commit':verify_source_baseline()['main_commit'],
            'transport_classes':entries,'download_loop_changed':False,
            'only_session_exception':'openInputStream parse-once; retries remain in existing retained backend safety policy',
            'native_capacity_publisher_present':False,'parallel_or_replacement_download_helpers_present':False,
            'real_webdav_throughput_tested':False}
    if report:
        report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(result,indent=2)+'\n')
    print('MAIN_TRANSPORT_EQUIVALENCE=PASS '+json.dumps(entries))
    return result

def verify_apk_absence(apk,require_helpers=False):
    helpers=(b'NovaWebdavOpenPolicy;',b'NovaWebdavSidecarPolicy;',b'NovaIsoSessionGuard;',b'NovaControlbarAutoHide;')
    found=set(); count=0; native=0
    with zipfile.ZipFile(apk) as z:
        for name in z.namelist():
            isdex=bool(re.fullmatch(r'classes(?:[0-9]+)?\.dex',name))
            if not isdex and not (name.startswith('lib/') and name.endswith('.so')): continue
            data=z.read(name);count+=int(isdex);native+=int(not isdex)
            for token in BANNED:
                if token in data: raise RuntimeError('Removed code in APK '+name+': '+token.decode())
            if isdex:
                found.update(t for t in helpers if t in data)
    if not count or not native: raise RuntimeError('APK missing DEX/native libraries')
    if require_helpers and len(found)!=len(helpers): raise RuntimeError('Retained repair helper missing')
    return {'status':'PASS','dex_files_scanned':count,'native_libraries_scanned':native,
            'retained_helpers':len(found),'removed_tokens_found':0}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source-check',action='store_true');p.add_argument('--apk',type=Path)
    a=p.parse_args()
    if a.source_check: print('MAIN_SOURCE_PIN=PASS '+verify_source_baseline()['main_commit'])
    if a.apk: print(json.dumps(verify_apk_absence(a.apk,True)))
