#!/usr/bin/env python3
"""Apply exact V11 mobile-side menu-centering fix over V10 unsigned APK.
Root BrowserCategory ListView is wrapped inside FrameLayout, and corresponding
onCreateView DEX method is patched to find android.R.id.list. TV remains same.
"""
import sys,zipfile,zlib,base64,hashlib,struct
from pathlib import Path
BLOB="eNqbtlllem8A0++35537b66Jiv2Zsi78z8RnLKn6OxmT1qxWOTtTwbRhwdfv/7zDNHI6LbsuSzdUCwe8/n+4e91f1t7X5ntuT2QAYSYGBgYOIJZgsPRTeNRzrur2EWeOvhUzvjXHuNTuvhOXZB8Yb82wn4Eh3UaIMc9BmodZhIdBhJGLgYkxT+EhjwADD6M8oySzkHCegomAIYMgw+AE6x7pfRHI2nXNcfcZB/cnVz/sOnHgkFtm7aoHls8lFdYsVOB0UrCUi75St/m/xbrMT1JqWr+ne12Y9iMiyluseeJnLf8pwHCyYWZgYISaZ8PMDAw2iIgMgwtQmB9mFZAdgWQzSFweiPWA2AmIg4E4FohzgbgKiDuBeBoQLwTi1UB8A4ifATEPT05iZX5pSXx5ZkpJBgMvL5SbkZqZnlECks4sLglOzUlNLskvYhAUTClKLIdx/fNC8gsY+PigWtKLEssySyoZ2NlTMssyU1KLgKZBWR4Q07i4kjPyM5NTffNTUoFGFySmpGTmpQeXJBaB5KBc17wUBg4OH6C1YZmp5UDTEvNSivIzUxi0tDJKSgqs9PWLkzNScxOL9aASesn5ufqJBdn6RanF+jDF3NxuRYm5qT5gpzEwMQGFGBoYORhcgH7+wsDI+BWIfwPxHyDeDMSajIyMWkCsDcSbmRkZtwAxeuxeAKpjYBQAJmIGcAr8DwTcoDAEYiaguA+SOAjwAtkiQMgE1c8DpUFywMwgAKJ5IFGJIgYyCySIbBYX1CwuBm6izfoHFWNCiDGuYOSoB4kxI8SEYOaxIOkVgIqxIumFqWNDiLEyQsXYkfTCxDiwqOPEIsaHZAcoxzOjhTHM/9jEQWHMiCNOAIfrKWg="
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
