# Nova Video Player — V7.14 14TV Fix + V7.11 UI Overlay

The **only maintained code version** in this repository is the Nova TV V7.14 14TV fix and approved V7.11 UI adaptation. No old APKs, earlier version scripts, copied upstream source, or signing keys live on `main`.

- `ui/apply.py`: readable, fail-closed Java/XML source-only UI changes.
- `upstream/locked.xml`: immutable commit IDs for all 21 repositories in official Nova 6.5.5 multi-repo manifest.
- `.github/workflows/build-release.yml`: fetch official source → apply UI modifications → build Android APK → sign → publish exactly one asset named **`Nova Video Player.apk`** in one rolling Release named `current`.
- `tests/test_overlay.py`, `scripts/verify_apk.py`: sanity checks.

[中文说明与签名配置](README_CN.md)

The previously user-tested APK is an **already-signed patched binary**. The Java/XML overlay is intended to reproduce the same UI and behavior from official source, not to guarantee a byte-identical APK: dex ordering, Gradle toolchains, and especially signing keys affect bytes. A new signing key **cannot** install as an upgrade over the already-signed V7.11 APK; uninstall the old APK first (back up app data if needed). Full cloud build and device smoke-test results must be checked before claiming parity.

**Upstream:** <https://github.com/nova-video-player/aos-AVP> (Apache-2.0). This repository contains modifications only. The original repositories, copyright notices and licenses remain upstream.

## V7.14 validated local binary (2026-10-13)

User confirmed that the standalone V7.14 patched APK works on their 14TV. Its verified SHA-256 is `c9977d28e57b6a58e2f4d09da959a1b41db2028020d3175facfe792e108e77ff`. The exact reproducible binary patch is saved in `scripts/v714_patch_dex.py` and reproduces the original unsigned patched APK from strictly SHA-pinned V7.13. It requires the original signing certificate for an installable update. The Java source overlay instead implements equivalent initialization behavior with `HEADERS_DISABLED` before view creation, plus deferred Rows focus; a source rebuilt APK is **not** byte-identical to the already-tested local APK, and still requires separate device validation.
