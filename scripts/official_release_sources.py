#!/usr/bin/env python3
"""Bind a Nova mod build to both assets and exact source commits of official v6.6.4.

The release's downloadable manifest.xml is generated with pinned revisions.
A moving 'v6.6' branch or an old AVOS checkout is not a release source lock.
Fail closed on any source, asset, or release mismatch.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import check_upstream

TAG = "v6.6.4"
APK_SHA256 = "1aa2068ffec42a86efe4cee790a3f03e61194a01261405baff73ecdef1ca9ee4"
MANIFEST_SHA256 = "d64e3270af8f163737e647d2e39e3c158c94b0a87359089746d2a325d5b4f975"
REQUIRED = {"AVP", "Video", "MediaLib", "FileCoreLibrary",
            "native/avos", "native/prebuilt/ffmpeg", "native/prebuilt/openssl"}
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")


def read_selection(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data.get("repository") != check_upstream.REPOSITORY or
        data.get("policy") != "github-official-latest-stable" or
        data.get("tag") != TAG or
        data.get("status") != "DOWNLOADED_AND_VERIFIED" or
        data.get("downloaded_sha256") != APK_SHA256 or
        data.get("official_sha256") != APK_SHA256):
        raise ValueError("Must use latest stable official v6.6.4 universal APK with exact release digest")
    return data


def parse_manifest(manifest: Path) -> dict[str, dict[str, str]]:
    if check_upstream.sha256_file(manifest) != MANIFEST_SHA256:
        raise ValueError("Official v6.6.4 release manifest SHA256 mismatch")
    root = ET.parse(manifest).getroot()
    if root.tag != "manifest":
        raise ValueError("Invalid official repo manifest root")
    projects = {}
    for entry in root.findall("project"):
        name = entry.get("name")
        path = entry.get("path", name)
        revision = entry.get("revision")
        if not name or not path or not revision or not SHA_RE.fullmatch(revision):
            raise ValueError("Release manifest contains missing or non-immutable project revision: " + str(path))
        if path in projects:
            raise ValueError("Duplicate source project path: " + path)
        if path.startswith("/") or ".." in Path(path).parts:
            raise ValueError("Unsafe release project path: " + path)
        projects[path] = {"name": name, "path": path, "sha": revision}
    if len(projects) < 25 or not REQUIRED.issubset(projects):
        raise ValueError("Official release manifest missing required source repositories")
    if projects["native/avos"]["sha"] == "d4abfdf075d4f7bfdee9a47cb2c02067f92f47cd":
        raise ValueError("Refusing the legacy #967 AVOS pin instead of v6.6.4")
    return projects


def load_manifest_and_metadata(manifest: Path, metadata: Path) -> dict:
    read_selection(metadata)
    return parse_manifest(manifest)


def download(metadata: Path, apk: Path, manifest: Path, report: Path) -> None:
    selected = read_selection(metadata)
    if check_upstream.sha256_file(apk) != APK_SHA256:
        raise ValueError("Downloaded base APK digest differs from official v6.6.4")
    release_id = selected["release_id"]
    if not isinstance(release_id, int):
        raise ValueError("Invalid upstream release id")
    assets = check_upstream.get_json(
        f"{check_upstream.API_ROOT}/releases/{release_id}/assets?per_page=100&page=1")
    candidates = [a for a in assets if a.get("name") == "manifest.xml"]
    if len(candidates) != 1:
        raise ValueError("Official release must contain exactly one manifest.xml asset")
    asset = candidates[0]
    url = f"https://github.com/nova-video-player/aos-AVP/releases/download/{TAG}/manifest.xml"
    if (asset.get("browser_download_url") != url or asset.get("state") != "uploaded" or
        asset.get("digest") != "sha256:" + MANIFEST_SHA256 or
        asset.get("size") != 6427):
        raise ValueError("Release's immutable source manifest asset metadata differs from the official v6.6.4 release")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.unlink(missing_ok=True)
    try:
        check_upstream.download_file(url, manifest)
        if manifest.stat().st_size != 6427:
            raise ValueError("Official manifest size mismatch")
        sources = parse_manifest(manifest)
    except Exception:
        manifest.unlink(missing_ok=True)
        raise
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({
        "status": "PASS", "official_tag": TAG, "official_apk_sha256": APK_SHA256,
        "official_manifest_sha256": MANIFEST_SHA256,
        "official_manifest_asset_url": url,
        "source_count": len(sources), "source_revisions": sources,
        "native_avos_sha": sources["native/avos"]["sha"],
        "verified_official_release_asset": True,
    }, indent=2) + "\n", encoding="utf-8")
    print("OFFICIAL_V664_APK_AND_RELEASE_MANIFEST=PASS")
    print("OFFICIAL_V664_NATIVE_AVOS_COMMIT=" + sources["native/avos"]["sha"])


def overlay(manifest: Path, metadata: Path, output: Path) -> None:
    projects = load_manifest_and_metadata(manifest, metadata)
    root = ET.Element("manifest")
    for project in projects.values():
        ET.SubElement(root, "extend-project", {
            "name": project["name"],
            "path": project["path"],
            "revision": project["sha"],
        })
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    print("OFFICIAL_V664_EXACT_RELEASE_SOURCE_LOCK=" + str(output))


def verify(manifest: Path, metadata: Path, root: Path, report: Path) -> None:
    projects = load_manifest_and_metadata(manifest, metadata)
    found = {}
    for path, entry in projects.items():
        git_dir = root / path
        got = subprocess.check_output(
            ["git", "-C", str(git_dir), "rev-parse", "HEAD"], text=True).strip()
        if got != entry["sha"]:
            raise ValueError(f"Official v6.6.4 release source mismatch at {path}: expected {entry['sha']}, got {got}")
        found[path] = got
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({
        "status": "PASS", "official_tag": TAG,
        "official_apk_sha256": APK_SHA256,
        "official_manifest_sha256": MANIFEST_SHA256,
        "verified_git_commits": found,
        "native_avos_sha": found["native/avos"],
    }, indent=2) + "\n", encoding="utf-8")
    print("OFFICIAL_V664_ALL_RELEASE_SOURCE_COMMITS=PASS count=" + str(len(found)))
    print("OFFICIAL_V664_AVOS_SOURCE_SHA=" + found["native/avos"])


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for cmd in ("download", "overlay", "verify"):
        q = sub.add_parser(cmd)
        q.add_argument("--metadata", type=Path, required=True)
        q.add_argument("--manifest", type=Path, required=True)
        if cmd == "download":
            q.add_argument("--apk", type=Path, required=True)
        if cmd == "overlay":
            q.add_argument("--output", type=Path, required=True)
        if cmd == "verify":
            q.add_argument("--root", type=Path, required=True)
        if cmd != "overlay":
            q.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    if a.cmd == "download":
        download(a.metadata, a.apk, a.manifest, a.report)
    elif a.cmd == "overlay":
        overlay(a.manifest, a.metadata, a.output)
    else:
        verify(a.manifest, a.metadata, a.root, a.report)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("::error::" + str(exc).replace("\n", " "), file=sys.stderr)
        raise
