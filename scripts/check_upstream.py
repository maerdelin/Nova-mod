#!/usr/bin/env python3
"""Resolve and download the official Latest stable APK; never fall back.

Selection has no version parser or pinned version. Compatibility is a separate
fail-closed gate: the existing binary overlay is NOT a cross-version patcher.
Python 3.10+; standard library plus curl for HTTPS asset downloads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import zipfile

REPOSITORY = "nova-video-player/aos-AVP"
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}"
LATEST_URL = f"{API_ROOT}/releases/latest"
POLICY = "github-official-latest-stable"
DIGEST_RE = re.compile(r"sha256:([0-9a-fA-F]{64})\Z")
UNIVERSAL_RE = re.compile(r"(?:^|[._-])universal(?:[._-]|$)", re.I)
UNSAFE_FLAVOR_RE = re.compile(r"(?:^|[._-])(?:debug|unsigned|test|beta|alpha|preview)(?:[._-]|$)", re.I)


class UpstreamError(RuntimeError):
    """A selection, download, provenance, or compatibility failure."""


def clean_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise UpstreamError(f"Invalid {label}")
    return value


def positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise UpstreamError(f"Invalid {label}")
    return value


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        try:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def summary(text: str) -> None:
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(text + "\n\n")


def action_outputs(**values: str | int) -> None:
    if path := os.environ.get("GITHUB_OUTPUT"):
        with open(path, "a", encoding="utf-8") as stream:
            for key, value in values.items():
                value = clean_text(str(value), key)
                stream.write(f"{key}={value}\n")


def get_json(url: str) -> Any:
    # Do not send the Actions token to asset/CDN hosts or arbitrary API URLs.
    if not url.startswith(API_ROOT + "/"):
        raise UpstreamError("Unexpected API URL")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Nova-Video-Player-mod",
               "Cache-Control": "no-cache", "X-GitHub-Api-Version": "2026-03-10"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    for attempt in range(4):
        try:
            with urlopen(Request(url, headers=headers), timeout=45) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise UpstreamError(f"Official release API failed (HTTP {exc.code}); no fallback") from exc
        except (URLError, TimeoutError, ConnectionError) as exc:
            if attempt == 3:
                raise UpstreamError("Official release API unavailable; no fallback") from exc
        except (ValueError, UnicodeError) as exc:
            raise UpstreamError("Invalid official release API response; no fallback") from exc
        time.sleep(2 ** attempt)
    raise UpstreamError("Official release API failed")


def validate_release(release: Any) -> dict[str, Any]:
    if not isinstance(release, dict):
        raise UpstreamError("Latest release is not a JSON object")
    if release.get("draft") is not False or release.get("prerelease") is not False:
        raise UpstreamError("Latest endpoint did not return a published stable release")
    positive_int(release.get("id"), "release ID")
    clean_text(release.get("tag_name"), "release tag")
    clean_text(release.get("published_at"), "publication time")
    return release


def select_asset(assets: Any) -> dict[str, Any]:
    if not isinstance(assets, list) or any(not isinstance(a, dict) for a in assets):
        raise UpstreamError("Invalid release asset list")
    matches = []
    for asset in assets:
        name = asset.get("name", "")
        if (isinstance(name, str) and name.lower().endswith(".apk")
                and UNIVERSAL_RE.search(name) and not UNSAFE_FLAVOR_RE.search(name)):
            matches.append(asset)
    # Select the latest release first. Never search older releases for an APK.
    if len(matches) != 1:
        raise UpstreamError(f"Latest release must contain exactly one universal APK; found {len(matches)}. No older-version fallback")
    asset = matches[0]
    positive_int(asset.get("id"), "asset ID")
    positive_int(asset.get("size"), "asset size")
    clean_text(asset.get("name"), "asset name")
    if asset.get("state") != "uploaded":
        raise UpstreamError("Latest universal APK upload is not complete")
    digest = asset.get("digest")
    if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
        raise UpstreamError("Official asset SHA-256 is missing or invalid; refusing an unverified download")
    url = clean_text(asset.get("browser_download_url"), "asset download URL")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment
            or not parsed.path.startswith(f"/{REPOSITORY}/releases/download/")):
        raise UpstreamError("APK URL is not an official repository release asset")
    return asset


def resolve_latest(fetch_json: Callable[[str], Any] | None = None) -> dict[str, Any]:
    fetch = fetch_json or get_json
    release = validate_release(fetch(LATEST_URL))
    assets: list[dict[str, Any]] = []
    # Fetch all asset pages, not a potentially partial embedded assets array.
    for page in range(1, 101):
        batch = fetch(f"{API_ROOT}/releases/{release['id']}/assets?per_page=100&page={page}")
        if not isinstance(batch, list):
            raise UpstreamError("Invalid paginated asset response")
        assets.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise UpstreamError("Excessive asset pages; refusing a partial selection")
    asset = select_asset(assets)
    return {"schema_version": 1, "policy": POLICY, "repository": REPOSITORY,
            "release_id": release["id"], "tag": release["tag_name"],
            "published_at": release["published_at"], "asset_id": asset["id"],
            "asset_name": asset["name"], "download_url": asset["browser_download_url"],
            "official_sha256": asset["digest"].split(":", 1)[1].lower(),
            "size_bytes": asset["size"], "selection_endpoint": LATEST_URL,
            "resolved_at_utc": datetime.now(timezone.utc).isoformat(), "status": "SELECTED"}


def download_file(url: str, destination: Path) -> None:
    try:
        subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error",
                        "--retry", "4", "--retry-all-errors", "--retry-delay", "3", "--retry-max-time", "900",
                        "--connect-timeout", "20", "--max-time", "300",
                        "--proto", "=https", "--proto-redir", "=https",
                        "--output", str(destination), "--", url], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise UpstreamError("Latest APK download failed; no fallback") from exc


def validate_apk(path: Path, selected: dict[str, Any]) -> str:
    if not path.is_file() or path.stat().st_size != selected["size_bytes"]:
        raise UpstreamError("APK size does not match the selected official asset")
    digest = sha256_file(path)
    if digest != selected["official_sha256"]:
        raise UpstreamError("APK SHA-256 does not match the selected official asset")
    try:
        with zipfile.ZipFile(path) as apk:
            names = apk.namelist()
            if len(names) != len(set(names)):
                raise UpstreamError("APK has duplicate ZIP entries")
            if not {"AndroidManifest.xml", "classes.dex", "resources.arsc"}.issubset(names):
                raise UpstreamError("Download is not the expected complete Android APK")
            if apk.testzip() is not None:
                raise UpstreamError("APK ZIP integrity check failed")
    except zipfile.BadZipFile as exc:
        raise UpstreamError("Download is not a valid APK ZIP") from exc
    return digest


def download_latest(output: Path, metadata: Path, *, fetch_json=None, downloader=None) -> dict[str, Any]:
    if output.resolve() == metadata.resolve():
        raise UpstreamError("APK and metadata paths must differ")
    # A failed lookup/download cannot leave a stale APK for later steps to reuse.
    output.unlink(missing_ok=True)
    metadata.unlink(missing_ok=True)
    selected = resolve_latest(fetch_json)
    write_json(metadata, selected)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".part", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        (downloader or download_file)(selected["download_url"], temporary)
        selected["downloaded_sha256"] = validate_apk(temporary, selected)
        os.replace(temporary, output)
        selected["status"] = "DOWNLOADED_AND_VERIFIED"
        write_json(metadata, selected)
    except Exception as exc:
        output.unlink(missing_ok=True)
        selected["status"] = "DOWNLOAD_FAILED"
        selected["error"] = str(exc)
        write_json(metadata, selected)
        raise
    finally:
        temporary.unlink(missing_ok=True)
    action_outputs(tag=selected["tag"], release_id=selected["release_id"],
                   asset_id=selected["asset_id"], sha256=selected["downloaded_sha256"])
    summary(f"## Dynamic official latest\n\nSelected official release: `{selected['tag']}`\n\n"
            f"Asset: `{selected['asset_name']}`\n\nSHA-256: `{selected['downloaded_sha256']}`\n\n"
            f"Build input: `{output}`. Download and integrity verification completed. No version fallback.")
    print("LATEST_OFFICIAL=" + selected["tag"])
    print("LATEST_UPSTREAM_SHA256=" + selected["downloaded_sha256"])
    return selected


def load_selection(metadata: Path, apk: Path) -> dict[str, Any]:
    selected = json.loads(metadata.read_text(encoding="utf-8"))
    if selected.get("policy") != POLICY or selected.get("repository") != REPOSITORY:
        raise UpstreamError("Unexpected upstream selection provenance")
    if selected.get("status") != "DOWNLOADED_AND_VERIFIED":
        raise UpstreamError("Selected upstream APK was not downloaded and verified")
    digest = validate_apk(apk, selected)
    if digest != selected.get("downloaded_sha256"):
        raise UpstreamError("Selected APK changed after download")
    return selected


def compatibility_gate(apk: Path, metadata: Path, baseline: Path, report: Path) -> None:
    selected = load_selection(metadata, apk)
    manifest = json.loads(baseline.read_text(encoding="utf-8"))
    tested_digest = manifest.get("upstream_sha256")
    if not isinstance(tested_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", tested_digest):
        raise UpstreamError("Baseline manifest has no valid tested upstream SHA-256")
    approved = selected["downloaded_sha256"] == tested_digest
    status = "APPROVED_TESTED_BINARY_BASE" if approved else "BLOCKED_UNPORTED_UPSTREAM"
    write_json(report, {"status": status, "selected_tag": selected["tag"],
                       "selected_sha256": selected["downloaded_sha256"],
                       "tested_upstream_sha256": tested_digest,
                       "old_version_fallback": False,
                       "note": "This gate approves only the existing overlay's exact tested base. It does not port patches to a new version."})
    summary(f"## Binary patch compatibility\n\nSelected upstream: `{selected['tag']}`. Status: **{status}**.\n\n"
            "The saved binary overlay is only verified for its recorded upstream digest. "
            "An unported new upstream stops the build; the previous stable release is not replaced.")
    print("STATUS=" + status)
    if not approved:
        raise UpstreamError(f"Latest official {selected['tag']} was downloaded, but existing binary patches are not verified for it. "
                            "Port and test the patches before publishing. No old APK was substituted")


def assert_current(apk: Path, metadata: Path, *, fetch_json=None) -> None:
    selected = load_selection(metadata, apk)
    current = resolve_latest(fetch_json)
    keys = ("release_id", "tag", "asset_id", "official_sha256", "size_bytes", "download_url")
    if any(selected[k] != current[k] for k in keys):
        raise UpstreamError("Official latest release/asset changed during this build; rerun instead of publishing a stale selection")
    summary(f"Pre-publish freshness check passed for official `{selected['tag']}`.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    download = sub.add_parser("download", help="Resolve and download the official Latest stable APK")
    download.add_argument("--apk", type=Path, default=Path("inputs/official.apk"))
    download.add_argument("--metadata", type=Path, default=Path("inputs/upstream.json"))
    guard = sub.add_parser("guard", help="Stop unless the saved binary overlay is approved for this exact input")
    guard.add_argument("--apk", type=Path, default=Path("inputs/official.apk"))
    guard.add_argument("--metadata", type=Path, default=Path("inputs/upstream.json"))
    guard.add_argument("--baseline", type=Path, default=Path("baseline/manifest.json"))
    guard.add_argument("--report", type=Path, default=Path("inputs/compatibility.json"))
    fresh = sub.add_parser("assert-current", help="Re-query official Latest before publishing")
    fresh.add_argument("--apk", type=Path, default=Path("inputs/official.apk"))
    fresh.add_argument("--metadata", type=Path, default=Path("inputs/upstream.json"))
    args = parser.parse_args()
    try:
        if args.command == "download":
            download_latest(args.apk, args.metadata)
        elif args.command == "guard":
            compatibility_gate(args.apk, args.metadata, args.baseline, args.report)
        else:
            assert_current(args.apk, args.metadata)
    except (UpstreamError, OSError, ValueError, KeyError, TypeError) as exc:
        # Escape workflow annotation metacharacters and newlines.
        message = str(exc).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print("::error::" + message, file=sys.stderr)
        summary("**STOPPED:** " + str(exc) + ". No old-version fallback was performed.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
