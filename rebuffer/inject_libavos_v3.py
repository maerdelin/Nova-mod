#!/usr/bin/env python3
from pathlib import Path
import sys, zipfile

apk=Path(sys.argv[1]); libs=Path(sys.argv[2]); out=Path(sys.argv[3])
abis=["arm64-v8a","armeabi-v7a","x86","x86_64"]
repl={f"lib/{a}/libavos.so":(libs/a/"libavos.so").read_bytes() for a in abis}
with zipfile.ZipFile(apk,"r") as zin, zipfile.ZipFile(out,"w") as zout:
    seen=set()
    for info in zin.infolist():
        if info.filename in seen: raise SystemExit("duplicate entry "+info.filename)
        seen.add(info.filename)
        data=repl.get(info.filename,zin.read(info.filename))
        zi=zipfile.ZipInfo(info.filename,info.date_time)
        zi.compress_type=info.compress_type
        zi.comment=info.comment; zi.extra=info.extra
        zi.internal_attr=info.internal_attr; zi.external_attr=info.external_attr
        zi.create_system=info.create_system; zi.flag_bits=info.flag_bits
        zout.writestr(zi,data,compress_type=info.compress_type)
missing=set(repl)-seen
if missing: raise SystemExit("missing native entries "+str(sorted(missing)))
print("INJECT_LIBAVOS=PASS")
