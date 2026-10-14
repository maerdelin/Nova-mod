#!/usr/bin/env python3
"""V7.14 network-only exact centering, measured from native layout resources.

Validated resource values in pinned resources.arsc:
  smbshortcut_width = 210dp
  lb_browse_item_horizontal_spacing = 16dp
  lb_browse_padding_start = 56dp

For N = saved network shortcuts + add network tile, the *native* row width is:
  Wdp = 210*N + 16*(N-1) + 2*56 = 226*N + 96

V4's 226*N+130 over-counted the trailing/padding budget by 34dp; V5's
attempt to query child views during the async loader callback returned null
before RecyclerView layout and skipped centering altogether.

V6 keeps V4's working early loader callback, activity-only FrameLayout gravity,
runtime resource density correction and overflow clamp. It changes only the
width formula's immediate 130->96. No screenshot pixel tuning.
"""
import base64
import hashlib
import struct
import sys
import zipfile
import zlib

BASELINE_DEX_SHA = "be158200a3070bf13f31f7bbc4c7a1ed667e42a8b221a6e027ebd0122f5ce636"
OUTPUT_DEX_SHA = "1f0194f96282bc3494e0ed17505a52d2cd552782cee5d534584480058b836e38"
NATIVE_CARD_DP = 210
NATIVE_SPACING_DP = 16
NATIVE_START_PADDING_DP = 56
assert 2*NATIVE_START_PADDING_DP-NATIVE_SPACING_DP == 96

PROTECTED_LAYOUT_SHA = {
    "res/Am.xml":"b246497606d126efa7e56156952bfd059538b9ffb18afb7a1c4cc44380293262",
    "res/mC.xml":"559a5e7d1b679338e5fb9be9eface0ee1edc7ef4ca454651b851ed9084b6a1bc",
}
METHODS = {
  # NetworkRootActivity.onKeyDown(int,KeyEvent)
  # Real remote keys follow the original superclass. The internal (-1,null)
  # shortcut refresh is consumed; it never dereferences a null KeyEvent.
  20881: (
      4263380, (9,3,3,0,6497187,83),
      "aa46e935df910f13da76ec38a824bb994e42b99a645855674c3a4e468fa09e81",
      "EvAzB00AbhCZGAYADABgAXo4biDYFhAADAAfAMgLcRDLUQAADAFuEHzpAQAKARMC4gCyIRMCYACwIW4Q6xcAAAwCYAOrM24guAQyAAoCsiETAtIAsyFuEPoXAAAMADgAHgBuED8NAAAKAjchAwABIRQDkQMKf24g4QwwAAwAbhAIDQAADAJZIXMCHwIOAxITWSOwAm4guw0gAA8DbzDKS3YICgAPAA==",
  ),
  # NetworkRootFragment.NetworkShortcutsLoaderTask.lambda$execute$0 callback:
  # preserve saved shortcuts and the add-network tile from original V4.
  20906: (
      4266828, (6,2,3,1,6499017,134),
      "1a0e62e64768f75f320910c74ae25683cf0461936ff7fcbb161043f54db51157",
      "VUCDYjkAbABUQIRibhDMFwAADAA4AGQAVECEYm4QAxgAAAoAOABcADgFWgByEAMFBQAKADkAVABUQIRicRDLUQAADABuEHfpAAByEPsEBQAKAD0AIAByEAUFBQAiAPEKcBC7TAAAbiC9TFAAVEGEYnEQy1EBAAwBbiC8TFAADABuIHXpAQByEAYFBQAKADkA5/9UQIRicRDLUQAADAAiAfwKVEKEYmADVj5uIPMXMgAMAnAg90whAG4gdekQAFRAhGJuEMwXAAAMABLxEgJuMCoCEAIoBAAADQQoDTgFCwByEAMFBQAKBDkEBQByEPQEBQAOADgFCwByEAMFBQAKADkABQByEPQEBQAnBA==",
  ),
}
def digest(data):
    return hashlib.sha256(data).hexdigest()
def patch_dex(source):
    if digest(source) != BASELINE_DEX_SHA:
        raise ValueError("Unexpected AutoMode DEX; refusing patch")
    result=bytearray(source)
    expected_original_headers={
      20881:(9,3,3,0,6497187,83),
      20906:(6,2,2,1,6499017,134)
    }
    for mid,(off,header,code_sha,b64) in METHODS.items():
        assert struct.unpack_from("<4H2I",result,off)==expected_original_headers[mid]
        code=base64.b64decode(b64,validate=True)
        assert len(code)==header[5]*2
        assert digest(code)==code_sha
        struct.pack_into("<4H2I",result,off,*header)
        result[off+16:off+16+len(code)]=code
    # Validate the exact formula constant, native center gravity and NPE fix.
    o=4263380+16
    assert struct.unpack_from("<H",result,o+24*2)[0]==226
    assert struct.unpack_from("<H",result,o+27*2)[0]==96
    assert struct.unpack_from("<H",result,o+72*2)[0]==0x2359  # iput gravity
    assert struct.unpack_from("<H",result,o+77*2)[0]==0x030f  # return, not super
    result[12:32]=hashlib.sha1(result[32:]).digest()
    struct.pack_into("<I",result,8,zlib.adler32(result[12:])&0xffffffff)
    assert len(result)==len(source)
    assert digest(result)==OUTPUT_DEX_SHA
    return bytes(result)

def build(baseline,output):
    with zipfile.ZipFile(baseline) as old:
        assert old.testzip() is None
        for name,expected in PROTECTED_LAYOUT_SHA.items():
            assert digest(old.read(name))==expected,name
        with zipfile.ZipFile(output,"w",allowZip64=False) as new:
            for e in old.infolist():
                name=e.filename
                upper=name.upper()
                if upper=="META-INF/MANIFEST.MF" or (
                    upper.startswith("META-INF/") and upper.endswith((".SF",".RSA",".DSA",".EC"))):
                    continue
                b=patch_dex(old.read(name)) if name=="classes.dex" else old.read(name)
                info=zipfile.ZipInfo(name,e.date_time)
                info.compress_type=e.compress_type
                info.external_attr=e.external_attr
                info.create_system=e.create_system
                new.writestr(info,b,compress_type=info.compress_type,compresslevel=6)
        with zipfile.ZipFile(output) as new:
            assert new.testzip() is None
            changed=[n for n in new.namelist() if old.read(n)!=new.read(n)]
            assert changed==["classes.dex"],changed
            for name in PROTECTED_LAYOUT_SHA:
                assert new.read(name)==old.read(name)
    print("PASS: V6 native geometry; only network DEX changed; home and common XML identical")
    print("PASS: dex SHA256",OUTPUT_DEX_SHA)

if __name__=="__main__":
    if len(sys.argv)!=3: sys.exit("Usage: network_center_v6.py proven-baseline.apk unsigned-v6.apk")
    build(sys.argv[1],sys.argv[2])
