#!/usr/bin/env python3
"""Nova V7.14 dynamic TV network-row centering (V5, exact-measured version).

The *existing* NetworkShortcutsLoaderTask already publishes its refreshed
shortcuts and add-network tile. Its main-thread callback invokes
NetworkRootActivity.onKeyDown(-1, null) as a private sentinel. In the network
activity only, V5 now derives the centered width from live measured geometry:

    content_px = N * first_tile.getWidth()
                 + (N - 1) * row_grid.getHorizontalSpacing()
    centered_rows_width_px = min(screen_px,
                                  content_px + 2 * first_tile.getLeft())

The first tile's actual LEFT offset is mirrored as the right inset so the
entire card group's center matches the screen center. No screenshot-pixel
corrections, fixed 130dp paddings, or guessed 16dp gaps are used. On overflow,
the rows viewport retains full screen width and native horizontal scrolling.
Only network activity code and its dedicated loader change; original TV home
AXML, common list row XML, non-TV mode selector and all other data stay exact.

The sentinel is consumed, so a null KeyEvent is never passed to super.
Ordinary remote control events still delegate to LeanbackActivity.onKeyDown.

This script modifies two existing code_item bodies IN PLACE; never adds,
moves or resizes a DEX method. All expected hashes are pinned to the proven
AutoMode baseline, and unexpected inputs are rejected.
"""
import base64
import hashlib
import struct
import sys
import zipfile
import zlib

BASE_DEX_SHA = "be158200a3070bf13f31f7bbc4c7a1ed667e42a8b221a6e027ebd0122f5ce636"
OUTPUT_DEX_SHA = "b5ca8a5fdc18b506a3fb5ddcc1879ba579474a6307f3e07b3f578690b2e646cd"
PROTECTED_RESOURCES = {
    "res/Am.xml": "b246497606d126efa7e56156952bfd059538b9ffb18afb7a1c4cc44380293262",
    "res/mC.xml": "559a5e7d1b679338e5fb9be9eface0ee1edc7ef4ca454651b851ed9084b6a1bc",
}
METHODS = {
    20881: {
        "offset": 4263380,
        "old_header": (9,3,3,0,6497187,83),
        "new_header": (9,3,3,0,6497187,83),
        "code_sha": "2e514631436e9fba9867452e093863bb1b484d2010b52f9c412659ccac41febd",
        "code": "EvAzB00AYABNOm4gAAIGAAwAOABDAB8ArQNuEIgcAAAMATgBOwBuEJ0dAQAKARICbiA+DiAADAI4AjAAbhA/DQIACgNuEFAaAAAKBLBDshOxQ24QCQ0CAAoCsCOwIxQAkQMKf24gAAIGAAwAOAAWAG4QJA0AAAwCbhA/DQIACgI3IwMAASNuEAgNAAAMAVkTcwJuILsNEAASEA8AbzDKS3YICgAPAA==",
    },
    20906: {
        "offset": 4266828,
        "old_header": (6,2,2,1,6499017,134),
        "new_header": (6,2,3,1,6499017,134),
        "code_sha": "1a0e62e64768f75f320910c74ae25683cf0461936ff7fcbb161043f54db51157",
        "code": "VUCDYjkAbABUQIRibhDMFwAADAA4AGQAVECEYm4QAxgAAAoAOABcADgFWgByEAMFBQAKADkAVABUQIRicRDLUQAADABuEHfpAAByEPsEBQAKAD0AIAByEAUFBQAiAPEKcBC7TAAAbiC9TFAAVEGEYnEQy1EBAAwBbiC8TFAADABuIHXpAQByEAYFBQAKADkA5/9UQIRicRDLUQAADAAiAfwKVEKEYmADVj5uIPMXMgAMAnAg90whAG4gdekQAFRAhGJuEMwXAAAMABLxEgJuMCoCEAIoBAAADQQoDTgFCwByEAMFBQAKBDkEBQByEPQEBQAOADgFCwByEAMFBQAKADkABQByEPQEBQAnBA==",
    },
}
def digest(data):
    return hashlib.sha256(data).hexdigest()
def transform_dex(dex):
    assert digest(dex) == BASE_DEX_SHA, "Not the confirmed AutoMode DEX; refusing to patch"
    data = bytearray(dex)
    for mid, spec in METHODS.items():
        off = spec["offset"]
        hdr = struct.unpack_from("<4H2I", dex, off)
        assert hdr == spec["old_header"], ("unexpected code header", mid, hdr)
        code = base64.b64decode(spec["code"], validate=True)
        assert len(code) == hdr[-1] * 2, ("code_item size changed", mid)
        assert digest(code) == spec["code_sha"], ("code_item bytes changed", mid)
        struct.pack_into("<4H2I", data, off, *spec["new_header"])
        data[off+16:off+16+len(code)] = code
    data[12:32] = hashlib.sha1(data[32:]).digest()
    struct.pack_into("<I", data, 8, zlib.adler32(data[12:]) & 0xffffffff)
    assert len(data) == len(dex)
    assert digest(data) == OUTPUT_DEX_SHA, "Unexpected generated DEX; refusing package"
    return bytes(data)

def build(input_apk, output_apk):
    with zipfile.ZipFile(input_apk) as old, zipfile.ZipFile(output_apk,"w",allowZip64=False) as new:
        assert old.testzip() is None, "Baseline ZIP invalid"
        for file,expected in PROTECTED_RESOURCES.items():
            assert digest(old.read(file)) == expected, ("Protected layout mismatch", file)
        for entry in old.infolist():
            path=entry.filename
            upper=path.upper()
            if upper=="META-INF/MANIFEST.MF" or (upper.startswith("META-INF/") and upper.endswith((".SF",".RSA",".DSA",".EC"))):
                continue
            data=transform_dex(old.read(path)) if path=="classes.dex" else old.read(path)
            info=zipfile.ZipInfo(path,entry.date_time)
            info.compress_type=entry.compress_type
            info.external_attr=entry.external_attr
            info.create_system=entry.create_system
            new.writestr(info,data,compress_type=info.compress_type,compresslevel=6)
    with zipfile.ZipFile(input_apk) as old, zipfile.ZipFile(output_apk) as new:
        assert new.testzip() is None
        modified=[p for p in new.namelist() if new.read(p)!=old.read(p)]
        assert modified==["classes.dex"],("Unexpected modified files",modified)
        assert digest(new.read("classes.dex")) == OUTPUT_DEX_SHA
        for name in PROTECTED_RESOURCES:
            assert new.read(name)==old.read(name)
    print("PASS: exactly one functional file changed (classes.dex) and both home/shared layouts unchanged")
    print("PASS: in-place two-method network-only patch, signed-APK ready")

if __name__=="__main__":
    if len(sys.argv)!=3:
        sys.exit("Usage: python3 scripts/network_center_v5.py confirmed-baseline.apk unsigned-v5.apk")
    build(sys.argv[1],sys.argv[2])
