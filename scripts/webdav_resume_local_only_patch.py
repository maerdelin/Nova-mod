#!/usr/bin/env python3
"""Keep WebDAV playback resume remote-write-free, while preserving local DB.

Scope: only OkHttpSardine.put(String,File,String), hidden Archos resume XML.
No media GET/seek, player/UI, credentials, local database, or native changes.
#496 had this behavior. Implement without adding any helper DEX.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

MARKER = "NOVA_WEBDAV_RESUME_LOCAL_ONLY_V1"
SARDINE = "Lcom/thegrizzlylabs/sardineandroid/impl/OkHttpSardine;"
PROTO = "(Ljava/lang/String;Ljava/io/File;Ljava/lang/String;)V"
OLD_HEADER = ".method public put" + PROTO
RENAMED_HEADER = ".method public novaPutOriginalFile" + PROTO
CLASS_PATH = "com/thegrizzlylabs/sardineandroid/impl/OkHttpSardine.smali"
URL_PATTERN = r"(?i)^(?:https?|webdavs?)://[^/?#]+/(?:[^?#]*/)?[.][^/?#]+[.]archos[.]resume[.]xml(?:[?#].*)?$"

# Only the hidden .video.mkv.0.archos.resume.xml sidecar. On all other
# URLs delegate to the exact original method body. Decode %2E for
# recognition only (never rewrite the URI passed to the original method).
WRAPPER = '''
.method public put(Ljava/lang/String;Ljava/io/File;Ljava/lang/String;)V
    .locals 3

    # NOVA_WEBDAV_RESUME_LOCAL_ONLY_V1: remote progress HTTP PUT forbidden
    if-eqz p1, :nova_resume_original_put

    const-string v0, "%2E"

    const-string v1, "."

    invoke-virtual {p1, v0, v1}, Ljava/lang/String;->replace(Ljava/lang/CharSequence;Ljava/lang/CharSequence;)Ljava/lang/String;

    move-result-object v2

    const-string v0, "%2e"

    invoke-virtual {v2, v0, v1}, Ljava/lang/String;->replace(Ljava/lang/CharSequence;Ljava/lang/CharSequence;)Ljava/lang/String;

    move-result-object v2

    const-string v0, "(?i)^(?:https?|webdavs?)://[^/?#]+/(?:[^?#]*/)?[.][^/?#]+[.]archos[.]resume[.]xml(?:[?#].*)?$"

    invoke-static {v0, v2}, Ljava/util/regex/Pattern;->matches(Ljava/lang/String;Ljava/lang/CharSequence;)Z

    move-result v0

    if-eqz v0, :nova_resume_original_put

    # No HTTP request; the caller's local player database is untouched.
    return-void

    :nova_resume_original_put
    invoke-virtual {p0, p1, p2, p3}, Lcom/thegrizzlylabs/sardineandroid/impl/OkHttpSardine;->novaPutOriginalFile(Ljava/lang/String;Ljava/io/File;Ljava/lang/String;)V

    return-void
.end method
'''.strip()

METHOD = re.compile(
    r"(?ms)^\.method public put\(Ljava/lang/String;Ljava/io/File;Ljava/lang/String;\)V\n"
    r".*?^\.end method$"
)

def classify_url(url: str | None) -> bool:
    if url is None:
        return False
    normalized = url.replace("%2E", ".").replace("%2e", ".")
    return re.fullmatch(URL_PATTERN, normalized) is not None

def patch_source(source: str) -> str:
    if MARKER in source or "novaPutOriginalFile" in source:
        raise RuntimeError("WebDAV local-only resume already patched")
    if not re.search(r"(?m)^\.class .*Lcom/thegrizzlylabs/sardineandroid/impl/OkHttpSardine;$", source):
        raise RuntimeError("Unexpected Sardine class identity")
    found = list(METHOD.finditer(source))
    if len(found) != 1:
        raise RuntimeError(f"Expected exactly one reviewed Sardine file PUT, found {len(found)}")
    m = found[0]
    original = m.group()
    if original.count(OLD_HEADER) != 1:
        raise RuntimeError("Unexpected Sardine file PUT declaration")
    if re.search(r"(?m)^    \.(?:locals|registers) \d+$", original) is None:
        raise RuntimeError("Unexpected Sardine file PUT register layout")
    renamed = original.replace(OLD_HEADER, RENAMED_HEADER, 1)
    result = source[:m.start()] + renamed + "\n\n" + WRAPPER + source[m.end():]
    if result.count(OLD_HEADER) != 1 or result.count(RENAMED_HEADER) != 1:
        raise RuntimeError("Sardine original/wrapper declaration count changed")
    if result.count(MARKER) != 1:
        raise RuntimeError("Sardine local-only sentinel missing")
    return result

def apply(root: Path, report: Path) -> dict:
    hits = list(root.glob("smali*/**/" + CLASS_PATH))
    if len(hits) != 1:
        raise RuntimeError(f"Expected one OkHttpSardine class, found {len(hits)}")
    target = hits[0]
    original = target.read_text(encoding="utf-8")
    rewritten = patch_source(original)
    target.write_text(rewritten, encoding="utf-8")
    record = {
        "status": "PASS", "marker": MARKER,
        "changed_smali": str(target.relative_to(root)),
        "remote_resume_sidecar_put": "short-circuited before network",
        "other_puts": "original file PUT method preserved and delegated",
        "modified_local_database": False,
        "modified_media_get_or_seek": False,
        "modified_player_ui_or_native": False,
        "runtime_probe_required": True,
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(record, indent=2) + "\n")
    print(MARKER + "=PASS")
    return record
