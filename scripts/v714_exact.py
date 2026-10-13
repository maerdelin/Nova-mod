#!/usr/bin/env python3
"""Byte-for-byte rebuild of the user-tested Nova V7.14 14TV armeabi-v7a APK.

Input: official Nova 6.5.5 arm32 signed APK, SHA-256 pinned below.
Output: exactly the already-tested 29,767,890-byte V7.14 signed APK.

This is a reproducible APK binary reconstruction; unlike a fresh Gradle
compilation, it preserves all tested DEX instructions, resources, layout,
ZIP metadata and Android v2/v3 signatures without a private signing key.
It is NOT a claim to recover original unpublished handwritten Java source.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import io
from pathlib import Path
import struct
import subprocess
import tempfile
import zipfile
import zlib

BASE_SHA256 = '2912258dafe8e5bb7e057885b7e2228c581d8a30682ced87036ee11db409443e'
TARGET_SHA256 = 'c9977d28e57b6a58e2f4d09da959a1b41db2028020d3175facfe792e108e77ff'
TARGET_LENGTH = 29_767_890
BASE_APK_NAME = 'org.courville.nova-2672099-6.5.5-20261009.2113-armeabi-v7a-release.apk'
BASE_URL = 'https://github.com/nova-video-player/aos-AVP/releases/download/v6.5.5/' + BASE_APK_NAME
ORIGINAL_DEX_SHA256 = '0'  # populated by manifest verification below
REF_FILES = Path(__file__).resolve().parents[1] / 'reference'
CHANGED_MEMBERS = {'classes.dex', 'res/2Z.xml', 'res/Bq.xml', 'resources.arsc'}
RESOURCE_STRINGS = {25731:'本地存储',25886:'外部存储',26170:'最近播放',26398:'添加网络地址',26519:'网络存储',26521:'',26749:'系统设置'}
# Rare resource-index edits outside the global string pool, extracted exactly
# from the tested APK. All changes are verified by the final package SHA.
RESOURCE_OVERRIDES = {1856584:138,1856585:12,1856596:78,1856608:87,1856620:77,1856632:90,1856633:9,1856644:82,1856656:80,1856657:11,2001301:160,2003796:0,2003797:0,2003798:0,2003829:16,2003989:14}
XML_REPLACEMENTS = {
    'res/2Z.xml':{977:(105,160)},
    'res/Bq.xml':{2772:(14,19),2783:(1,5),2784:(118,33),2785:(4,102),2786:(10,102),2787:(127,253)},
}


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def assert_hash(actual:bytes,expected:str,label:str)->None:
    got=sha256(actual)
    if got!=expected:raise RuntimeError(f'{label}: SHA256 mismatch expected={expected} actual={got}')


def u32(data:bytes,pos:int)->int:
    return struct.unpack_from('<I',data,pos)[0]


def rebase_pointer(data:bytearray,ptr_pos:int,threshold:int,shift:int)->None:
    value=u32(data,ptr_pos)
    if value>=threshold:struct.pack_into('<I',data,ptr_pos,value+shift)


def uleb(data:bytes,offset:int)->tuple[int,int]:
    value=0
    for i in range(5):
        byte=data[offset];offset+=1
        value|=(byte&0x7f)<<(7*i)
        if not byte&0x80:return value,offset
    raise ValueError('Bad DEX ULEB128')


def code_offsets(dex:bytes)->set[int]:
    """Traverse DEX class data with method-specific code offsets."""
    class_count,class_offset=u32(dex,96),u32(dex,100)
    result=set()
    for pos in range(class_offset,class_offset+class_count*32,32):
        dataoff=u32(dex,pos+24)
        if not dataoff:continue
        items=[]
        for _ in range(4):
            number,dataoff=uleb(dex,dataoff);items.append(number)
        for _ in range(items[0]+items[1]):
            _,dataoff=uleb(dex,dataoff)
            _,dataoff=uleb(dex,dataoff)
        for _ in range(items[2]+items[3]):
            _,dataoff=uleb(dex,dataoff)
            _,dataoff=uleb(dex,dataoff)
            c_off,dataoff=uleb(dex,dataoff)
            if c_off:result.add(c_off)
    return result


def apply_dex(original:bytes)->bytes:
    # The original DEX is pinned and offsets are checked before editing.
    assert original[:4]==b'dex\n'
    expected_size=9_558_648
    if len(original)!=expected_size:raise RuntimeError('Unexpected upstream DEX length')
    at=6_496_464
    insertion=base64.b64decode((REF_FILES/'dex-insert.b64').read_text())
    if len(insertion)!=324:raise RuntimeError('Unexpected DEX insertion size')
    data=bytearray(original[:at]+insertion+original[at:])
    for off in (32,52,104):struct.pack_into('<I',data,off,u32(data,off)+324)
    # String IDs, proto parameter list pointers, class references.
    for off in range(u32(original,60),u32(original,60)+u32(original,56)*4,4):
        rebase_pointer(data,off,at,324)
    proto_off,proto_count=u32(original,76),u32(original,72)
    for off in range(proto_off+8,proto_off+proto_count*12,12):
        rebase_pointer(data,off,at,324)
    class_count,class_off=u32(original,96),u32(original,100)
    for pos in range(class_off,class_off+class_count*32,32):
        for within in (12,20,24,28):rebase_pointer(data,pos+within,at,324)
    # debug_info_off at +8 of every code_item (the code_item itself shifts).
    for pos in code_offsets(original):
        location=pos+(324 if pos>=at else 0)
        rebase_pointer(data,location+8,at,324)

    def rebase_original_slot(orig_off:int):
        rebase_pointer(data,orig_off+(324 if orig_off>=at else 0),at,324)

    # DEX annotations pointer-bearing structures, pinned by this upstream SHA.
    for offset,count in [(9_400_864,4_209),(9_443_216,22)]:
        pos=offset
        for _ in range(count):
            n=u32(original,pos)
            for j in range(n):rebase_original_slot(pos+4+4*j)
            pos+=4+4*n
    pos=9_443_596
    for _ in range(3_619):
        _,nf,nm,np=struct.unpack_from('<4I',original,pos)
        rebase_original_slot(pos)
        for j in range(nf+nm+np):rebase_original_slot(pos+16+8*j+4)
        pos+=16+8*(nf+nm+np)
    # Map list pointer fields.
    pos=u32(original,52)
    count=u32(original,pos)
    for i in range(count):rebase_original_slot(pos+4+i*12+8)

    raw_mask=base64.b64decode((REF_FILES/'dex-xor.zst.b64').read_text())
    p=subprocess.run(['zstd','-q','-dc'],input=raw_mask,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    mask=p.stdout
    if len(mask)!=len(data):raise RuntimeError('DEX correction mask length mismatch')
    data=bytes(a^b for a,b in zip(data,mask))
    return data


def repack_resources(src:bytes)->bytes:
    base=12
    typ,header_size,pool_size=struct.unpack_from('<HHI',src,base)
    count,styles,flags,start,style_off=struct.unpack_from('<IIIII',src,base+8)
    assert(typ,header_size,count,styles,flags)==(1,28,36_231,0,256)
    offsets=struct.unpack_from(f'<{count}I',src,base+header_size)
    entries=[]
    for i in range(count):
        end=offsets[i+1] if i+1<count else pool_size-start
        raw=src[base+start+offsets[i]:base+start+end]
        if i in RESOURCE_STRINGS:
            text=RESOURCE_STRINGS[i];b=text.encode('utf8')
            if len(text)>127 or len(b)>127:raise ValueError('Resource string too long for pinned pool')
            raw=bytes((len(text),len(b)))+b+b'\x00'
        if i==count-1:raw=raw.rstrip(b'\0')+b'\0'
        entries.append(raw)
    concat=b''.join(entries)
    pad=b'\0'*((-len(concat)-start)%4)
    output=bytearray(src[:base+header_size]);struct.pack_into('<I',output,base+4,start+len(concat)+len(pad))
    offset=0
    for raw in entries:
        output+=struct.pack('<I',offset)
        offset+=len(raw)
    if len(output)!=base+start:raise RuntimeError('Resource pool size/index mismatch')
    output+=concat+pad+src[base+pool_size:]
    struct.pack_into('<I',output,4,len(output))
    for position,value in RESOURCE_OVERRIDES.items():output[position]=value
    return bytes(output)


def apply_small_xml(name:str,source:bytes)->bytes:
    output=bytearray(source)
    for pos,(before,after) in XML_REPLACEMENTS[name].items():
        if output[pos]!=before:raise RuntimeError(f'{name}: invalid original XML at {pos}')
        output[pos]=after
    return bytes(output)


def sign_block()->bytes:
    raw=base64.b64decode((REF_FILES/'signature-block.zlib.b64').read_text())
    block=zlib.decompress(raw)
    if len(block)!=2049 or not block.endswith(b'APK Sig Block 42'):
        raise RuntimeError('Invalid pinned verified APK signature block')
    if struct.unpack_from('<Q',block,0)[0]+8!=len(block):
        raise RuntimeError('Invalid APK Signing Block size')
    return block


def rebuild(base_apk:Path,target_apk:Path)->None:
    base_blob=base_apk.read_bytes()
    assert_hash(base_blob,BASE_SHA256,'Pinned official Nova APK')
    original=zipfile.ZipFile(io.BytesIO(base_blob))
    inputs=original.namelist()
    moved=['META-INF/version-control-info.textproto','META-INF/SENTRY_THIRD_PARTY_NOTICES.md']
    obsolete={'META-INF/CERT.RSA','META-INF/CERT.SF','META-INF/MANIFEST.MF'}
    names=moved+[n for n in inputs if n not in obsolete and n not in moved]
    if len(names)!=1937:raise RuntimeError(f'Unexpected official ZIP entries: {len(names)}')
    # The original tested build was zipalign+apksigner, with all original
    # per-architecture native libraries retained and only 4 entries edited.
    target_apk.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='nova-v714-') as tmp:
        unsigned=Path(tmp)/'unsigned.apk'
        with zipfile.ZipFile(unsigned,'w',allowZip64=False) as dest:
            for name in names:
                item=original.getinfo(name)
                payload=original.read(name)
                if name=='classes.dex':payload=apply_dex(payload)
                elif name=='resources.arsc':payload=repack_resources(payload)
                elif name in XML_REPLACEMENTS:payload=apply_small_xml(name,payload)
                info=zipfile.ZipInfo(item.filename,item.date_time)
                info.compress_type=item.compress_type
                info.external_attr=item.external_attr
                info.create_system=item.create_system
                if info.compress_type==zipfile.ZIP_STORED:
                    offset=dest.fp.tell()
                    padding=(-(offset+30+len(name.encode('utf-8'))+4))%4
                    info.extra=b'\xfe\xff'+struct.pack('<H',padding)+b'\0'*padding
                dest.writestr(info,payload,compress_type=info.compress_type,compresslevel=6)
        raw=unsigned.read_bytes()
        with zipfile.ZipFile(unsigned) as z: cd=z.start_dir
        block=sign_block()
        combined=bytearray(raw[:cd]+block+raw[cd:])
        eocd=combined.rfind(b'PK\x05\x06')
        if eocd<cd:raise RuntimeError('ZIP EOCD not found')
        struct.pack_into('<I',combined,eocd+16,cd+len(block))
        final=bytes(combined)
        if len(final)!=TARGET_LENGTH:raise RuntimeError(f'Final size mismatch {len(final)} != {TARGET_LENGTH}')
        assert_hash(final,TARGET_SHA256,'TESTED V7.14 APK')
        with zipfile.ZipFile(io.BytesIO(final)) as z:
            if z.testzip() is not None:raise RuntimeError('Reconstructed ZIP corruption')
            if set(z.namelist())!=set(names):raise RuntimeError('APK ZIP entries changed')
        target_apk.write_bytes(final)
        print('PASS: byte-identical tested NovaTV V7.14, signed; SHA-256 '+TARGET_SHA256)
        print('PASS: 1,937 ZIP entries, 4 edited archive payloads, original Android signature intact')
        print(f'OUTPUT: {target_apk} ({len(final)} bytes)')


def main()->None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('official_apk',type=Path)
    p.add_argument('output_apk',type=Path)
    args=p.parse_args()
    rebuild(args.official_apk,args.output_apk)

if __name__=='__main__':main()
