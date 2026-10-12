#!/usr/bin/env python3
"""Reconstruct stable V6.3 DEX and resource bytes from one verified Nova 6.5.5 APK."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import zipfile
import zlib

SOURCE_SHA256 = "2912258dafe8e5bb7e057885b7e2228c581d8a30682ced87036ee11db409443e"
SIGNED_RELEASE_SHA256 = "0978bbf6b8e54ee83fe9c5df221e994c0f3942a574817742f1fda874c7221231"
EXPECTED = {
    "classes.dex": "923c098958b91877f1da7e84c04556b1aa019048d674e208d01bfd8dab6a40ae",
    "resources.arsc": "e6b1e698d366582c9fe4fda32094f945ff70f2aaa61033034da94ee1ae7caa19",
}
# zlib-compressed JSON [(byte_offset, replacement_hex), ...]; not an APK or a key.
PATCHES = {
    "classes.dex": "eNqdVkt26zAI3UvHHQACJK2l5w383f8SHsiNbNc4aZNJD3D5XoT79VU+P5KWkheapizzPFQe5lUF1zJXxKxprQsmUkyTLGmcef349/mVCmNlc0bqosDnB6xgv13FpjqI6uLj19VKR/Xx1yGZ7yAXaIUwSY1yE0CYu5vxYN6V5ZfFEKRe964qTzNyeTEMAoWwFdWg1kwHBkzk0LXAz6S7qYQelZ91gXDpGyEMhHhcERP12Ww7LIUjwKSXtBwjOVwHlKfrgOdN3dXlbnz2gB7tMRJVT4sr0Kww6IIwLzyCbSEsu18DKl4L6cYMh6BSGkULwOuddHiFS+tNjXQImhU8B3bRrRmM14Un+/PA1eqLsMouWi06bGKy8N5G3kWz5rGLeLb6u5p3kcyqB9HKJnmISejaReIC7Sa1kR7VPnfiTWTA/XI10S+XjAVgldVZWQfM9iYAJrDn2mFqrYppHULjjN8QTMU6yR2WfQSPKNggZBDb7Q7xG2VFpqE0U4LZure1cNmqSfbELYs91wWWZL3stZK/FzcNK8xuMiTynAbXWdLJEz4ydqckPqxjRiutZ2yLuLpTc02pQrL3alkhedj0XQVMPaBvoIVhH4G7l9FaYIMMIOYu2GdNRbdxwIilTWzYJuYbK1zQPjZLk4et55Jh9iZQgdY2bcuCrrMalp1VNllfHeITnE9HaVOV6xaZev9ubeKPy9qUSieMcoDJEIbPUbxCv2kmaoxB765WM19vajcRRwVygluPFE6Mmf9SfXfT+9LyiQOOZsblxIE98wBTQw64BvEE3uZA6CkHkm4bFQ45ELnlQCTkQPQtDqTcl1ZPHEg0M4UTBwoBB4ohB4pRPHqbA+WnHKjcNqoacqD5lgPNIQda3uIgR99kU+Npthl/BO8GotCdwhpzCpvNDK/+9Wowea/D/KdbnR+b9+8/1ZiX/g==",
    "resources.arsc": "eNqLjjYyMDC2MDDRUTIAA6VYHbCQpaUZREgpNhYAlk0H4w==",
}

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def patch_file(name, data):
    changes = json.loads(zlib.decompress(base64.b64decode(PATCHES[name])))
    out = bytearray(data)
    for offset, replacement in changes:
        b = bytes.fromhex(replacement)
        if offset < 0 or offset + len(b) > len(out):
            raise ValueError("Patch offset outside " + name)
        out[offset:offset+len(b)] = b
    if sha256(out) != EXPECTED[name]:
        raise ValueError("V6.3 " + name + " verification failed")
    return bytes(out)

def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit("Usage: python3 tools/rebuild_unsigned.py original-nova.apk [unsigned-output.apk]")
    source = Path(sys.argv[1])
    target = Path(sys.argv[2]) if len(sys.argv) == 3 else Path("NovaTV-V6.3-unsigned.apk")
    if sha256(source.read_bytes()) != SOURCE_SHA256:
        raise SystemExit("REFUSED: original official Nova APK hash is different")
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w") as dst:
        if src.testzip() is not None:
            raise SystemExit("REFUSED: corrupt input archive")
        for info in src.infolist():
            if info.is_dir():
                continue
            upper = info.filename.upper()
            if upper == "META-INF/MANIFEST.MF" or (
                upper.startswith("META-INF/") and upper.endswith((".SF",".RSA",".DSA",".EC"))
            ):
                continue
            content = src.read(info.filename)
            if info.filename in PATCHES:
                content = patch_file(info.filename, content)
            zi = zipfile.ZipInfo(info.filename, info.date_time)
            zi.compress_type = info.compress_type
            zi.internal_attr = info.internal_attr
            zi.external_attr = info.external_attr
            zi.create_system = info.create_system
            dst.writestr(zi, content, compress_type=zi.compress_type, compresslevel=6)
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        for filename, expected in EXPECTED.items():
            assert sha256(z.read(filename)) == expected
    print("PASS: V6.3 classes.dex/resources.arsc byte-exact.")
    print("Unsigned APK:", target)
    print("The APK is NOT installable until signed. Never commit a private signing key.")
    print("User-approved signed V6.3 SHA256:", SIGNED_RELEASE_SHA256)

if __name__ == "__main__":
    main()
