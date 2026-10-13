"""Center the exact pinned Nova V7.14 Leanback home rows using compiled XML.

The parent BrowseRowsFrameLayout remains match_parent. FrameLayout applies
CENTER_HORIZONTAL to a card-group-width child at any screen width. No DEX
code or item size/spacing/focus behavior is changed.
"""
import hashlib
import struct

TARGET='res/Am.xml'
INPUT_SHA='328d0fba66e5debd7b491b994048eacacf622bd31e88377abd0693b4e7fb4c74'
OUTPUT_SHA='23af2a9b483d1ae1c56a7bd0f17f8047c230c7a434288d0201697e8471969467'
GRAVITY_ATTR=0x010100B3
CARD_GROUP_WIDTH_DP=760

def hdr(data,at=0):return struct.unpack_from('<HHI',data,at)
def sha(data):return hashlib.sha256(data).hexdigest()

def patch(data):
    if sha(data)!=INPUT_SHA:raise ValueError('Unexpected V7.14 home XML input')
    assert hdr(data)==(3,8,len(data))
    chunks=[];pos=8;found=0
    while pos<len(data):
        tag,head,length=hdr(data,pos)
        assert head>=8 and length>=head and pos+length<=len(data)
        chunk=data[pos:pos+length]
        if tag==1:
            assert hdr(chunk)==(1,28,416)
            count,style_count,flags,start,style_start=struct.unpack_from('<5I',chunk,8)
            assert (count,style_count,flags,start,style_start)==(14,0,256,84,0)
            indexes=chunk[28:84];body=chunk[84:]
            extra=b'\x0e\x0e'+b'layout_gravity\0'
            new_body=body+extra
            new_body+=bytes((-len(new_body))%4)
            chunk=bytearray(chunk[:28]+indexes+struct.pack('<I',len(body))+new_body)
            struct.pack_into('<I',chunk,4,len(chunk))
            struct.pack_into('<I',chunk,8,15)
            struct.pack_into('<I',chunk,20,88)
        elif tag==0x0180:
            assert hdr(chunk)==(0x0180,8,40)
            assert struct.unpack_from('<I',chunk,8+5*4)[0]==0x010100F4
            chunk=bytearray(chunk+struct.pack('<7I',0,0,0,0,0,0,GRAVITY_ATTR))
            struct.pack_into('<I',chunk,4,len(chunk))
        elif tag==0x0102 and struct.unpack_from('<I',chunk,20)[0]==12:
            found+=1
            start,step,count=struct.unpack_from('<3H',chunk,24)
            assert (start,step,count)==(20,20,3)
            at=16+start
            attrs=[bytearray(chunk[at+i*20:at+(i+1)*20]) for i in range(count)]
            assert [struct.unpack_from('<I',a,4)[0] for a in attrs]==[0,5,6]
            assert attrs[1][15]==0x10 and struct.unpack_from('<I',attrs[1],16)[0]==0xffffffff
            attrs[1][15]=5 # TypedValue.TYPE_DIMENSION
            struct.pack_into('<I',attrs[1],16,(CARD_GROUP_WIDTH_DP<<8)|1) # dip, radix0
            ns=struct.unpack_from('<I',attrs[0],0)[0]
            gravity=struct.pack('<IIIHBBI',ns,14,0xffffffff,8,0,0x10,1)
            chunk=bytearray(chunk[:at]+gravity+b''.join(attrs))
            struct.pack_into('<I',chunk,4,len(chunk))
            struct.pack_into('<H',chunk,28,4)
        chunks.append(bytes(chunk));pos+=length
    assert pos==len(data) and found==1
    out=bytearray(data[:8]+b''.join(chunks))
    struct.pack_into('<I',out,4,len(out))
    result=bytes(out)
    if sha(result)!=OUTPUT_SHA:raise ValueError('Unexpected centered compiled XML hash')
    return result
