import zipfile, struct, hashlib, zlib, sys, shutil
from pathlib import Path
sys.path.insert(0,'/mnt/data')
from dex_inspect import Dex
from cryptography import x509
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

SRC=Path('/mnt/data/NOVA-6.5.5-Network-UI-R16-armeabi-v7a.apk')
UNSIGNED=Path('/mnt/data/NOVA-6.5.5-Network-UI-R17-armeabi-v7a-unsigned.apk')
OUT=Path('/mnt/data/NOVA-6.5.5-Network-UI-R17-armeabi-v7a.apk')
DEX=Path('/mnt/data/r17_classes.dex')
KEY=Path('/mnt/data/nova_r2_key.pem')
CERT=Path('/mnt/data/nova_r2_cert.pem')

with zipfile.ZipFile(SRC,'r') as z:
    infos={zi.filename:zi for zi in z.infolist() if not zi.is_dir()}
    entries={zi.filename:z.read(zi.filename) for zi in z.infolist() if not zi.is_dir()}
    DEX.write_bytes(entries['classes.dex'])

dx=Dex(str(DEX)); raw=bytearray(DEX.read_bytes())

def method(desc,name,insns_size=None):
    ms=[m for m in dx.class_methods(desc) if m['name']==name and (insns_size is None or m['insns_size']==insns_size)]
    if len(ms)!=1: raise RuntimeError((desc,name,insns_size,len(ms)))
    return ms[0]

def words(m): return list(struct.unpack_from('<%dH'%m['insns_size'],raw,m['code_off']+16))
def put_words(m,ws):
    if len(ws)!=m['insns_size']: raise RuntimeError((m['name'],len(ws),m['insns_size']))
    struct.pack_into('<%dH'%len(ws),raw,m['code_off']+16,*ws)

def method_idx(owner,name):
    oi=dx.types.index(owner)
    hits=[i for i,(c,p,n) in enumerate(dx.methods) if c==oi and dx.strings[n]==name]
    if len(hits)!=1: raise RuntimeError(('method',owner,name,hits))
    return hits[0]

UI='Lcom/archos/mediacenter/video/UiChoiceDialog;'
m=method(UI,'applicationIsInLeanbackMode',115)
assert m['tries']==0 and m['ins']==1
ws=[0x0012, 0x000f] + [0x0000]*(m['insns_size']-2)
put_words(m,ws)

MA='Lcom/archos/mediacenter/video/browser/MainActivity;'
m=method(MA,'checkUiChoice',135)
assert m['tries']==0
put_words(m,[0x000e]+[0x0000]*(m['insns_size']-1))

VPC='Lcom/archos/mediacenter/video/utils/VideoPreferencesCommon;'
m=method(VPC,'onCreatePreferences',2475)
assert m['tries']==0
ws=words(m)
SET_VISIBLE=method_idx('Landroidx/preference/Preference;','setVisible')

assert ws[0x7e9]==0x0338 and ws[0x7ea]==0x0018, [hex(x) for x in ws[0x7e7:0x7ed]]
patch=[0x0612,0x206e,SET_VISIBLE,0x0063]
ws[0x7eb:0x801]=patch+[0x0000]*((0x801-0x7eb)-len(patch))

assert ws[0x832]==0x0338 and ws[0x833]==0x000a, [hex(x) for x in ws[0x830:0x836]]
ws[0x834:0x83c]=patch+[0x0000]*((0x83c-0x834)-len(patch))

assert ws[0x8b1]==0x0238 and ws[0x8b2]==0x000a, [hex(x) for x in ws[0x8af:0x8b5]]
patch2=[0x0312,0x206e,SET_VISIBLE,0x0032]
ws[0x8b3:0x8bb]=patch2+[0x0000]*((0x8bb-0x8b3)-len(patch2))
put_words(m,ws)

raw[12:32]=hashlib.sha1(raw[32:]).digest()
struct.pack_into('<I',raw,8,zlib.adler32(raw[12:]) & 0xffffffff)
DEX.write_bytes(raw)
entries['classes.dex']=DEX.read_bytes()

def parse_string_pool(buf, off):
    typ,hdr,size=struct.unpack_from('<HHI',buf,off)
    if typ!=0x0001: raise ValueError(('not string pool',hex(typ),off))
    sc,stylec,flags,ss,stylesStart=struct.unpack_from('<IIIII',buf,off+8)
    utf8=bool(flags & 0x100)
    offs=[struct.unpack_from('<I',buf,off+hdr+4*i)[0] for i in range(sc)]
    base=off+ss; out=[]
    def d8(p):
        x=buf[p]; p+=1
        if x&0x80:return ((x&0x7f)<<8)|buf[p],p+1
        return x,p
    def d16(p):
        x=struct.unpack_from('<H',buf,p)[0]; p+=2
        if x&0x8000:return ((x&0x7fff)<<16)|struct.unpack_from('<H',buf,p)[0],p+2
        return x,p
    for o in offs:
        p=base+o
        if utf8:
            _,p=d8(p); ln,p=d8(p); out.append(bytes(buf[p:p+ln]).decode('utf-8','replace'))
        else:
            ln,p=d16(p); out.append(bytes(buf[p:p+ln*2]).decode('utf-16le','replace'))
    return out,size

def patch_axml(data, callback):
    buf=bytearray(data); typ,hdr,size=struct.unpack_from('<HHI',buf,0)
    if typ!=0x0003: raise ValueError('not binary xml')
    strings,spsz=parse_string_pool(buf,hdr); off=hdr+spsz
    if off<len(buf):
        ct,ch,cs=struct.unpack_from('<HHI',buf,off)
        if ct==0x0180: off+=cs
    stack=[]
    while off<len(buf):
        ct,ch,cs=struct.unpack_from('<HHI',buf,off)
        if ct==0x0102:
            line,comment,ns,name=struct.unpack_from('<IIII',buf,off+8)
            ast,asz,ac,ii,ci,si=struct.unpack_from('<HHHHHH',buf,off+24)
            tag=strings[name]; attrs=[]; aoff=off+16+ast
            for i in range(ac):
                base=aoff+i*asz
                ans,aname,araw=struct.unpack_from('<III',buf,base)
                vs,r0,dt,val=struct.unpack_from('<HBBI',buf,base+12)
                attrs.append({'name':strings[aname],'dtype':dt,'data':val,'base':base})
            callback(buf,tag,attrs,stack); stack.append(tag)
        elif ct==0x0103:
            if stack: stack.pop()
        off+=cs
    return bytes(buf)

TARGET_TEXT=0x7f1205af
seen={'count':0}
def hide_index_button(buf,tag,attrs,stack):
    if tag!='Button': return
    if not any(a['name']=='text' and a['data']==TARGET_TEXT for a in attrs): return
    seen['count']+=1
    for a in attrs:
        if a['name'] in ('layout_width','layout_height'):
            struct.pack_into('<I',buf,a['base']+16,0)

if 'res/GE.xml' not in entries: raise RuntimeError('res/GE.xml missing')
entries['res/GE.xml']=patch_axml(entries['res/GE.xml'],hide_index_button)
if seen['count']!=1: raise RuntimeError(('Add-to-library button match count',seen['count']))

with open(UNSIGNED,'wb') as fout:
    with zipfile.ZipFile(fout,'w',allowZip64=True) as zout:
        for name,zi in infos.items():
            if name.startswith('META-INF/'): continue
            content=entries[name]
            nzi=zipfile.ZipInfo(name,zi.date_time)
            nzi.compress_type=zi.compress_type; nzi.comment=zi.comment
            nzi.internal_attr=zi.internal_attr; nzi.external_attr=zi.external_attr
            nzi.create_system=zi.create_system; nzi.flag_bits=zi.flag_bits & ~0x08; nzi.extra=b''
            if name=='resources.arsc':
                nzi.compress_type=zipfile.ZIP_STORED
                cur=fout.tell(); baseoff=cur+30+len(name.encode('utf-8'))
                pad=next(n for n in range(4) if (baseoff+4+n)%4==0)
                nzi.extra=struct.pack('<HH',0xFFFF,pad)+b'\0'*pad
            zout.writestr(nzi,content,compress_type=nzi.compress_type,compresslevel=6)

ALG=0x0103; V2_ID=0x7109871a; MAGIC=b'APK Sig Block 42'; CHUNK=1024*1024
def lp(x): return struct.pack('<I',len(x))+x
def digest_sections(sections):
    chunks=[]
    for sec in sections:
        for i in range(0,len(sec),CHUNK):
            c=sec[i:i+CHUNK]
            chunks.append(hashlib.sha256(b'\xa5'+struct.pack('<I',len(c))+c).digest())
    return hashlib.sha256(b'\x5a'+struct.pack('<I',len(chunks))+b''.join(chunks)).digest()

d=UNSIGNED.read_bytes(); eo=d.rfind(b'PK\x05\x06',max(0,len(d)-65557))
if eo<0: raise RuntimeError('EOCD not found')
cd_off=struct.unpack_from('<I',d,eo+16)[0]; cd_size=struct.unpack_from('<I',d,eo+12)[0]
assert cd_off+cd_size==eo
pre=bytearray(d[eo:]); struct.pack_into('<I',pre,16,cd_off)
dig=digest_sections([d[:cd_off],d[cd_off:eo],bytes(pre)])
key=serialization.load_pem_private_key(KEY.read_bytes(),password=None)
cert=x509.load_pem_x509_certificate(CERT.read_bytes())
cert_der=cert.public_bytes(serialization.Encoding.DER)
pub_der=cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
drec=struct.pack('<I',ALG)+lp(dig); signed=lp(lp(drec))+lp(lp(cert_der))+lp(b'')
sig=key.sign(signed,padding.PKCS1v15(),hashes.SHA256())
srec=struct.pack('<I',ALG)+lp(sig); signer=lp(signed)+lp(lp(srec))+lp(pub_der)
v2=lp(lp(signer)); pair=struct.pack('<Q',4+len(v2))+struct.pack('<I',V2_ID)+v2
size=len(pair)+8+16; block=struct.pack('<Q',size)+pair+struct.pack('<Q',size)+MAGIC
fe=bytearray(d[eo:]); struct.pack_into('<I',fe,16,cd_off+len(block))
OUT.write_bytes(d[:cd_off]+block+d[cd_off:eo]+bytes(fe))

print('OUT',OUT)
print('APK_SHA256',hashlib.sha256(OUT.read_bytes()).hexdigest())
print('HIDDEN_ADD_TO_LIBRARY',seen['count'])
print('SET_VISIBLE_METHOD',SET_VISIBLE)
print('CERT',cert.subject.rfc4514_string())
