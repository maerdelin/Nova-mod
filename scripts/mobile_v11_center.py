#!/usr/bin/env python3
"""Apply exact V11 mobile-side menu-centering fix over V10 unsigned APK.
Root BrowserCategory ListView is wrapped inside FrameLayout, and corresponding
onCreateView DEX method is patched to find android.R.id.list. TV remains same.
"""
import sys,zipfile,zlib,base64,hashlib,struct
from pathlib import Path
BLOB="eNqbtlllem8A0++35537b66Jiv2Zsi78z8RnLKn6OxmT1qxWcUuMsH710ERL6DxnHYtfhcireU//ZaWf+fRzZ478pp/VR/bcnsgAwkwMDAwcQCzB0O5fs9z/W93Wz4dyLfYUX77Bk7fkluBGqyWB8dYM+xkY0m2EGPMcpHmYRXgYgCwFOz4BBh5GeUZJZhEGLgYmoMhWXkYGIeE8BRMBQwZBhsEF1j3S+yKQteua4+4zDu5Prn7YdeLAIbfM2lUPLJ9LKqxZqMDppGApF32lbvN/i3WZn6TUtH5P97ow7UdElLdY88TPWv5TgOFkw8zAwAg1z4aZGRhsEBEZBhegMD/MKiA7AslmkLg8EOsBsRMQBwNxLBDnAnEVEHcC8TQgXgjEq4H4BhA/A2IenpzEyvzSkvjyzJSSDAZeXig3IzUzPaMEJJ1ZXBKcmpOaXJJfxCAomFKUWA7j+ueF5Bcw8PFBtaQXJZZlllQysLOnZJZlpqQWAU2DsjwgpnFxJWfkZyan+uanpAKNLkhMScnMSw8uSSwCyUG5rnkpDBwcPkBrwzJTy4GmJealFOVnpjBoaWWUlBRY6esXJ2ek5iYW60El9JLzc/UTC7L1i1KL9WGKubndihJzU33ATmNgYgIKMTQwcjC4AP38hYGR8SsQ/wbiP0C8GYg1GRkZtYBYG4g3MzMybgFi9Ni9AFTHwCgATMQM4JT3Hwi4QWEIxExAcR8kcRDgBbJFgJAJqp8HSoPkgJlBAETzQKISRQxkFkgQ2SwuqFlcDNxEm/UPKsaEEGNcwchRDxJjRogJwcxjQdIrABVjRdILU8eGEGNlhIqxI+mFiXFgUceJRYwPyQ5QHmdGC2OY/7GJg8KYEUecAAAlVyrH"
NAMES=['classes.dex','res/Tl.xml']
def sha(b):return hashlib.sha256(b).digest()
def build(base,out):
 src=zlib.decompress(base64.b64decode(BLOB))
 off=0; changes={}
 with zipfile.ZipFile(base) as old:
  for name in NAMES:
   a=old.read(name)
   expected=src[off:off+32];target=src[off+32:off+64];off+=64
   al,bl,count=struct.unpack_from('<III',src,off);off+=12
   if len(a)!=al or sha(a)!=expected:raise ValueError('Wrong V10 base '+name)
   b=bytearray(a if al==bl else bytes(bl))
   for i in range(count):
    start,size=struct.unpack_from('<IH',src,off);off+=6
    b[start:start+size]=src[off:off+size];off+=size
   if sha(b)!=target:raise ValueError('Incorrect V11 member '+name)
   changes[name]=bytes(b)
  if off!=len(src):raise ValueError('Extra bytes')
  with zipfile.ZipFile(out,'w') as dest:
   for entry in old.infolist():
    name=entry.filename
    z=zipfile.ZipInfo(name,entry.date_time);z.compress_type=entry.compress_type;z.external_attr=entry.external_attr;z.create_system=entry.create_system
    dest.writestr(z,changes.get(name,old.read(name)),compress_type=z.compress_type,compresslevel=6)
  with zipfile.ZipFile(out) as dest:assert dest.testzip() is None
 print('PASS V11 menu FrameLayout wrapper & mobile-only DEX')
if __name__=='__main__':
 if len(sys.argv)!=3:sys.exit('Usage: mobile_v11_center.py input-v10.apk output-v11.apk')
 build(sys.argv[1],sys.argv[2])
