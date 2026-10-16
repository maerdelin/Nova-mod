#!/usr/bin/env python3
from pathlib import Path
import sys, zipfile, tempfile, os, shutil

apk = Path(sys.argv[1])
libs = Path(sys.argv[2])
out = Path(sys.argv[3])
abis = ["arm64-v8a","armeabi-v7a","x86","x86_64"]
repl = {f"lib/{abi}/libavos.so": (libs/abi/"libavos.so").read_bytes() for abi in abis}

with zipfile.ZipFile(apk, "r") as zin, zipfile.ZipFile(out, "w") as zout:
    seen=set()
    for info in zin.infolist():
        if info.filename in seen:
            raise SystemExit("duplicate entry: "+info.filename)
        seen.add(info.filename)
        data = repl.get(info.filename, zin.read(info.filename))
        zinfo = zipfile.ZipInfo(info.filename, info.date_time)
        zinfo.compress_type = info.compress_type
        zinfo.comment = info.comment
        zinfo.extra = info.extra
        zinfo.internal_attr = info.internal_attr
        zinfo.external_attr = info.external_attr
        zinfo.create_system = info.create_system
        zinfo.flag_bits = info.flag_bits
        zout.writestr(zinfo, data, compress_type=info.compress_type)

missing = set(repl) - seen
if missing:
    raise SystemExit("missing native entries: "+str(sorted(missing)))
print("Injected rebuilt Kodi-buffer V2 libavos.so into", out)
