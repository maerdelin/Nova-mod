import zipfile, struct, hashlib, zlib, sys, shutil
from pathlib import Path
sys.path.insert(0,'/mnt/data')
from dex_inspect import Dex
from cryptography import x509
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

SRC=Path('/mnt/data/NOVA-6.5.5-Network-UI-R11-armeabi-v7a.apk')
UNSIGNED=Path('/mnt/data/NOVA-6.5.5-Network-UI-R16-armeabi-v7a-unsigned.apk')
OUT=Path('/mnt/data/NOVA-6.5.5-Network-UI-R16-armeabi-v7a.apk')
DEX=Path('/mnt/data/r16_classes.dex')
ARSC=Path('/mnt/data/r16_resources.arsc')
KEY=Path('/mnt/data/nova_r2_key.pem')
CERT=Path('/mnt/data/nova_r2_cert.pem')
LEFT_BG=0xff06233b

with zipfile.ZipFile(SRC,'r') as z:
    infos={zi.filename:zi for zi in z.infolist() if not zi.is_dir()}
    entries={zi.filename:z.read(zi.filename) for zi in z.infolist() if not zi.is_dir()}
    DEX.write_bytes(entries['classes.dex'])
    ARSC.write_bytes(entries['resources.arsc'])

# ---------- DEX: only in-place, fixed-size instruction substitutions ----------
dx=Dex(str(DEX)); raw=bytearray(DEX.read_bytes())

def method(desc,name,insns_size=None):
    ms=[m for m in dx.class_methods(desc) if m['name']==name and (insns_size is None or m['insns_size']==insns_size)]
    if len(ms)!=1: raise RuntimeError((desc,name,insns_size,len(ms)))
    return ms[0]

def words(m): return list(struct.unpack_from('<%dH'%m['insns_size'],raw,m['code_off']+16))
def put_words(m,ws):
    assert len(ws)==m['insns_size']
    struct.pack_into('<%dH'%len(ws),raw,m['code_off']+16,*ws)

# field and method lookup helpers
fields=[]
for i in range(dx.field_ids_size):
    c,t,n=struct.unpack_from('<HHI',raw,dx.field_ids_off+8*i); fields.append((c,t,n))
def field_idx(owner,name):
    oi=dx.types.index(owner); hits=[i for i,(c,t,n) in enumerate(fields) if c==oi and dx.strings[n]==name]
    if len(hits)!=1: raise RuntimeError(('field',owner,name,hits))
    return hits[0]
def method_indices(owner,name):
    oi=dx.types.index(owner); return [i for i,(c,p,n) in enumerate(dx.methods) if c==oi and dx.strings[n]==name]
def unique_method_idx(owner,name):
    hits=method_indices(owner,name)
    if len(hits)!=1: raise RuntimeError(('method',owner,name,hits))
    return hits[0]
def method_proto(mid):
    c,p,n=struct.unpack_from('<HHI',raw,dx.method_ids_off+8*mid)
    shorty,ret,poff=struct.unpack_from('<III',raw,dx.proto_ids_off+12*p)
    params=[]
    if poff:
        sz=struct.unpack_from('<I',raw,poff)[0]
        params=[dx.types[struct.unpack_from('<H',raw,poff+4+2*i)[0]] for i in range(sz)]
    return dx.types[c], dx.strings[n], dx.types[ret], params

def find_invoke(ws,mid):
    out=[]
    for i in range(len(ws)-1):
        op=ws[i]&0xff
        if 0x6e<=op<=0x78 and ws[i+1]==mid: out.append(i)
    return out

# 1) Keep the entire known-good WebDAV/SMB fragment path from R11.
#    Only change RecyclerView bottom padding from the computed top padding to zero.
NR='Lcom/archos/mediacenter/video/browser/filebrowsing/network/NewRootFragment;'
m=method(NR,'onCreateView',89); ws=words(m)
set_padding=unique_method_idx('Landroid/view/View;','setPadding')
hits=find_invoke(ws,set_padding)
if len(hits)!=1: raise RuntimeError(('setPadding hits',hits))
pc=hits[0]
# R11 exact call = invoke-virtual {v0,v4,v1,v4,v1}, setPadding ; v4 is already 0.
if ws[pc] != 0x516e or ws[pc+2] != 0x4140:
    raise RuntimeError(('unexpected R11 setPadding',pc,[hex(x) for x in ws[pc:pc+3]]))
ws[pc]=0x546e  # {v0,v4,v1,v4,v4}: left=0, top=centerOffset, right=0, bottom=0
put_words(m,ws)

# 2) Button background: keep R11 bind logic, replace only setBackgroundColor(color)
#    with setBackgroundResource(R.drawable.big_button_normal) in the same instruction footprint.
RDRAW='Lcom/archos/mediacenter/video/R$drawable;'
big_drawable=field_idx(RDRAW,'big_button_normal')
set_bg_color=unique_method_idx('Landroid/view/View;','setBackgroundColor')
set_bg_res=unique_method_idx('Landroid/view/View;','setBackgroundResource')
for desc in [
    'Lcom/archos/mediacenter/video/browser/filebrowsing/network/ShortcutAdapter;',
    'Lcom/archos/mediacenter/video/browser/filebrowsing/network/FtpBrowser/FtpShortcutAdapter;'
]:
    m=method(desc,'onBindViewHolder',64); ws=words(m)
    hits=find_invoke(ws,set_bg_color)
    if len(hits)!=1: raise RuntimeError((desc,'setBackgroundColor hits',hits))
    pc=hits[0]
    # immediately before invoke should be const v1, LEFT_BG (3 words)
    if pc<3 or (ws[pc-3]&0xff)!=0x14:
        raise RuntimeError((desc,'missing const color',pc,[hex(x) for x in ws[pc-3:pc+3]]))
    # Replace 3-word const with 2-word sget + nop, then invoke setBackgroundResource.
    ws[pc-3]=0x0160                 # sget v1, field@BBBB
    ws[pc-2]=big_drawable
    ws[pc-1]=0x0000                 # nop; preserves all branch PCs and method size
    ws[pc+1]=set_bg_res
    put_words(m,ws)

# 3) Direct playback from indexed/recent video lists without touching the directory/type gate.
#    Keep BrowserByVideoObjects.onItemClick byte-for-byte identical to R11.
#    That stock method performs the instanceof Video guard, so folders continue into
#    BrowserByFolder.enterDirectory(). We only replace displayInfo(position), which is
#    reached after the item has already been confirmed to be a Video.
BVO='Lcom/archos/mediacenter/video/browser/BrowserByVideoObjects;'
VIDEO='Lcom/archos/mediacenter/video/browser/adapters/object/Video;'
ADAPTER='Lcom/archos/mediacenter/video/browser/adapters/AdapterByVideoObjectsInterface;'

# Resolve refs from this exact R11 DEX.
F_ADAPTER_VIDEO=field_idx(BVO,'mAdapterByVideoObjects')
GET_VIDEO_ITEM=unique_method_idx(ADAPTER,'getVideoItem')
start_mid=None
for mid in method_indices(BVO,'startVideo'):
    owner,name,ret,params=method_proto(mid)
    if params==[VIDEO,'I']:
        start_mid=mid
if start_mid is None:
    raise RuntimeError('startVideo(Video,int) not found')

# Rewrite only displayInfo(int):
# Video v = mAdapterByVideoObjects.getVideoItem(position);
# if (v != null) startVideo(v, position);
m=method(BVO,'displayInfo',69)
# Keep the original register map (regs=13, ins=2 => p0=v11, p1=v12).
new_words=[
    0xb054, F_ADAPTER_VIDEO,       # iget-object v0, v11, mAdapterByVideoObjects
    0x2072, GET_VIDEO_ITEM, 0x00c0,# invoke-interface {v0,v12}, getVideoItem(I)
    0x000c,                        # move-result-object v0
    0x0038, 0x0005,                # if-eqz v0, return
    0x306e, start_mid, 0x0c0b,     # invoke-virtual {v11,v0,v12}, startVideo(Video,int)
    0x000e,                        # return-void
]
if len(new_words)>m['insns_size']:
    raise RuntimeError('displayInfo replacement too large')
put_words(m,new_words+[0x0000]*(m['insns_size']-len(new_words)))

# DEX checksums
raw[12:32]=hashlib.sha1(raw[32:]).digest()
struct.pack_into('<I',raw,8,zlib.adler32(raw[12:]) & 0xffffffff)
DEX.write_bytes(raw)
entries['classes.dex']=DEX.read_bytes()

# ---------- Binary XML helpers ----------
def parse_string_pool(buf, off):
    typ,hdr,size=struct.unpack_from('<HHI',buf,off)
    if typ!=0x0001: raise ValueError(('not string pool',hex(typ),off))
    sc,stylec,flags,ss,stylesStart=struct.unpack_from('<IIIII',buf,off+8)
    utf8=bool(flags & 0x100); offs=[struct.unpack_from('<I',buf,off+hdr+4*i)[0] for i in range(sc)]; base=off+ss
    strings=[]
    def d8(p):
        b=buf[p];p+=1
        if b&0x80:return ((b&0x7f)<<8)|buf[p],p+1
        return b,p
    def d16(p):
        x=struct.unpack_from('<H',buf,p)[0];p+=2
        if x&0x8000:return ((x&0x7fff)<<16)|struct.unpack_from('<H',buf,p)[0],p+2
        return x,p
    for o in offs:
        p=base+o
        if utf8:
            _,p=d8(p); bl,p=d8(p); strings.append(bytes(buf[p:p+bl]).decode('utf-8','replace'))
        else:
            ln,p=d16(p); strings.append(bytes(buf[p:p+ln*2]).decode('utf-16le','replace'))
    return strings,size

def patch_axml(data, cb):
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
            attrStart,attrSize,attrCount,idIndex,classIndex,styleIndex=struct.unpack_from('<HHHHHH',buf,off+24)
            tag=strings[name]; attrs=[]; aoff=off+16+attrStart
            for i in range(attrCount):
                base=aoff+i*attrSize; ans,aname,araw=struct.unpack_from('<III',buf,base); vsize,res0,dtype,adata=struct.unpack_from('<HBBI',buf,base+12)
                attrs.append({'name':strings[aname],'dtype':dtype,'data':adata,'base':base})
            cb(buf,tag,attrs,stack); stack.append(tag)
        elif ct==0x0103:
            if stack: stack.pop()
        off+=cs
    return bytes(buf)

# 4) Rounded deep button drawable: exact same deep color as left panel, 8dp radius.
def patch_drawable(xml):
    def cb(buf,tag,attrs,stack):
        if tag=='solid':
            for a in attrs:
                if a['name']=='color': struct.pack_into('<I',buf,a['base']+16,LEFT_BG)
        elif tag=='stroke':
            for a in attrs:
                if a['name']=='color': struct.pack_into('<I',buf,a['base']+16,LEFT_BG)
        elif tag=='corners':
            for a in attrs:
                if a['name']=='radius':
                    buf[a['base']+15]=0x05       # TYPE_DIMENSION
                    struct.pack_into('<I',buf,a['base']+16,0x0801)  # 8dp
    return patch_axml(xml,cb)

# 5) Add button width +50%: current ~120dp -> fixed 180dp, while keeping its row otherwise untouched.
def patch_button_layout(xml):
    seen={'button':0}
    def cb(buf,tag,attrs,stack):
        if tag=='Button':
            seen['button']+=1
            for a in attrs:
                if a['name']=='layout_width':
                    buf[a['base']+15]=0x05       # TYPE_DIMENSION
                    struct.pack_into('<I',buf,a['base']+16,0xB401)  # 180dp
    out=patch_axml(xml,cb)
    if seen['button']!=1: raise RuntimeError(('unexpected button count',seen))
    return out

entries['res/8i.xml']=patch_drawable(entries['res/8i.xml'])
entries['res/g6.xml']=patch_button_layout(entries['res/g6.xml'])

# ---------- Repack preserving metadata/compression and resources.arsc alignment ----------
with open(UNSIGNED,'wb') as fout:
    with zipfile.ZipFile(fout,'w',allowZip64=True) as zout:
        for name,zi in infos.items():
            if name.startswith('META-INF/'): continue
            content=entries[name]
            nzi=zipfile.ZipInfo(name,zi.date_time); nzi.compress_type=zi.compress_type; nzi.comment=zi.comment; nzi.internal_attr=zi.internal_attr; nzi.external_attr=zi.external_attr; nzi.create_system=zi.create_system; nzi.flag_bits=zi.flag_bits & ~0x08; nzi.extra=b''
            if name=='resources.arsc':
                nzi.compress_type=zipfile.ZIP_STORED
                cur=fout.tell(); baseoff=cur+30+len(name.encode('utf-8')); pad=next(n for n in range(4) if (baseoff+4+n)%4==0); nzi.extra=struct.pack('<HH',0xFFFF,pad)+b'\0'*pad
            zout.writestr(nzi,content,compress_type=nzi.compress_type,compresslevel=6)

# ---------- APK Signature Scheme v2 with the same key used for prior versions ----------
ALG=0x0103; V2_ID=0x7109871a; MAGIC=b'APK Sig Block 42'; CHUNK=1024*1024
def lp(x): return struct.pack('<I',len(x))+x
def digest_sections(sections):
    chunks=[]
    for sec in sections:
        for i in range(0,len(sec),CHUNK):
            c=sec[i:i+CHUNK]; chunks.append(hashlib.sha256(b'\xa5'+struct.pack('<I',len(c))+c).digest())
    return hashlib.sha256(b'\x5a'+struct.pack('<I',len(chunks))+b''.join(chunks)).digest()

d=UNSIGNED.read_bytes(); eo=d.rfind(b'PK\x05\x06',max(0,len(d)-65557))
if eo<0: raise RuntimeError('EOCD')
cd_off=struct.unpack_from('<I',d,eo+16)[0]; cd_size=struct.unpack_from('<I',d,eo+12)[0]; assert cd_off+cd_size==eo
pre=bytearray(d[eo:]); struct.pack_into('<I',pre,16,cd_off); dig=digest_sections([d[:cd_off],d[cd_off:eo],bytes(pre)])
key=serialization.load_pem_private_key(KEY.read_bytes(),password=None); cert=x509.load_pem_x509_certificate(CERT.read_bytes())
cert_der=cert.public_bytes(serialization.Encoding.DER); pub_der=cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
drec=struct.pack('<I',ALG)+lp(dig); signed=lp(lp(drec))+lp(lp(cert_der))+lp(b''); sig=key.sign(signed,padding.PKCS1v15(),hashes.SHA256()); srec=struct.pack('<I',ALG)+lp(sig)
signer=lp(signed)+lp(lp(srec))+lp(pub_der); v2=lp(lp(signer)); pair=struct.pack('<Q',4+len(v2))+struct.pack('<I',V2_ID)+v2; size=len(pair)+8+16; block=struct.pack('<Q',size)+pair+struct.pack('<Q',size)+MAGIC
fe=bytearray(d[eo:]); struct.pack_into('<I',fe,16,cd_off+len(block)); OUT.write_bytes(d[:cd_off]+block+d[cd_off:eo]+bytes(fe))

print('OUT',OUT)
print('APK_SHA256',hashlib.sha256(OUT.read_bytes()).hexdigest())
print('displayInfo rewritten -> startVideo',start_mid)
print('NewRoot setPadding pc',pc)
print('big_button_normal field',big_drawable,'setBackgroundResource',set_bg_res)
