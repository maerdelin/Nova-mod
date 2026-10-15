# Nova Video Player mod

## Dynamic official Latest selection

The only workflow is **Nova Video Player mod**. Manual runs, main-branch pushes,
CI branch pushes (`ci/**`), and daily scheduled runs query the official
repository's
`GET /repos/nova-video-player/aos-AVP/releases/latest` endpoint.
"Latest" means the official GitHub Latest stable release, not the largest tag
string, the latest commit, or a prerelease. No version number is hard-coded in
release selection, and no three-component version regex is used.

The workflow resolves the release first, enumerates its release assets, selects
exactly one universal APK, downloads it to `inputs/official.apk`, and verifies
its size, official GitHub asset SHA-256, ZIP integrity, and required APK entries.
There is no search for an older APK when the latest asset is missing or fails.
The build command consumes that same `inputs/official.apk`.

The original downloaded APK signature is checked with Android apksigner before
applying the overlay. The finished APK is zipaligned, signed, checked with
apksigner, and its functional entries are verified against the saved manifest.

The official release/asset identity is checked again after signing and before
publishing. A release or asset change stops publication and requires a new run.
This is a point-in-time check; it is not a claim that upstream can never change
immediately after the check.

## Important: selection is not automatic cross-version patching

The saved overlay in `baseline/parts/` is still the existing V9.8.2 binary
baseline. Its recorded test package is
`Nova_V9_8_2_WebDAV_TVList_VerifyErrorFix_TEST.apk`.

The compatibility gate intentionally accepts only the exact upstream SHA-256
already recorded in `baseline/manifest.json`. A newly downloaded upstream with
a different hash stops with `BLOCKED_UNPORTED_UPSTREAM`. It is not automatically
approved just because a version tag is newer, and the previous stable release
is not replaced on this failure.

**For a future official v6.7, the new script selects and downloads v6.7 when the
official Latest endpoint points to it. With the current saved binary overlay,
that new APK is expected to stop at the compatibility gate until the actual
patches have been ported and tested.** This update does not contain a general
DEX/resource patch-porting engine. Never update a digest merely to bypass the
gate, and never cover a new DEX with an old DEX and call that an upstream upgrade.

`build.py`, `baseline/manifest.json`, and all binary fragments are retained.
This remains APK binary reconstruction, not Java/Kotlin/Gradle source compilation.

## Signing, outputs, and release retention

The existing signing-secret names are retained: `NOVA_KEYSTORE_BASE64`,
`NOVA_STORE_PASSWORD`, `NOVA_KEY_ALIAS`, and `NOVA_KEY_PASSWORD`.
With none configured, the existing temporary-test-key behavior is retained;
a new certificate cannot update an installation signed with a different key.
The signing mode is recorded in the run summary, report artifact, and release
notes. No private key is uploaded to the repository or any artifact.

A successful build produces one APK, `Nova_Video_Player_mod.apk`, plus a checksum
file. The release title includes the dynamically selected official tag. As
before, scheduled runs do not publish releases. CI branches never publish or
clean up releases. Successful non-scheduled main-branch runs publish and keep the latest three non-draft releases; failed runs do not reach
release creation or cleanup. The existing cleanup policy deletes older releases
and their tags only after a new release is created.

Selection and compatibility JSON reports are retained as Actions artifacts,
including when a newly downloaded upstream is blocked. Static checks are not
Android-device runtime tests.

## Local tests

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
```

The tests use mock API replies and synthetic APK ZIPs. They cover flexible tags,
stable-release validation, asset ambiguity, pagination, official digest checks,
no stale-input fallback, compatibility failures, and pre-publish freshness.
