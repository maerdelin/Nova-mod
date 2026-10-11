import struct,sys,os

def uleb(b,o):
    r=0;s=0
    while True:
        x=b[o];o+=1;r|=(x&0x7f)<<s
        if x<0x80:return r,o
        s+=7

def read_str(b,o):
    _,o=uleb(b,o)
    e=b.index(0,o)
    return b[o:e].decode('utf-8','replace')

class Dex:
    def __init__(self,path):
        self.path=path; self.b=open(path,'rb').read()
        b=self.b
        vals=struct.unpack_from('<20I',b,0x20)
        (self.file_size,self.header_size,self.endian,self.link_size,self.link_off,self.map_off,
         self.string_ids_size,self.string_ids_off,self.type_ids_size,self.type_ids_off,
         self.proto_ids_size,self.proto_ids_off,self.field_ids_size,self.field_ids_off,
         self.method_ids_size,self.method_ids_off,self.class_defs_size,self.class_defs_off,
         self.data_size,self.data_off)=vals
        self.strings=[]
        for i in range(self.string_ids_size):
            off=struct.unpack_from('<I',b,self.string_ids_off+4*i)[0]
            self.strings.append(read_str(b,off))
        self.types=[self.strings[struct.unpack_from('<I',b,self.type_ids_off+4*i)[0]] for i in range(self.type_ids_size)]
        self.methods=[]
        for i in range(self.method_ids_size):
            c,p,n=struct.unpack_from('<HHI',b,self.method_ids_off+8*i)
            self.methods.append((c,p,n))
        self.protos=[]
        for i in range(self.proto_ids_size):
            shorty,ret,poff=struct.unpack_from('<III',b,self.proto_ids_off+12*i)
            ps=[]
            if poff:
                sz=struct.unpack_from('<I',b,poff)[0]
                ps=[self.types[struct.unpack_from('<H',b,poff+4+2*j)[0]] for j in range(sz)]
            self.protos.append((self.types[ret],ps))
        self.method_code={}
        self.method_meta={}
        for ci in range(self.class_defs_size):
            (class_idx,acc,super_idx,interfaces_off,source_idx,ann_off,class_data_off,static_values_off)=struct.unpack_from('<8I',b,self.class_defs_off+32*ci)
            if not class_data_off: continue
            o=class_data_off
            sf,o=uleb(b,o); inf,o=uleb(b,o); dm,o=uleb(b,o); vm,o=uleb(b,o)
            idx=0
            for _ in range(sf):
                d,o=uleb(b,o); idx+=d; _,o=uleb(b,o)
            idx=0
            for _ in range(inf):
                d,o=uleb(b,o); idx+=d; _,o=uleb(b,o)
            for n in (dm,vm):
                idx=0
                for _ in range(n):
                    d,o=uleb(b,o); idx+=d; access,o=uleb(b,o); code_off,o=uleb(b,o)
                    if code_off:
                        regs,ins,outs,tries,debug,isz=struct.unpack_from('<HHHHII',b,code_off)
                        insn=b[code_off+16:code_off+16+isz*2]
                        self.method_code[idx]=(code_off,insn)
                        self.method_meta[idx]=(regs,ins,outs,tries,isz)
    def mname(self,idx):
        c,p,n=self.methods[idx]
        ret,ps=self.protos[p]
        return f"{self.types[c]}->{self.strings[n]}({''.join(ps)}){ret}"

def compare(a,b):
    da,db=Dex(a),Dex(b)
    assert len(da.methods)==len(db.methods)
    changed=[]
    for i in range(len(da.methods)):
        ca=da.method_code.get(i); cb=db.method_code.get(i)
        if (ca is None)!=(cb is None): changed.append((i,'code-presence')); continue
        if ca and ca[1]!=cb[1]: changed.append((i,'insns'))
        elif ca and da.method_meta[i]!=db.method_meta[i]: changed.append((i,'meta'))
    print(os.path.basename(a),'->',os.path.basename(b),'changed methods',len(changed))
    for i,k in changed:
        print(i,k,da.mname(i),'A',da.method_meta.get(i),'B',db.method_meta.get(i),'off',da.method_code.get(i,(None,))[0],db.method_code.get(i,(None,))[0])
        if k=='insns':
            xa=da.method_code[i][1]; xb=db.method_code[i][1]
            wa=list(struct.unpack('<%dH'%(len(xa)//2),xa)); wb=list(struct.unpack('<%dH'%(len(xb)//2),xb))
            dif=[j for j,(x,y) in enumerate(zip(wa,wb)) if x!=y]
            if dif:
                runs=[]; s=p=dif[0]
                for j in dif[1:]:
                    if j==p+1:p=j
                    else:runs.append((s,p));s=p=j
                runs.append((s,p))
                for s,e in runs:
                    lo=max(0,s-3); hi=min(len(wa),e+4)
                    print('  words',s,e,'ctx',lo,hi)
                    print('   A',' '.join(f'{x:04x}' for x in wa[lo:hi]))
                    print('   B',' '.join(f'{x:04x}' for x in wb[lo:hi]))

if __name__=='__main__': compare(sys.argv[1],sys.argv[2])
