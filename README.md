# Nova Video Player — V7.11 UI Overlay

The **only maintained code version** in this repository is the Nova TV V7.11 UI adaptation. No old APKs, earlier version scripts, copied upstream source, or signing keys live on `main`.

- `ui/apply.py`: readable, fail-closed Java/XML source-only UI changes.
- `upstream/locked.xml`: immutable commit IDs for all 21 repositories in official Nova 6.5.5 multi-repo manifest.
- `.github/workflows/build-release.yml`: fetch official source → apply UI modifications → build Android APK → sign → publish exactly one asset named **`Nova Video Player.apk`** in one rolling Release named `current`.
- `tests/test_overlay.py`, `scripts/verify_apk.py`: sanity checks.

[中文说明与签名配置](README_CN.md)

The previously user-tested APK is an **already-signed patched binary**. The Java/XML overlay is intended to reproduce the same UI and behavior from official source, not to guarantee a byte-identical APK: dex ordering, Gradle toolchains, and especially signing keys affect bytes. A new signing key **cannot** install as an upgrade over the already-signed V7.11 APK; uninstall the old APK first (back up app data if needed). Full cloud build and device smoke-test results must be checked before claiming parity.

**Upstream:** <https://github.com/nova-video-player/aos-AVP> (Apache-2.0). This repository contains modifications only. The original repositories, copyright notices and licenses remain upstream.
