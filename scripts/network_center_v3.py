#!/usr/bin/env python3
"""Pin-patched network-only centering: no DEX resizing; preserve working home XML.

Renders 1, 2, 3 network tiles in a centered, width-fitted row. More items keep
a full-screen scrollable row. Called from NetworkShortcutsLoaderTask's main-
thread refresh; onKeyDown(-1) is a network-only centering hook; the synthetic null event is consumed before superclass dispatch.
"""
import base64
import hashlib
import sys
import struct
import zipfile
import zlib
from pathlib import Path

INPUT_DEX_SHA = 'be158200a3070bf13f31f7bbc4c7a1ed667e42a8b221a6e027ebd0122f5ce636'
OUTPUT_DEX_SHA = 'a40884c8fc55b384171e8fe3f4be3ee23fe574835f7dc0f9480ce11d69b5d74d'
CODE_ITEMS = {
    20881: (4263380, 83, '4831df85e6f4e0662e5abd19b755cbfde71cb5c7e417167a63060efd484f7dc9',
        'EvAzB00AbhCZGAYADABgAXo4biDYFhAADAAfAMgLcRDLUQAADAFuEHzpAQAKARMC4gCyIRMCggCwIW4Q6xcAAAwCYAOrM24guAQyAAoCsiETAtIAsyFuEPoXAAAMADgAHgBuED8NAAAKAjchAwABIRQDkQMKf24g4QwwAAwAbhAIDQAADAJZIXMCHwIOAxITWSOwAm4guw0gAA8DbzDKS3YICgAPAA=='),
    20906: (4266828, 134, '1a0e62e64768f75f320910c74ae25683cf0461936ff7fcbb161043f54db51157',
        'VUCDYjkAbABUQIRibhDMFwAADAA4AGQAVECEYm4QAxgAAAoAOABcADgFWgByEAMFBQAKADkAVABUQIRicRDLUQAADABuEHfpAAByEPsEBQAKAD0AIAByEAUFBQAiAPEKcBC7TAAAbiC9TFAAVEGEYnEQy1EBAAwBbiC8TFAADABuIHXpAQByEAYFBQAKADkA5/9UQIRicRDLUQAADAAiAfwKVEKEYmADVj5uIPMXMgAMAnAg90whAG4gdekQAFRAhGJuEMwXAAAMABLxEgJuMCoCEAIoBAAADQQoDTgFCwByEAMFBQAKBDkEBQByEPQEBQAOADgFCwByEAMFBQAKADkABQByEPQEBQAnBA==')
}
UNCHANGED_FILES = {
    'res/Am.xml': 'b246497606d126efa7e56156952bfd059538b9ffb18afb7a1c4cc44380293262',
    'res/mC.xml': '559a5e7d1b679338e5fb9be9eface0ee1edc7ef4ca454651b851ed9084b6a1bc',
    'AndroidManifest.xml': '11774efa86dde2662b0fe8f9d9b36e41bc34864de5cd0fe4d1f31c2656e77712',
}
def sha(b): return hashlib.sha256(b).hexdigest()
def patch(dex):
    if sha(dex) != INPUT_DEX_SHA: raise RuntimeError('Not the user-confirmed AutoMode DEX')
    if struct.unpack_from('<4H2I',dex,4263380)!=(9,3,3,0,6497187,83):
        raise RuntimeError('Wrong network activity method')
    if struct.unpack_from('<4H2I',dex,4266828)!=(6,2,2,1,6499017,134):
        raise RuntimeError('Wrong network loader method')
    out = bytearray(dex)
    for mid,(off,units,digest,encoded) in CODE_ITEMS.items():
        b=base64.b64decode(encoded)
        if len(b)!=units*2 or sha(b)!=digest:raise RuntimeError('Corrupt code item '+str(mid))
        out[off+16:off+16+len(b)]=b
    struct.pack_into('<H',out,4266828+4,3)
    out[12:32]=hashlib.sha1(out[32:]).digest()
    struct.pack_into('<I',out,8,zlib.adler32(out[12:])&0xffffffff)
    if len(out)!=len(dex) or sha(out)!=OUTPUT_DEX_SHA:
        raise RuntimeError('Unexpected result DEX hash')
    return bytes(out)

def build(input_name,output_name):
    with zipfile.ZipFile(input_name) as old:
        if old.testzip(): raise RuntimeError('Bad baseline ZIP CRC')
        for k, expected in UNCHANGED_FILES.items():
            if sha(old.read(k))!=expected:raise RuntimeError('Protected UI asset differs: '+k)
        out=Path(output_name);out.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(out,'w',allowZip64=False) as new:
            for inf in old.infolist():
                name=inf.filename
                upper=name.upper()
                if upper=='META-INF/MANIFEST.MF' or upper.startswith('META-INF/') and upper.endswith(('.SF','.RSA','.DSA','.EC')):
                    continue
                data=patch(old.read(name)) if name=='classes.dex' else old.read(name)
                info=zipfile.ZipInfo(name,inf.date_time)
                info.compress_type=inf.compress_type
                info.external_attr=inf.external_attr
                info.create_system=inf.create_system
                new.writestr(info,data,compress_type=info.compress_type,compresslevel=6)
    with zipfile.ZipFile(out) as candidate, zipfile.ZipFile(input_name) as old:
        if candidate.testzip():raise RuntimeError('Bad candidate ZIP CRC')
        changed=[name for name in candidate.namelist() if old.read(name)!=candidate.read(name)]
        if changed!=['classes.dex']:raise RuntimeError('Other functional files changed: '+str(changed))
        if sha(candidate.read('classes.dex'))!=OUTPUT_DEX_SHA:
            raise RuntimeError('Network patch missing in APK')
        print('PASS: network-only 2 in-place methods, exact home/shared XML unchanged')
        print('PASS: patched DEX',OUTPUT_DEX_SHA, 'Unsigned APK',out)

if __name__=='__main__':
    if len(sys.argv)!=3:sys.exit('Usage: network_center_v3.py input-unsigned.apk output-unsigned.apk')
    build(*sys.argv[1:])
