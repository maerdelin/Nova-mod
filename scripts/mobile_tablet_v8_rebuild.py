#!/usr/bin/env python3
"""Reproducible V8 mobile-only UI patch from SHA-pinned user-tested V7 APK.

TV/Leanback V6, automatic mode selection, TV layouts, and Android manifest
are unchanged. V8 restores the original V6 mobile toolbar, vertically centers
three mobile drawer entries in their FragmentContainerView, and replaces the
network shortcut's two-line label/URL with just a human-readable folder path.
WebDAV removes the service root path component (e.g. /dav/); SMB retains the
share path. Existing add-address and plus-button behavior is unchanged.

This reproduces unsigned APK content. Android v2 signing is a separate action:
re-sign with your OWN secure key to install; do not commit signing material.
"""
import base64,hashlib,struct,sys,zipfile,zlib
from pathlib import Path

V7_APK_SHA = '6d35f84f183e3ebe37557d318a45bbe21e4e9684ad114f60e1f47b7ba49493bb'
V7_DEX_SHA = 'dc49b1782b86e42668ec74ef8033d0845fdbad06029acc8e3760de6825c5d171'
V8_DEX_SHA = 'b6a42ce5d8bc9b055eebf6f40cbac427b5f5c259fbe019bc29eed8bd191d7eea'
V7_CATEGORY_SHA = '3f77e37c7475299a69a6f0a8af3da9de85ee94b8b01e252f201adaaaade0a04b'
V8_CATEGORY_SHA = 'aee22ef4106abad641bbcc4047e4d5f0bac8c0c246697daae039e71920aca120'
CODE_ITEMS = [
    (16137, 3856608, '7904190fb6f66eb6ff029b6f1e233845e244dd67738f4a4b8f2f033b541f564e', 'eNpjYWACQgaGk1rJDFVAulBgcRITAw9DnsLMJAWGfIV5EkYMeQJs9kwMXMx5CpoXjBgSmK0t8xS4gSweZnlmX6CozgWQGv4LIH0JjNuM8xS2sQgwcDEkMcYczlNYw8uMMFVgfRIDUCZPYTFQNERZL8yC2RAoav2KCWzaBw4LZk6GEAW9sBBjtbA8BRFzA7CqPIW1ZspgVqGAx0OI+zaaQUzIE5gHZOUJcDGBzMgTEGBhBtIgM/IUhIH6lZjfcRQoMNgrM0QrG4RBXcIcomQAlN+UpMzAxwAAltM0VQ=='),
    (18038, 3997104, 'f956d2e18a6155de2b1daec41c87fcc67b3695bc868d178e7afaa7dc4046c738', 'eNrjZGAGQgi4CMR5Av5y7AxcDEKCxgJRDPLsNzlDEpZH5SksXN7AwMMgz5DAGcLEH1Eo0MbBxMDDlCdQB6KZLZiNgDpzlzAzcLEIiZqHaDPkKVQtCQbK5Am0gFSwWLAoM0iz9sgzAmXKl4QA1VmwSDEIs+gD+SlLnIF8KxYhhhssLIxQc1hNQ7jApjgDTdFkYGEIYeaNyFModDMH2pTvxg40U5iVA6jiE28IkCxyU2fgQ7g+0FiAD+j6q5x5AkkgtQwJjGF2eQrThAWAqvINItzKOPgYhiYAAN65K5A='),
    (18040, 3996960, '19db4373e62a377e7d3e767b4865d99ec05c8d17dfcd3a476c1a5d6f6de1787a', 'eNpjY2BkYGKAAAcgDglYHpUnMHc5kBW4HsxiZAgJOhplwSTLUCQwZwUTAw9TkUA2kOZitmAWBorlgMSY8xRmLTdgEBIpFDi7mIWBhwXEd2TQZHj9XygEVSyBJcwOWcSBgY8BAQAXGyCP'),
]
CODE_OFF = [
    (18038, 8936572, 'a0faf301', 'b0fbf301'),
    (18040, 8936584, 'b0fbf301', 'a0faf301'),
]
PROTECTED = {
    'res/Am.xml':'b246497606d126efa7e56156952bfd059538b9ffb18afb7a1c4cc44380293262',
    'res/mC.xml':'559a5e7d1b679338e5fb9be9eface0ee1edc7ef4ca454651b851ed9084b6a1bc',
    'AndroidManifest.xml':'11774efa86dde2662b0fe8f9d9b36e41bc34864de5cd0fe4d1f31c2656e77712',
}
def sha(b):return hashlib.sha256(b).hexdigest()

def patch_dex(raw):
    if sha(raw)!=V7_DEX_SHA:raise ValueError('Wrong V7 base DEX')
    out=bytearray(raw)
    for mid,off,digest,encoded in CODE_ITEMS:
        block=zlib.decompress(base64.b64decode(encoded,validate=True))
        if sha(block)!=digest:raise ValueError(('Unexpected DEX code item',mid))
        regs,ins,outs,tries,debug,words=struct.unpack_from('<4H2I',block)
        assert len(block)==16+2*words
        if words!=struct.unpack_from('<I',raw,off+12)[0]:raise ValueError('DEX method resized')
        out[off:off+len(block)]=block
    for mid,off,expected,new in CODE_OFF:
        before=bytes.fromhex(expected);after=bytes.fromhex(new)
        if out[off:off+len(before)]!=before:raise ValueError(('Changed code_off input',mid))
        out[off:off+len(after)]=after
    out[12:32]=hashlib.sha1(out[32:]).digest()
    struct.pack_into('<I',out,8,zlib.adler32(out[12:])&0xffffffff)
    result=bytes(out)
    if sha(result)!=V8_DEX_SHA:raise ValueError('V8 DEX hash mismatch')
    for off,count in ((4263380,83),(4266828,134),(3841932,115)):
        assert result[off:off+16+2*count]==raw[off:off+16+2*count], 'TV method changed'
    return result

def patch_mobile_category(raw):
    if sha(raw)!=V7_CATEGORY_SHA:raise ValueError('Unexpected mobile category XML input')
    out=bytearray(raw)
    old=b'cacheColorHint';new=b'layout_gravity'
    assert len(old)==len(new)==14
    idx=out.find(old)
    if idx<0:raise ValueError('Category missing cacheColorHint')
    out[idx:idx+14]=new
    p=8
    while p<len(out):
        typ,header,size=struct.unpack_from('<HHI',out,p)
        assert size>=8
        if typ==0x180:
            off=p+8+4*4
            assert struct.unpack_from('<I',out,off)[0]==0x01010101
            struct.pack_into('<I',out,off,0x010100b3)
        if typ==0x102:
            start=p+16+20
            h=start+20+16
            assert struct.unpack_from('<I',out,h)[0]==0xffffffff
            struct.pack_into('<I',out,h,0xfffffffe)
            a=start+4*20
            assert out[a+15]==0x1c
            out[a+15]=0x10
            struct.pack_into('<I',out,a+16,0x10)
        p+=size
    result=bytes(out)
    if sha(result)!=V8_CATEGORY_SHA:raise ValueError('Updated menu XML hash mismatch')
    return result

def build(input_apk,output):
    if sha(Path(input_apk).read_bytes())!=V7_APK_SHA:raise ValueError('Not user-tested V7 signed APK')
    with zipfile.ZipFile(input_apk) as old:
        assert old.testzip() is None
        for name,digest in PROTECTED.items():
            assert sha(old.read(name))==digest,name
        d=patch_dex(old.read('classes.dex'))
        mobile=patch_mobile_category(old.read('res/Tl.xml'))
        with zipfile.ZipFile(output,'w',allowZip64=False) as new:
            for it in old.infolist():
                n=it.filename;up=n.upper()
                if up=='META-INF/MANIFEST.MF' or (up.startswith('META-INF/') and up.endswith(('.SF','.RSA','.DSA','.EC'))):continue
                e=zipfile.ZipInfo(n,it.date_time)
                e.compress_type=it.compress_type;e.external_attr=it.external_attr
                e.create_system=it.create_system
                data=d if n=='classes.dex' else mobile if n=='res/Tl.xml' else old.read(n)
                new.writestr(e,data,compress_type=e.compress_type,compresslevel=6)
        with zipfile.ZipFile(output) as new:
            assert new.testzip() is None
            changed=[n for n in new.namelist() if new.read(n)!=old.read(n)]
            assert sorted(changed)==['classes.dex','res/Tl.xml'],changed
            print('PASS: verified mobile V8 code and UI, only classes.dex & res/Tl.xml changed')

if __name__=='__main__':
    if len(sys.argv)!=3:sys.exit('Usage: mobile_tablet_v8_rebuild.py user-verified-v7.apk unsigned-v8.apk')
    build(sys.argv[1],sys.argv[2])
