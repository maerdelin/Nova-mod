import zipfile, struct, hashlib, zlib, sys
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

sys.path.insert(0, '/mnt/data/nova_tv')
from dexdiff import Dex

BASE = Path('/mnt/data/nova_tv/NOVA-6.5.5-Network-UI-R22-DIRECT-TV-HOME-FIXED-armeabi-v7a.apk')
R19_DEX = Path('/mnt/data/nova_tv/NOVA-6.5.5-Network-UI-R19-TV-HOME-SYNC-armeabi-v7a.dex')
KEY = Path('/mnt/data/nova_tv/testkey.pk8')
CERT_DER = Path('/mnt/data/nova_tv/testkey_cert.der')
OUT = Path('/mnt/data/NOVA-6.5.5-Network-UI-R23-HOME-PANEL-TV-ROUTES-armeabi-v7a.apk')
UNSIGNED = Path('/mnt/data/nova_tv/R23-unsigned.apk')
PATCHED_DEX = Path('/mnt/data/nova_tv/R23-classes.dex')

with zipfile.ZipFile(BASE, 'r') as z:
    infos = {zi.filename: zi for zi in z.infolist() if not zi.is_dir()}
    entries = {zi.filename: z.read(zi.filename) for zi in z.infolist() if not zi.is_dir()}

PATCHED_DEX.write_bytes(entries['classes.dex'])
d = Dex(str(PATCHED_DEX))
r19 = Dex(str(R19_DEX))
raw = bytearray(PATCHED_DEX.read_bytes())

# ---------------- DEX helpers ----------------
def mids(owner, name):
    oi = d.types.index(owner)
    return [i for i, (c,p,n) in enumerate(d.methods) if c == oi and d.strings[n] == name]

def unique_mid(owner, name, proto_contains=None):
    hits = mids(owner, name)
    if proto_contains is not None:
        hits = [i for i in hits if proto_contains in d.mname(i)]
    if len(hits) != 1:
        raise RuntimeError(('method', owner, name, proto_contains, hits))
    return hits[0]

def get_words(mid, dex=d, buf=None):
    co, insn = dex.method_code[mid]
    if buf is None:
        b = insn
    else:
        isz = dex.method_meta[mid][4]
        b = bytes(buf[co+16:co+16+isz*2])
    return list(struct.unpack('<%dH' % (len(b)//2), b))

def put_words(mid, words):
    co, _ = d.method_code[mid]
    isz = d.method_meta[mid][4]
    if len(words) != isz:
        raise RuntimeError(('word length', d.mname(mid), len(words), isz))
    struct.pack_into('<%dH' % isz, raw, co+16, *words)

def type_idx(desc): return d.types.index(desc)
def str_idx(s): return d.strings.index(s)

# ---------------- 1) Home = previous two-pane home ----------------
# R22's only EntryActivity delta from R19 is the selected home Activity type.
# Copy the known-good R19 EntryActivity onCreate instruction stream exactly.
ENTRY = unique_mid('Lcom/archos/mediacenter/video/EntryActivity;', 'onCreate')
if d.method_meta[ENTRY] != r19.method_meta[ENTRY]:
    raise RuntimeError('EntryActivity metadata differs from R19')
r19_entry = get_words(ENTRY, r19)
r22_entry = get_words(ENTRY)
diffs = [i for i,(a,b) in enumerate(zip(r19_entry, r22_entry)) if a != b]
if diffs != [39]:
    raise RuntimeError(('unexpected EntryActivity diff', diffs))
# R19 type 0x094e = browser/MainActivity, R22 0x0ad6 = MainActivityLeanback
if r19_entry[39] != type_idx('Lcom/archos/mediacenter/video/browser/MainActivity;'):
    raise RuntimeError(('unexpected R19 home type', hex(r19_entry[39])))
put_words(ENTRY, r19_entry)

# BrowserCategory.onListItemClick in R22 is already identical to R19, which is
# important: focus/click keeps the previous real right-side Fragment content.
BC_CLICK = unique_mid('Lcom/archos/mediacenter/video/browser/BrowserCategory;', 'onListItemClick')
if get_words(BC_CLICK) != get_words(BC_CLICK, r19):
    raise RuntimeError('R22 BrowserCategory.onListItemClick is not R19 baseline')

# Common refs for TV routes
MID_META_URI = unique_mid('Lcom/archos/filecorelibrary/MetaFile2;', 'getUri')
MID_META_NAME = unique_mid('Lcom/archos/filecorelibrary/MetaFile2;', 'getName')
MID_FILEUTIL_NAME = unique_mid('Lcom/archos/filecorelibrary/FileUtils;', 'getName', '(Landroid/net/Uri;)')
MID_GET_TV_ACTIVITY = unique_mid('Lcom/archos/mediacenter/video/leanback/filebrowsing/ListingActivity;', 'getActivityForUri')
MID_FRAGMENT_GET_ACTIVITY = unique_mid('Landroidx/fragment/app/q;', 'getActivity')
MID_INTENT_CTOR = unique_mid('Landroid/content/Intent;', '<init>', '(Landroid/content/Context;Ljava/lang/Class;)')
MID_INTENT_PARCEL = unique_mid('Landroid/content/Intent;', 'putExtra', '(Ljava/lang/String;Landroid/os/Parcelable;)')
MID_INTENT_STRING = unique_mid('Landroid/content/Intent;', 'putExtra', '(Ljava/lang/String;Ljava/lang/String;)')
MID_ACTIVITY_START = unique_mid('Landroid/app/Activity;', 'startActivity', '(Landroid/content/Intent;)V')
T_INTENT = type_idx('Landroid/content/Intent;')
T_TV_SETTINGS = type_idx('Lcom/archos/mediacenter/video/leanback/settings/VideoSettingsActivity;')
S_ROOT_URI = str_idx('ROOT_URI')
S_ROOT_NAME = str_idx('ROOT_NAME')
S_START_URI = str_idx('STARTING_URI')
S_START_NAME = str_idx('STARTING_NAME')

# ---------------- 2) Local folder click -> TV ListingActivity ----------------
BROWSER_FOLDER = unique_mid('Lcom/archos/mediacenter/video/browser/filebrowsing/BrowserByFolder;', 'enterDirectory')
meta = d.method_meta[BROWSER_FOLDER]
if meta != (5,2,3,1,76):
    raise RuntimeError(('unexpected enterDirectory meta', meta))
old = get_words(BROWSER_FOLDER)
# Preserve original catch handler at pc 0x43: move-exception, log, return.
if old[0x43] != 0x030d or old[-1] != 0x000e:
    raise RuntimeError(('unexpected enterDirectory catch tail', [hex(x) for x in old[0x43:]]))
main = [
    0x106e, MID_META_URI, 0x0004,          # invoke-virtual {v4}, MetaFile2.getUri
    0x000c,                                # move-result-object v0 (Uri)
    0x106e, MID_META_NAME, 0x0004,         # invoke-virtual {v4}, MetaFile2.getName
    0x010c,                                # move-result-object v1 (String)
    0x1071, MID_GET_TV_ACTIVITY, 0x0000,   # invoke-static {v0}, ListingActivity.getActivityForUri
    0x020c,                                # move-result-object v2 (Class)
    0x106e, MID_FRAGMENT_GET_ACTIVITY, 0x0003, # invoke-virtual {v3}, Fragment.getActivity
    0x030c,                                # move-result-object v3 (Activity)
    0x0422, T_INTENT,                      # new-instance v4, Intent
    0x3070, MID_INTENT_CTOR, 0x0234,       # invoke-direct {v4,v3,v2}, Intent(Context,Class)
    0x021a, S_ROOT_URI,
    0x306e, MID_INTENT_PARCEL, 0x0024,     # v4.putExtra(v2,v0)
    0x021a, S_ROOT_NAME,
    0x306e, MID_INTENT_STRING, 0x0124,     # v4.putExtra(v2,v1)
    0x021a, S_START_URI,
    0x306e, MID_INTENT_PARCEL, 0x0024,
    0x021a, S_START_NAME,
    0x306e, MID_INTENT_STRING, 0x0124,
    0x206e, MID_ACTIVITY_START, 0x0043,     # v3.startActivity(v4)
    0x000e,                                # return-void
]
if len(main) >= 0x43:
    raise RuntimeError(('route too large', len(main)))
new = main + [0x0000]*(0x43-len(main)) + old[0x43:]
put_words(BROWSER_FOLDER, new)
# Expand existing try to catch the entire new route and land on preserved handler.
co,_ = d.method_code[BROWSER_FOLDER]
try_off = co + 16 + meta[4]*2
start_addr, count, handler_off = struct.unpack_from('<IHH', raw, try_off)
if handler_off != 1:
    raise RuntimeError(('unexpected handler offset', handler_off))
struct.pack_into('<IHH', raw, try_off, 0, 0x43, handler_off)

# ---------------- 3) WebDAV / SMB saved shortcut click -> TV ListingActivity ----------------
NEWROOT = unique_mid('Lcom/archos/mediacenter/video/browser/filebrowsing/network/NewRootFragment;', 'onShortcutTap')
meta = d.method_meta[NEWROOT]
if meta != (5,2,3,0,159):
    raise RuntimeError(('unexpected onShortcutTap meta', meta))
route = [
    0x1071, MID_FILEUTIL_NAME, 0x0004,      # FileUtils.getName(v4)
    0x010c,                                # v1 = name
    0x1071, MID_GET_TV_ACTIVITY, 0x0004,   # getActivityForUri(v4)
    0x020c,                                # v2 = Class
    0x106e, MID_FRAGMENT_GET_ACTIVITY, 0x0003,
    0x000c,                                # v0 = Activity
    0x0322, T_INTENT,                      # v3 = new Intent
    0x3070, MID_INTENT_CTOR, 0x0203,       # Intent(v0,v2)
    0x021a, S_ROOT_URI,
    0x306e, MID_INTENT_PARCEL, 0x0423,     # v3.putExtra(v2,v4)
    0x021a, S_ROOT_NAME,
    0x306e, MID_INTENT_STRING, 0x0123,     # v3.putExtra(v2,v1)
    0x021a, S_START_URI,
    0x306e, MID_INTENT_PARCEL, 0x0423,
    0x021a, S_START_NAME,
    0x306e, MID_INTENT_STRING, 0x0123,
    0x206e, MID_ACTIVITY_START, 0x0030,     # v0.startActivity(v3)
    0x000e,
]
put_words(NEWROOT, route + [0x0000]*(meta[4]-len(route)))

# ---------------- 4) Settings click -> TV settings Activity ----------------
START_PREF = unique_mid('Lcom/archos/mediacenter/video/browser/MainActivity;', 'startPreference')
meta = d.method_meta[START_PREF]
if meta != (5,1,3,0,44):
    raise RuntimeError(('unexpected startPreference meta', meta))
pref = [
    0x0022, T_INTENT,                      # v0 = new Intent
    0x011c, T_TV_SETTINGS,                 # v1 = VideoSettingsActivity.class
    0x3070, MID_INTENT_CTOR, 0x0140,       # Intent(v0, p0=v4, v1)
    0x206e, MID_ACTIVITY_START, 0x0004,     # p0.startActivity(v0)
    0x000e,
]
put_words(START_PREF, pref + [0x0000]*(meta[4]-len(pref)))

# ---------------- 5) Local TV listing honors clicked subfolder ----------------
SUPER_START_NAME = unique_mid('Lcom/archos/mediacenter/video/leanback/filebrowsing/ListingActivity;', 'getStartingName')
SUPER_START_URI = unique_mid('Lcom/archos/mediacenter/video/leanback/filebrowsing/ListingActivity;', 'getStartingUri')
LOCAL_START_NAME = unique_mid('Lcom/archos/mediacenter/video/leanback/filebrowsing/LocalListingActivity;', 'getStartingName')
LOCAL_START_URI = unique_mid('Lcom/archos/mediacenter/video/leanback/filebrowsing/LocalListingActivity;', 'getStartingUri')
if d.method_meta[LOCAL_START_NAME] != (1,1,1,0,5) or d.method_meta[LOCAL_START_URI] != (1,1,1,0,5):
    raise RuntimeError('LocalListing starting method metadata changed')
put_words(LOCAL_START_NAME, [0x106f, SUPER_START_NAME, 0x0000, 0x000c, 0x0011])
put_words(LOCAL_START_URI, [0x106f, SUPER_START_URI, 0x0000, 0x000c, 0x0011])

# Recompute DEX signature/checksum.
raw[12:32] = hashlib.sha1(raw[32:]).digest()
struct.pack_into('<I', raw, 8, zlib.adler32(raw[12:]) & 0xffffffff)
PATCHED_DEX.write_bytes(raw)
entries['classes.dex'] = bytes(raw)

# ---------------- Repack ----------------
with open(UNSIGNED, 'wb') as fout:
    with zipfile.ZipFile(fout, 'w', allowZip64=True) as zout:
        for name, zi in infos.items():
            if name.startswith('META-INF/'):
                continue
            content = entries[name]
            nzi = zipfile.ZipInfo(name, zi.date_time)
            nzi.compress_type = zi.compress_type
            nzi.comment = zi.comment
            nzi.internal_attr = zi.internal_attr
            nzi.external_attr = zi.external_attr
            nzi.create_system = zi.create_system
            nzi.flag_bits = zi.flag_bits & ~0x08
            nzi.extra = b''
            if name == 'resources.arsc':
                nzi.compress_type = zipfile.ZIP_STORED
                cur = fout.tell()
                baseoff = cur + 30 + len(name.encode('utf-8'))
                pad = next(n for n in range(4) if (baseoff + 4 + n) % 4 == 0)
                nzi.extra = struct.pack('<HH', 0xFFFF, pad) + b'\0' * pad
            zout.writestr(nzi, content, compress_type=nzi.compress_type, compresslevel=6)

# ---------------- APK Signature Scheme v2 ----------------
ALG=0x0103; V2_ID=0x7109871a; MAGIC=b'APK Sig Block 42'; CHUNK=1024*1024
def lp(x): return struct.pack('<I', len(x)) + x
def digest_sections(sections):
    chunks=[]
    for sec in sections:
        for i in range(0, len(sec), CHUNK):
            c=sec[i:i+CHUNK]
            chunks.append(hashlib.sha256(b'\xa5'+struct.pack('<I',len(c))+c).digest())
    return hashlib.sha256(b'\x5a'+struct.pack('<I',len(chunks))+b''.join(chunks)).digest()

ud = UNSIGNED.read_bytes()
eo = ud.rfind(b'PK\x05\x06', max(0, len(ud)-65557))
if eo < 0: raise RuntimeError('EOCD not found')
cd_off = struct.unpack_from('<I', ud, eo+16)[0]
cd_size = struct.unpack_from('<I', ud, eo+12)[0]
if cd_off + cd_size != eo: raise RuntimeError('central dir mismatch')
# Digest uses EOCD with the final central-directory offset after inserting sig block
pre = bytearray(ud[eo:])
# Block length not known yet but digest section 3 wants offset of signing block (old cd_off)
struct.pack_into('<I', pre, 16, cd_off)
dig = digest_sections([ud[:cd_off], ud[cd_off:eo], bytes(pre)])
key = serialization.load_der_private_key(KEY.read_bytes(), password=None)
cert_der = CERT_DER.read_bytes()
cert = x509.load_der_x509_certificate(cert_der)
pub_der = cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
key_pub = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
if key_pub != pub_der: raise RuntimeError('private key does not match APK certificate')
drec = struct.pack('<I', ALG) + lp(dig)
signed = lp(lp(drec)) + lp(lp(cert_der)) + lp(b'')
sig = key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
srec = struct.pack('<I', ALG) + lp(sig)
signer = lp(signed) + lp(lp(srec)) + lp(pub_der)
v2 = lp(lp(signer))
pair = struct.pack('<Q', 4+len(v2)) + struct.pack('<I', V2_ID) + v2
size = len(pair) + 8 + 16
block = struct.pack('<Q', size) + pair + struct.pack('<Q', size) + MAGIC
fe = bytearray(ud[eo:])
struct.pack_into('<I', fe, 16, cd_off + len(block))
OUT.write_bytes(ud[:cd_off] + block + ud[cd_off:eo] + bytes(fe))

print('OUT', OUT)
print('APK_SHA256', hashlib.sha256(OUT.read_bytes()).hexdigest())
print('DEX_SHA256', hashlib.sha256(bytes(raw)).hexdigest())
print('CERT_SHA256', hashlib.sha256(cert_der).hexdigest())
print('MODIFIED_METHODS')
for mid in [ENTRY, BROWSER_FOLDER, NEWROOT, START_PREF, LOCAL_START_NAME, LOCAL_START_URI]:
    print(mid, d.mname(mid))
print('ENTRY_DIFF_FROM_R19', diffs)
print('ROUTE_WORDS', len(main), len(route), len(pref))
