#!/usr/bin/env python3
"""Exact V7 MOBILE/TABLET UI patch over the user-verified V6 signed APK.

R37 is used as UI reference ONLY. No R37 TV-mode lock, boot redirection, or
Leanback bytecode has been carried over. This is an exact binary reconstruction,
not the upstream Java/Kotlin source. No Android resources/manifest/TV XML change.

Usage:
 python3 scripts/mobile_tablet_v7_rebuild.py tested-v6.apk unsigned-v7.apk
Then zipalign and sign with your own secure Android signing key.
"""
import base64
import hashlib
import struct
import sys
import zipfile
import zlib
from pathlib import Path

V6_APK_SHA = '957819f313352ff54adcaac9000037d082e2f42a5823e03f5e3eb6dffb344d6d'
V6_DEX_SHA = '1f0194f96282bc3494e0ed17505a52d2cd552782cee5d534584480058b836e38'
V7_DEX_SHA = 'dc49b1782b86e42668ec74ef8033d0845fdbad06029acc8e3760de6825c5d171'
PROTECTED = {
    'res/Am.xml': 'b246497606d126efa7e56156952bfd059538b9ffb18afb7a1c4cc44380293262',
    'res/mC.xml': '559a5e7d1b679338e5fb9be9eface0ee1edc7ef4ca454651b851ed9084b6a1bc',
    'AndroidManifest.xml': '11774efa86dde2662b0fe8f9d9b36e41bc34864de5cd0fe4d1f31c2656e77712'
}
# Code items are in their original DEX slots; two mobile-only code_off pointers
# are swapped below to fit an external-storage listing without growing the DEX.
# Each triple: method ID, code-item byte offset, compressed replacement bytes.
CODE_ITEMS = [
 (16137,3856608,'eNpjYWACQgaGk1rJDFVAulBgcRITAw9DnsLMJAWGfIV5EkYMeQJs9kwMXMx5CpoXjBgSmK0t8xS4gSweZnlmX6CoDpAtzMAB1POJl5kBG4CbKrA+iYGBC6hyMVBliLJemAWzIVDU+hUT2LQPHBbMnAwhCnphIcZqYXkKIuYGYFV5CmvNlMGsQgGPhxD3bTSDmJAnMA/IyhPgYgKZkScgwMIMpEFm5CkIA/UrMb/jKFBgsFdmiFY2CIO6hDlEyQAovylJmYGPAQActC8d'),
 (16693,3894136,'eNrtzzEKwjAUxvEvoQUtKLEnKJ0cHYKzHQLOJQTeVnEXLXTSxWu4SxxcvItS76CLg7NGo6Bn0P/4+PHga4AhBNDrjzFigJ6ezURsLRAh7uxEXl6MTCLo0t2TjeU4ArfuNQ3S5lS0sgBFOJek9qYI64xUbeKK1MHo6uFXViGFl0DBl5K4k9wOiDuZE3ey9JJ/ycVLrr1M3xLPPiTTkpiTbJgRq42e+W/MLTm5JVYAbfz7ne7+w0Cf'),
 (16694,3894860,'eNpjZmBkYGJgYHBTSmbQANIhCm/CLBm4GJQYGKUKBKYtZ2CIBoposOQJzF0Okc1TMHBkgrAE1gDFuBgiFT6G8TFgBwBzrxCu'),
 (16702,3889380,'eNpjZGBkAAF9pWQGZiAtzMDOwM8AAAn6AOM='),
 (16714,3975796,'eNpjYmBigAFzIOZjoCcAACD0AEo='),
 (17726,3890268,'eNrjYmACQgiYD8QhDQpRQo55CqWcAkC2dJQFAytDnkC3OFCmSSaqSGDqCiYGhYY1nBYMoUB5yahChghOBgYexkKBSg5GIJ2nILFEgIGLwYLBlaGQYbUeUI5ZiZVRqkBg2nKQSav0mBl4GMCmKswBi6zBEFmJIbIUSPKwFAlkr2ABmy3OUCSQA2TzsMqzakoqsZ2UKFBIWhTGoMRux16gIGiUzlCkMGlFEYMmw/P/RQpTVkwCulUK6pcwVw6GoAa1qHsMDIyRQDpP4Iw4B8w+gTV2HAx8DOQCAPEjOGc='),
 (18040,3997104,'eNrjZGBkYGZgYDAwS2a4CKRDGpZH5QnMXQ5irYezjkZZMJgwFAnMXsHAwMVoyagHZM8BsnmAdDZYzIJRBcjOAYkxyjMmcIYI8UcwYICQJqDpCrOWCwFZ66OEhAsFzi5mZuBhBokZMWgy3PoPslUoECTOCDQJJC4AdlMCY5gdqigfw8gEAJvfLNM='),
 (18045,3997640,'eNqlUT1LxEAQfZt1L/Eu5NbvY1N4YGEWsRGblFrYixHF8mysAjlBsbER9IQ7ES20UAQJSMDGPyDYWPkDLAPXXWFnHWeTn+DA2/dmmBlmZh04EAD6m/v4JvbZT5NhSXyQVphZTtpPuYCLRPIB4MHn1/MMQcvnfcPTPvcksbSnAs/n1gTpuuKjLLB9HnjkccWHWSwPUgt1oex8PBQO4vZx2iU/FDXSO+kiXEuJtUbS7r5vweUmv1bmA6FoYvJ3JXKgxGzDzBPBtU3VUclpegjzLiCWbymnTok8dyziiH3uxfJrjpUdL0xMdMZau/F2vr7aiWVvg6Eys9cwAzRei2pujRdSozL2XFSbaTySMvfRuC+qzTVui+oWGldFdR2NywL/NeaUdEI4JZwRegT6BNwQ7ggPhD/yQEpl')
]
CODE_OFF = [
 (8922706,bytes.fromhex('dcb8ed01'),bytes.fromhex('f4d4f201')),
 (8933502,bytes.fromhex('f4d4f201'),bytes.fromhex('dcb8ed01'))
]

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def patch_dex(source):
    if sha(source)!=V6_DEX_SHA:
        raise ValueError('Input DEX is NOT the verified V6 baseline')
    result=bytearray(source)
    for mid,offset,encoded in CODE_ITEMS:
        body=zlib.decompress(base64.b64decode(encoded,validate=True))
        regs,ins,outs,tries,debug,words=struct.unpack_from('<4H2I',body)
        _,_,_,_,_,old_words=struct.unpack_from('<4H2I',source,offset)
        if len(body)!=16+2*words or words!=old_words:
            raise ValueError(('Unexpected DEX code item dimensions',mid))
        result[offset:offset+len(body)]=body
    for off,expected,new in CODE_OFF:
        if bytes(result[off:off+len(expected)])!=expected:
            raise ValueError('Unexpected class_data code_off')
        result[off:off+len(new)]=new
    result[12:32]=hashlib.sha1(result[32:]).digest()
    struct.pack_into('<I',result,8,zlib.adler32(result[12:])&0xffffffff)
    built=bytes(result)
    if len(built)!=len(source) or sha(built)!=V7_DEX_SHA:
        raise ValueError('V7 DEX does not match pinned result')
    for off,units in [(4263380,83),(4266828,134),(3841932,115)]:
        assert built[off:off+16+units*2]==source[off:off+16+units*2], 'TV V6 bytecode changed'
    return built

def build(baseline,output):
    if sha(Path(baseline).read_bytes())!=V6_APK_SHA:
        raise ValueError('Input APK is not the user-confirmed V6 signed build')
    with zipfile.ZipFile(baseline) as original:
        if original.testzip() is not None: raise ValueError('Input APK invalid')
        for name,expected in PROTECTED.items():
            assert sha(original.read(name))==expected, name
        new_dex=patch_dex(original.read('classes.dex'))
        with zipfile.ZipFile(output,'w',allowZip64=False) as target:
            for entry in original.infolist():
                name=entry.filename; upper=name.upper()
                if upper=='META-INF/MANIFEST.MF' or (upper.startswith('META-INF/') and upper.endswith(('.SF','.RSA','.DSA','.EC'))):continue
                info=zipfile.ZipInfo(name,entry.date_time)
                info.compress_type=entry.compress_type
                info.external_attr=entry.external_attr
                info.create_system=entry.create_system
                target.writestr(info,new_dex if name=='classes.dex' else original.read(name),compress_type=info.compress_type,compresslevel=6)
        with zipfile.ZipFile(output) as target:
            assert target.testzip() is None
            assert sha(target.read('classes.dex'))==V7_DEX_SHA
            for name in target.namelist():
                if name!='classes.dex': assert target.read(name)==original.read(name), name
    print('PASS: V7 mobile-only UI patch; exact V6 TV layout and code preserved',output)

if __name__=='__main__':
    if len(sys.argv)!=3: sys.exit(__doc__)
    build(sys.argv[1],sys.argv[2])
