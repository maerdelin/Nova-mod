#!/usr/bin/env python3
"""Reconstruct the V9.8.2 functional APK payload from a pinned official Universal APK.
This is binary reconstruction, NOT source compilation. Never call it an exact
signed APK match unless the entire signed output digest agrees.
"""
import argparse, hashlib, json, pathlib, subprocess, tarfile, tempfile, zipfile
from io import BytesIO
ROOT=pathlib.Path(__file__).resolve().parents[1]
M=json.loads((ROOT/'baseline/manifest.json').read_text())
sha=lambda b:hashlib.sha256(b).hexdigest()

def overlay():
    chunks=[]
    for i,p in enumerate(M['overlay_parts']):
        data=(ROOT/'baseline/parts'/p['name']).read_bytes()
        assert len(data)==p['size'] and sha(data)==p['sha256'],f'corrupt part {i}'
        chunks.append(data)
    compressed=b''.join(chunks)
    assert sha(compressed)==M['overlay_sha256'],'overlay digest mismatch'
    decoded=subprocess.run(['zstd','-dc'],input=compressed,stdout=subprocess.PIPE,check=True).stdout
    with tarfile.open(fileobj=BytesIO(decoded),mode='r:') as tf:
        out={}
        for m in tf.getmembers():
            assert m.isfile() and not m.name.startswith('/') and '..' not in pathlib.PurePosixPath(m.name).parts
            assert m.name not in out
            out[m.name]=tf.extractfile(m).read()
    return out

def verify_payload(apk):
    entries=M['entries']; declared={e['name']:e for e in entries}
    with zipfile.ZipFile(apk) as z:
        assert z.testzip() is None
        actual={n for n in z.namelist() if n in declared}
        assert actual==set(declared),(len(actual),len(declared),list(set(declared)-actual)[:8])
        for e in entries:
            info=z.getinfo(e['name']);raw=z.read(e['name'])
            assert sha(raw)==e['sha256'],f'V9.8.2 payload mismatch: {e["name"]}'
            assert len(raw)==e['size'] and info.compress_type==e['method']
        print('PASS: V9.8.2 user-tested functional payload:',len(entries),'entries')
        a=z.getinfo('resources.arsc')
        with open(apk,'rb') as fp:
            fp.seek(a.header_offset+26)
            import struct
            nl,el=struct.unpack('<HH',fp.read(4))
        assert a.compress_type==0 and (a.header_offset+30+nl+el)%4==0,'uncompressed resources.arsc alignment failure'
        print('PASS: resources.arsc uncompressed + 4-byte aligned')

def build(source,dest):
    assert sha(source.read_bytes())==M['upstream_sha256'],'official source SHA mismatch'
    changes=overlay(); dest.parent.mkdir(exist_ok=True,parents=True)
    declared={x['name']:x for x in M['entries']}
    with zipfile.ZipFile(source) as upstream,zipfile.ZipFile(dest,'w',allowZip64=False) as target:
        names=set(upstream.namelist())
        assert set(declared).issubset(names),'official source is missing target entry'
        for src in upstream.infolist():
            n=src.filename
            if n=='META-INF/MANIFEST.MF' or (n.startswith('META-INF/') and n.upper().endswith(('.SF','.RSA','.DSA','.EC'))):
                continue
            if n in declared:
                if n in changes: data=changes[n]
                else: data=upstream.read(n)
                assert sha(data)==declared[n]['sha256'],f'non-overlay upstream payload differs: {n}'
                e=declared[n]; method=e['method'];dt=tuple(e['date']);attr=e['external_attr'];system=e['create_system']
            else:
                data=upstream.read(n);method=src.compress_type;dt=src.date_time;attr=src.external_attr;system=src.create_system
            info=zipfile.ZipInfo(n,dt)
            info.compress_type=method
            info.external_attr=attr;info.create_system=system
            target.writestr(info,data,compress_type=method,compresslevel=6)
    verify_payload(dest)
    print('Unsigned functional baseline built. SHA-256:',sha(dest.read_bytes()))

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('mode',choices=['build','verify']);a.add_argument('apk',type=pathlib.Path);a.add_argument('output',nargs='?',type=pathlib.Path);args=a.parse_args()
    if args.mode=='build':
        assert args.output is not None
        build(args.apk,args.output)
    else:verify_payload(args.apk)