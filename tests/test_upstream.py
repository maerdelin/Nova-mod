"""Offline behavior tests: mock official API responses and synthetic APK ZIPs.
These are not a live APK build, Android runtime, or GitHub Actions test.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_upstream", ROOT / "scripts/check_upstream.py")
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


def apk_bytes() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("AndroidManifest.xml", b"synthetic manifest")
        z.writestr("classes.dex", b"synthetic dex")
        z.writestr("resources.arsc", b"synthetic resources")
    return out.getvalue()


class UpstreamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.apk = self.root / "inputs/official.apk"
        self.metadata = self.root / "inputs/upstream.json"
        self.report = self.root / "inputs/compatibility.json"
        self.baseline = self.root / "baseline.json"
        self.payload = apk_bytes()
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.release = {"id": 700, "tag_name": "v6.7", "draft": False, "prerelease": False,
                        "published_at": "2027-01-01T00:00:00Z"}
        self.asset = {"id": 701, "name": "Nova-6.7-universal-release.apk", "state": "uploaded",
                      "size": len(self.payload), "digest": "sha256:" + self.digest,
                      "browser_download_url": f"https://github.com/{u.REPOSITORY}/releases/download/v6.7/Nova-6.7-universal-release.apk"}
        self.requests = []
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def fetch(self, url):
        self.requests.append(url)
        if url == u.LATEST_URL:
            return copy.deepcopy(self.release)
        if url == f"{u.API_ROOT}/releases/700/assets?per_page=100&page=1":
            return [copy.deepcopy(self.asset)]
        raise AssertionError("Unexpected URL: " + url)

    def downloader(self, url, destination):
        self.assertEqual(url, self.asset["browser_download_url"])
        destination.write_bytes(self.payload)

    def download(self):
        return u.download_latest(self.apk, self.metadata, fetch_json=self.fetch, downloader=self.downloader)

    def test_v67_two_component_tag(self):
        self.assertEqual(u.resolve_latest(self.fetch)["tag"], "v6.7")

    def test_v670_three_component_tag(self):
        self.release["tag_name"] = "v6.7.0"
        self.assertEqual(u.resolve_latest(self.fetch)["tag"], "v6.7.0")

    def test_version_without_v_prefix(self):
        self.release["tag_name"] = "6.7"
        self.assertEqual(u.resolve_latest(self.fetch)["tag"], "6.7")

    def test_future_major_tag(self):
        self.release["tag_name"] = "v7.0"
        self.assertEqual(u.resolve_latest(self.fetch)["tag"], "v7.0")

    def test_non_numeric_official_tag(self):
        self.release["tag_name"] = "release-2027-spring"
        self.assertEqual(u.resolve_latest(self.fetch)["tag"], "release-2027-spring")

    def test_official_latest_policy_not_lexicographic_sort(self):
        self.release["tag_name"] = "v6.10"
        self.assertEqual(u.resolve_latest(self.fetch)["tag"], "v6.10")
        self.assertEqual(self.requests[0], u.LATEST_URL)

    def test_draft_rejected(self):
        self.release["draft"] = True
        with self.assertRaises(u.UpstreamError):
            u.resolve_latest(self.fetch)

    def test_prerelease_rejected(self):
        self.release["prerelease"] = True
        with self.assertRaises(u.UpstreamError):
            u.resolve_latest(self.fetch)

    def test_unpublished_rejected(self):
        self.release["published_at"] = None
        with self.assertRaises(u.UpstreamError):
            u.resolve_latest(self.fetch)

    def test_control_characters_rejected(self):
        self.release["tag_name"] = "v6.7\nfake=value"
        with self.assertRaises(u.UpstreamError):
            u.resolve_latest(self.fetch)

    def test_asset_renamed_still_works(self):
        self.asset["name"] = "Nova_Universal.APK"
        self.assertEqual(u.resolve_latest(self.fetch)["asset_id"], 701)

    def test_no_universal_rejected(self):
        self.asset["name"] = "nova-arm64-release.apk"
        with self.assertRaisesRegex(u.UpstreamError, "No older-version fallback"):
            u.resolve_latest(self.fetch)
        self.assertEqual(len(self.requests), 2)

    def test_ambiguous_assets_rejected(self):
        with self.assertRaises(u.UpstreamError):
            u.select_asset([self.asset, dict(self.asset, id=702)])

    def test_debug_universal_not_chosen(self):
        debug = dict(self.asset, id=702, name="nova-universal-debug.apk")
        self.assertEqual(u.select_asset([debug, self.asset])["id"], 701)

    def test_incomplete_upload_rejected(self):
        self.asset["state"] = "new"
        with self.assertRaises(u.UpstreamError):
            u.resolve_latest(self.fetch)

    def test_digest_missing_rejected(self):
        self.asset["digest"] = None
        with self.assertRaisesRegex(u.UpstreamError, "SHA-256"):
            u.resolve_latest(self.fetch)

    def test_digest_wrong_algorithm_rejected(self):
        self.asset["digest"] = "md5:" + "a" * 32
        with self.assertRaises(u.UpstreamError):
            u.resolve_latest(self.fetch)

    def test_foreign_download_host_rejected(self):
        self.asset["browser_download_url"] = "https://example.com/nova.apk"
        with self.assertRaises(u.UpstreamError):
            u.resolve_latest(self.fetch)

    def test_foreign_repository_rejected(self):
        self.asset["browser_download_url"] = "https://github.com/other/repo/releases/download/v6.7/nova.apk"
        with self.assertRaises(u.UpstreamError):
            u.resolve_latest(self.fetch)

    def test_http_download_rejected(self):
        self.asset["browser_download_url"] = self.asset["browser_download_url"].replace("https:", "http:")
        with self.assertRaises(u.UpstreamError):
            u.resolve_latest(self.fetch)

    def test_paginated_assets(self):
        def fetch(url):
            if url == u.LATEST_URL:
                return self.release
            if url.endswith("page=1"):
                return [{"name": f"non-apk-{i}.txt"} for i in range(100)]
            if url.endswith("page=2"):
                return [self.asset]
            raise AssertionError(url)
        self.assertEqual(u.resolve_latest(fetch)["asset_id"], 701)

    def test_corrupt_asset_list_rejected(self):
        with self.assertRaises(u.UpstreamError):
            u.select_asset([None])

    def test_valid_download_becomes_actual_build_input(self):
        result = self.download()
        self.assertEqual(self.apk.read_bytes(), self.payload)
        self.assertEqual(result["status"], "DOWNLOADED_AND_VERIFIED")
        self.assertEqual(json.loads(self.metadata.read_text())["downloaded_sha256"], self.digest)
        self.assertEqual(list(self.apk.parent.glob("*.part")), [])

    def test_download_sha_mismatch_no_stale_output(self):
        self.asset["digest"] = "sha256:" + "0" * 64
        self.apk.parent.mkdir(parents=True)
        self.apk.write_bytes(b"old version")
        with self.assertRaisesRegex(u.UpstreamError, "SHA-256"):
            self.download()
        self.assertFalse(self.apk.exists())
        self.assertEqual(json.loads(self.metadata.read_text())["status"], "DOWNLOAD_FAILED")
        self.assertEqual(list(self.apk.parent.glob("*.part")), [])

    def test_download_size_mismatch(self):
        self.asset["size"] += 1
        with self.assertRaisesRegex(u.UpstreamError, "size"):
            self.download()
        self.assertFalse(self.apk.exists())

    def test_network_failure_removes_old_input(self):
        self.apk.parent.mkdir(parents=True)
        self.apk.write_bytes(b"old")
        self.metadata.write_text('{"stale": true}')
        def fail(_):
            raise u.UpstreamError("network unavailable")
        with self.assertRaises(u.UpstreamError):
            u.download_latest(self.apk, self.metadata, fetch_json=fail)
        self.assertFalse(self.apk.exists())
        self.assertFalse(self.metadata.exists())

    def test_download_failure_no_fallback(self):
        def fail(*_):
            raise u.UpstreamError("download unavailable")
        with self.assertRaises(u.UpstreamError):
            u.download_latest(self.apk, self.metadata, fetch_json=self.fetch, downloader=fail)
        self.assertFalse(self.apk.exists())
        self.assertEqual(list(self.apk.parent.glob("*.part")), [])

    def test_valid_digest_but_invalid_zip_rejected(self):
        self.payload = b"not an apk"
        self.asset["size"] = len(self.payload)
        self.asset["digest"] = "sha256:" + hashlib.sha256(self.payload).hexdigest()
        with self.assertRaisesRegex(u.UpstreamError, "valid APK"):
            self.download()

    def test_non_apk_zip_rejected(self):
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("hello.txt", b"hello")
        self.payload = out.getvalue()
        self.asset["size"] = len(self.payload)
        self.asset["digest"] = "sha256:" + hashlib.sha256(self.payload).hexdigest()
        with self.assertRaisesRegex(u.UpstreamError, "complete Android APK"):
            self.download()

    def test_approved_digest_passes_separate_gate(self):
        self.download()
        self.baseline.write_text(json.dumps({"upstream_sha256": self.digest}))
        u.compatibility_gate(self.apk, self.metadata, self.baseline, self.report)
        self.assertEqual(json.loads(self.report.read_text())["status"], "APPROVED_TESTED_BINARY_BASE")

    def test_unported_latest_downloads_then_blocks(self):
        self.download()
        self.baseline.write_text(json.dumps({"upstream_sha256": "a" * 64}))
        with self.assertRaisesRegex(u.UpstreamError, "not verified"):
            u.compatibility_gate(self.apk, self.metadata, self.baseline, self.report)
        self.assertEqual(self.apk.read_bytes(), self.payload)
        report = json.loads(self.report.read_text())
        self.assertEqual(report["status"], "BLOCKED_UNPORTED_UPSTREAM")
        self.assertFalse(report["old_version_fallback"])

    def test_metadata_cannot_bypass_digest_check(self):
        self.download()
        self.apk.write_bytes(b"modified after download")
        with self.assertRaises(u.UpstreamError):
            u.load_selection(self.metadata, self.apk)

    def test_wrong_provenance_rejected(self):
        self.download()
        data = json.loads(self.metadata.read_text())
        data["repository"] = "wrong/repo"
        self.metadata.write_text(json.dumps(data))
        with self.assertRaises(u.UpstreamError):
            u.load_selection(self.metadata, self.apk)

    def test_selected_status_without_download_rejected(self):
        self.download()
        data = json.loads(self.metadata.read_text())
        data["status"] = "SELECTED"
        self.metadata.write_text(json.dumps(data))
        with self.assertRaises(u.UpstreamError):
            u.load_selection(self.metadata, self.apk)

    def test_latest_unchanged_before_publish(self):
        self.download()
        u.assert_current(self.apk, self.metadata, fetch_json=self.fetch)

    def test_latest_changed_before_publish_rejected(self):
        self.download()
        self.release["tag_name"] = "v6.8"
        with self.assertRaisesRegex(u.UpstreamError, "changed during"):
            u.assert_current(self.apk, self.metadata, fetch_json=self.fetch)

    def test_same_tag_asset_replaced_rejected(self):
        self.download()
        self.asset["id"] = 702
        with self.assertRaises(u.UpstreamError):
            u.assert_current(self.apk, self.metadata, fetch_json=self.fetch)

    def test_same_asset_new_digest_rejected(self):
        self.download()
        self.asset["digest"] = "sha256:" + "0" * 64
        with self.assertRaises(u.UpstreamError):
            u.assert_current(self.apk, self.metadata, fetch_json=self.fetch)

    def test_output_metadata_path_conflict_rejected(self):
        with self.assertRaises(u.UpstreamError):
            u.download_latest(self.apk, self.apk, fetch_json=self.fetch, downloader=self.downloader)

    def test_cli_bad_metadata_returns_failure(self):
        p = subprocess.run([sys.executable, str(ROOT / "scripts/check_upstream.py"), "guard",
                            "--apk", str(self.apk), "--metadata", str(self.metadata)],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        self.assertIn("::error::", p.stderr)

    def test_workflow_single_fixed_name(self):
        paths = list((ROOT / ".github/workflows").glob("*.yml"))
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].read_text().startswith("name: Nova Video Player mod\n"))

    def test_workflow_has_no_pinned_download(self):
        content = (ROOT / ".github/workflows/nova-video-player-mod.yml").read_text()
        self.assertNotIn("/releases/download/v6.5.5", content)
        self.assertNotIn("latest-upstream.apk", content)
        self.assertNotIn("continue-on-error", content)
        self.assertIn("download --apk inputs/official.apk", content)
        self.assertIn("build.py build inputs/official.apk", content)
        self.assertLess(content.index("check_upstream.py guard"), content.index("build.py build"))
        self.assertLess(content.index("assert-current"), content.index("gh release create"))


    def test_ci_branch_cannot_publish(self):
        content = (ROOT / ".github/workflows/nova-video-player-mod.yml").read_text()
        self.assertIn("branches: [main, 'ci/**']", content)
        self.assertIn("if: github.ref == 'refs/heads/main' && github.event_name != 'schedule'", content)

    def test_original_signature_checked_before_overlay(self):
        content = (ROOT / ".github/workflows/nova-video-player-mod.yml").read_text()
        self.assertLess(content.index('verify --verbose --print-certs inputs/official.apk'),
                        content.index('build.py build inputs/official.apk'))

    def test_temporary_key_cleanup_and_signing_mode_recorded(self):
        content = (ROOT / ".github/workflows/nova-video-player-mod.yml").read_text()
        self.assertIn("trap 'rm -f \"$STORE\"' EXIT", content)
        self.assertIn('SIGNING_MODE=temporary-test-key', content)
        self.assertIn('inputs/signing.json', content)
        self.assertNotIn('path: $RUNNER_TEMP', content)

    def test_rerun_release_tags_are_distinct(self):
        content = (ROOT / ".github/workflows/nova-video-player-mod.yml").read_text()
        self.assertIn('${GITHUB_RUN_NUMBER}-${GITHUB_RUN_ATTEMPT}', content)


if __name__ == "__main__":
    unittest.main()
