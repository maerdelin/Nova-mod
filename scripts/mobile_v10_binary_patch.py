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
V10_PATCH_BASE64 = """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"""
MEMBERS=['classes.dex','res/Tl.xml','res/2a.xml','res/_J.xml','res/yt.xml']
SOURCE_V6_DEX='1f0194f96282bc3494e0ed17505a52d2cd552782cee5d534584480058b836e38'
def digest(b):return hashlib.sha256(b).digest()
def rebuild(base,out):
    with zipfile.ZipFile(base) as check:
        if hashlib.sha256(check.read('classes.dex')).hexdigest()!=SOURCE_V6_DEX:raise RuntimeError('Wrong V6 DEX input')
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
