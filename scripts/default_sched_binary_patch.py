#!/usr/bin/env python3
import zipfile,struct,sys
from pathlib import Path
SRC=Path(sys.argv[1]); OUT=Path(sys.argv[2])
PATCHES={
 'lib/arm64-v8a/libavos.so':[('arm64',0x9a934),('arm64',0x9a950),('arm64',0xb4c14),('arm64',0xb5034)],
 'lib/armeabi-v7a/libavos.so':[('arm',0x78eec),('arm',0x78f14),('arm',0x99800),('arm',0x99844)],
 'lib/x86/libavos.so':[('x86',0x915ba),('x86',0x915df),('x86',0xb263a),('x86',0xb268b)],
 'lib/x86_64/libavos.so':[('x86',0x9a912),('x86',0x9a92c),('x86',0xb7082),('x86',0xb75d1)],
}
def va_to_off(b,va):
    if b[:4]!=b'\x7fELF' or b[5]!=1: raise RuntimeError('ELF/little-endian expected')
    cls=b[4]
    if cls==1:
        phoff=struct.unpack_from('<I',b,28)[0]; entsz=struct.unpack_from('<H',b,42)[0]; num=struct.unpack_from('<H',b,44)[0]
        for i in range(num):
            o=phoff+i*entsz
            typ,off,vaddr,paddr,filesz,memsz,flags,align=struct.unpack_from('<IIIIIIII',b,o)
            if typ==1 and vaddr<=va<vaddr+filesz:return off+(va-vaddr)
    elif cls==2:
        phoff=struct.unpack_from('<Q',b,32)[0]; entsz=struct.unpack_from('<H',b,54)[0]; num=struct.unpack_from('<H',b,56)[0]
        for i in range(num):
            o=phoff+i*entsz
            typ,flags,off,vaddr,paddr,filesz,memsz,align=struct.unpack_from('<IIQQQQQQ',b,o)
            if typ==1 and vaddr<=va<vaddr+filesz:return off+(va-vaddr)
    raise RuntimeError('VA not mapped')
def patch_lib(data,items,name):
    b=bytearray(data)
    for arch,va in items:
        off=va_to_off(b,va)
        if arch=='arm64':
            old=struct.unpack_from('<I',b,off)[0]
            if old & 0xfc000000 != 0x94000000: raise RuntimeError(name+' arm64 guard')
            b[off:off+4]=struct.pack('<I',0x52800000)
        elif arch=='arm':
            old=struct.unpack_from('<I',b,off)[0]
            if old & 0xff000000 != 0xeb000000: raise RuntimeError(name+' arm guard')
            b[off:off+4]=struct.pack('<I',0xe3a00000)
        else:
            if b[off]!=0xe8: raise RuntimeError(name+' x86 guard')
            b[off:off+5]=b'\x31\xc0\x90\x90\x90'
    return bytes(b)
with zipfile.ZipFile(SRC) as zin, zipfile.ZipFile(OUT,'w',allowZip64=True) as zout:
    for info in zin.infolist():
        data=zin.read(info.filename)
        if info.filename in PATCHES:data=patch_lib(data,PATCHES[info.filename],info.filename)
        zout.writestr(info,data)
with zipfile.ZipFile(OUT) as z:
    if z.testzip() is not None: raise RuntimeError('zip verify failed')
print('DEFAULT_SCHED_PATCH=PASS')
