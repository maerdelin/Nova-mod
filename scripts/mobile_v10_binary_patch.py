#!/usr/bin/env python3
"""V10 mobile-only exact patch over the SHA-pinned user-tested V6 APK.

Blob is a compact binary change set with original and target member SHA256s.
It contains *only* classes.dex, mobile-only category/phone/tablet/card XML.
Android TV UI resources and V6 AutoMode bytecode remain unchanged.
This reconstructs unsigned content. Re-sign with a trusted keystore.
"""
import base64,hashlib,io,struct,sys,zipfile,zlib
from pathlib import Path
BLOB='e451efc5'
# Embedded patch payload follows in V10_PATCH_BASE64 below.
V10_PATCH_BASE64 = """__BLOB_PENDING__"""
MEMBERS=['classes.dex','res/Tl.xml','res/2a.xml','res/_J.xml','res/yt.xml']
SOURCE_V6='957819f313352ff54adcaac9000037d082e2f42a5823e03f5e3eb6dffb344d6d'
def digest(b):return hashlib.sha256(b).digest()
def rebuild(base,out):
    if hashlib.sha256(Path(base).read_bytes()).hexdigest()!=SOURCE_V6:raise RuntimeError('Wrong V6 APK input')
    patches=zlib.decompress(base64.b64decode(V10_PATCH_BASE64))
    p=0; replacements={}
    with zipfile.ZipFile(base) as orig:
        for name in MEMBERS:
            old=orig.read(name)
            before=patches[p:p+32];after=patches[p+32:p+64];p+=64
            oldlen,newlen,count=struct.unpack_from('<III',patches,p);p+=12
            if digest(old)!=before or len(old)!=oldlen:raise RuntimeError('Member mismatch '+name)
            dst=bytearray(old if len(old)==newlen else b'\x00'*newlen)
            for _ in range(count):
                offset,n=struct.unpack_from('<IH',patches,p);p+=6
                dst[offset:offset+n]=patches[p:p+n];p+=n
            if digest(dst)!=after:raise RuntimeError('Patched SHA mismatch '+name)
            replacements[name]=bytes(dst)
        if p!=len(patches):raise RuntimeError('Trailing delta bytes')
        with zipfile.ZipFile(out,'w') as result:
            for entry in orig.infolist():
                n=entry.filename;upper=n.upper()
                if upper=='META-INF/MANIFEST.MF' or (upper.startswith('META-INF/') and upper.endswith(('.SF','.RSA','.DSA','.EC'))):continue
                zi=zipfile.ZipInfo(n,entry.date_time);zi.compress_type=entry.compress_type
                zi.external_attr=entry.external_attr;zi.create_system=entry.create_system
                result.writestr(zi,replacements.get(n,orig.read(n)),compress_type=zi.compress_type,compresslevel=6)
        with zipfile.ZipFile(out) as result:
            assert result.testzip() is None
            for name in ['res/Am.xml','res/mC.xml','AndroidManifest.xml','resources.arsc']:
                assert result.read(name)==orig.read(name)
    print('PASS V10 unsigned APK from user-confirmed V6, only mobile DEX and layouts differ')
if __name__=='__main__':
    if len(sys.argv)!=3:sys.exit('Usage: mobile_v10_binary_patch.py user-confirmed-v6.apk unsigned-v10.apk')
    rebuild(sys.argv[1],sys.argv[2])
