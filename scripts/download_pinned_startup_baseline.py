#!/usr/bin/env python3
"""Build from precisely the tested main-compatible v6.5.5 APK, verified by SHA256."""
from pathlib import Path
import check_upstream as upstream
BASE={
 "schema_version":1,"policy":"github-official-latest-stable",
 "repository":"nova-video-player/aos-AVP",
 "release_id":408256428,"tag":"v6.5.5","published_at":"2026-10-09T19:19:45Z",
 "asset_id":625921451,
 "asset_name":"org.courville.nova-2672099-6.5.5-20261009.2113-universal-release.apk",
 "download_url":"https://github.com/nova-video-player/aos-AVP/releases/download/v6.5.5/org.courville.nova-2672099-6.5.5-20261009.2113-universal-release.apk",
 "official_sha256":"f252631680328916ed847c8c0d6711d6a9922373e54f939178c428a9b3c3e1a5",
 "size_bytes":84480195,"selection_endpoint":"https://api.github.com/repos/nova-video-player/aos-AVP/releases/408256428",
 "pinned_baseline_run":780,"pinned_only_on_independent_branch":True}
apk=Path("inputs/official.apk")
meta=Path("inputs/upstream.json")
apk.parent.mkdir(parents=True,exist_ok=True)
apk.unlink(missing_ok=True)
meta.unlink(missing_ok=True)
upstream.download_file(BASE["download_url"],apk)
digest=upstream.validate_apk(apk,BASE)
BASE["downloaded_sha256"]=digest
BASE["status"]="DOWNLOADED_AND_VERIFIED"
upstream.write_json(meta,BASE)
upstream.action_outputs(tag=BASE["tag"],release_id=BASE["release_id"],asset_id=BASE["asset_id"],sha256=digest)
print("PINNED_MAIN_BASE_SHA256_OK="+digest)
