#!/usr/bin/env python3
"""Disable the homepage ListRow header presenter for every locale.
Change one Dalvik register in MainFragment.loadRows from v5 to v3 (null).
Do not modify method sizes, opcode widths, branches, assets or translations.
"""
import hashlib,struct,zlib
INPUT_DEX_SHA='5a80942986604fd954922b39ee415b0e6d0baab6773ec789c8fbfb5db9a6fd1d'
OUTPUT_DEX_SHA='8f4c363d26747747644faf46b6eb3e7eb6fa373fdbb975c8c4fc0fd483f92a1a'
CODE_ITEM=4128208
HEADER_INVOKE_UNIT=58
ORIGINAL_CALL=bytes.fromhex('6e20a9dc5100')
HIDDEN_CALL=bytes.fromhex('6e20a9dc3100')
ICON_HEADER_CALL=bytes.fromhex('6e20a9dc1200')
def sha(b):return hashlib.sha256(b).hexdigest()
def text_value(data,idx):
    cnt,off=struct.unpack_from('<II',data,56)
    if idx>=cnt:raise ValueError('Unexpected string')
    p=struct.unpack_from('<I',data,off+idx*4)[0]
    for _ in range(5):
        v=data[p];p+=1
        if v<128:break
    else:raise ValueError('Invalid ULEB128')
    return data[p:data.index(b'\0',p)].decode('utf-8')
def type_value(data,idx):
    cnt,off=struct.unpack_from('<II',data,64)
    if idx>=cnt:raise ValueError('Unexpected type')
    return text_value(data,struct.unpack_from('<I',data,off+idx*4)[0])
def method_value(data,idx):
    cnt,off=struct.unpack_from('<II',data,88)
    if idx>=cnt:raise ValueError('Unexpected method')
    cl,proto,name=struct.unpack_from('<HHI',data,off+idx*8)
    return type_value(data,cl),text_value(data,name)
def patch(data):
    if sha(data)!=INPUT_DEX_SHA:raise ValueError('Unexpected DEX baseline')
    if method_value(data,19493)!=('Lcom/archos/mediacenter/video/leanback/MainFragment;','loadRows'):
        raise ValueError('Wrong loadRows method identity')
    if method_value(data,0xdca9)[1]!='setHeaderPresenter':
        raise ValueError('Wrong RowPresenter method index')
    header=struct.unpack_from('<4H2I',data,CODE_ITEM)
    if header[:4]!=(12,1,7,0) or header[5]!=1096:
        raise ValueError('Unexpected home row method layout')
    start=CODE_ITEM+16
    if data[start+31*2:start+32*2]!=bytes.fromhex('1203'):
        raise ValueError('Expected v3=null missing')
    if data[start+66*2:start+69*2]!=ICON_HEADER_CALL:
        raise ValueError('Icon header presenter changed')
    pos=start+HEADER_INVOKE_UNIT*2
    if data[pos:pos+6]!=ORIGINAL_CALL:
        raise ValueError('Home header invoke mismatch')
    result=bytearray(data)
    result[pos:pos+6]=HIDDEN_CALL
    result[12:32]=hashlib.sha1(result[32:]).digest()
    struct.pack_into('<I',result,8,zlib.adler32(result[12:])&0xffffffff)
    result=bytes(result)
    if sha(result)!=OUTPUT_DEX_SHA:raise ValueError('Unexpected output DEX sha')
    if result[32:pos]!=data[32:pos] or result[pos+6:]!=data[pos+6:]:
        raise ValueError('Extra code changes detected')
    return result
