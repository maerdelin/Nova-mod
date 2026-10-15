#!/usr/bin/env python3
"""Check upstream stable release without changing the SHA-locked V9.8.2 baseline.

A candidate is only eligible for automated *native-library-only* integration
when every non-native upstream APK entry is byte-identical to pinned v6.5.5.
Anything else requires reviewing and porting the V9.8.2 DEX/resource patches.
No CI result is a substitute for on-device runtime testing.
"""
import json, os, re, urllib.request, urllib.error, pathlib, hashlib, zipfile, subprocess, sys

OWNER="nova-video-player"
REPO="aos-AVP"
API=f"https://api.github.com/repos/{OWNER}/{REPO}/releases?per_page=40"
PINNED="v6.5.5"
PINNED_SHA="f252631680328916ed847c8c0d6711d6a9922373e54f939178c428a9b3c3e1a5"

def get_json(url):
    req=urllib.request.Request(url,headers={"Accept":"application/vnd.github+json","User-Agent":"Nova-Video-Player-mod-upstream-watcher"})
    with urllib.request.urlopen(req,timeout=40) as r:
        return json.load(r)

def version(tag):
    m=re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)",tag)
    return tuple(map(int,m.groups())) if m else None

def download(url, path):
    subprocess.run(["curl","--fail","--location","--retry","4","--retry-delay","3","--output",str(path),url],check=True)

def compatible_with_locked_base(original, candidate):
    with zipfile.ZipFile(original) as a, zipfile.ZipFile(candidate) as b:
        aa={i.filename:i for i in a.infolist() if not i.is_dir()}
        bb={i.filename:i for i in b.infolist() if not i.is_dir()}
        changes=[]
        for p in sorted(set(aa)|set(bb)):
            # APK signatures will change on official builds, ignore signature metadata.
            if p.upper().startswith("META-INF/"):continue
            if p not in aa or p not in bb or a.read(p)!=b.read(p):
                changes.append(p)
        non_native=[p for p in changes if not p.startswith("lib/")]
        return len(changes),non_native

def main():
    rels=get_json(API)
    rels=[r for r in rels if not r.get("draft") and not r.get("prerelease") and version(r["tag_name"])]
    if not rels:raise RuntimeError("No stable upstream semantic releases found")
    r=max(rels,key=lambda x:version(x["tag_name"]))
    tag=r["tag_name"]
    print("LATEST_OFFICIAL="+tag)
    print("PINNED_BASELINE="+PINNED)
    summary=pathlib.Path(os.environ.get("GITHUB_STEP_SUMMARY","/dev/null"))
    with summary.open("a") as f:
        f.write(f"## Nova upstream check\n\nLatest official stable: **{tag}**. Protected verified baseline: **V9.8.2 / {PINNED}**.\n\n")
    if version(tag)<=version(PINNED):
        print("STATUS=NO_NEW_VERSION")
        with summary.open("a") as f:f.write("No newer stable release. No changes made.\n")
        return
    assets=[a for a in r["assets"] if a["name"].endswith("-universal-release.apk")]
    if len(assets)!=1:raise RuntimeError(f"Expected one official universal APK for {tag}, found {len(assets)}")
    os.makedirs("inputs",exist_ok=True)
    new=pathlib.Path("inputs/latest-upstream.apk")
    download(assets[0]["browser_download_url"],new)
    digest=hashlib.sha256(new.read_bytes()).hexdigest()
    print("LATEST_UPSTREAM_SHA256="+digest)
    source=pathlib.Path("inputs/official.apk")
    if not source.is_file():
        raise RuntimeError("Pinned baseline APK unavailable for compatibility check")
    if hashlib.sha256(source.read_bytes()).hexdigest()!=PINNED_SHA:
        raise RuntimeError("Pinned baseline APK SHA mismatch")
    num,non_native=compatible_with_locked_base(source,new)
    print("UPSTREAM_CHANGED_ENTRIES="+str(num))
    with summary.open("a") as f:
        f.write(f"New version downloaded and SHA-256 recorded: `{digest}`.\n\n")
        f.write(f"Modified/missing APK entries: **{num}**. Non-native changed entries: **{len(non_native)}**.\n\n")
        if non_native:
            f.write("**BLOCKED:** DEX/resources or other non-native files differ from the pinned baseline. Do not auto-port V9.8.2 DEX offsets or publish a replacement stable APK.\n\n")
            f.write("Examples: `"+", ".join(non_native[:16])+"`\n")
        else:
            f.write("**NATIVE-ONLY CANDIDATE:** automated repackaging may be feasible. Still needs ABI/API checks, signing and real-device tests before stable release. V9.8.2 remains unchanged.\n")
    print("STATUS="+("BLOCKED_NON_NATIVE_CHANGE" if non_native else "NATIVE_ONLY_CANDIDATE"))
    for p in non_native[:30]:print("CHANGED_NON_NATIVE="+p)
if __name__=="__main__":
    main()
