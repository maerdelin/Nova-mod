# Nova Video Player mod

## Install the correct file
Only `Nova_Video_Player_mod_SIGNED.apk` in the **Nova-installable-signed** artifact or Release is intended for installation. The former `Nova-granular-analysis/modified.apk` was an **UNSIGNED intermediate reference**, not an installer. Reports and diff files are not applications.

The pipeline now requires signing, signature verification, ZIP alignment, and a real clean installation on an Android 11 x86_64 CI emulator. Both normal and Leanback launcher entry points must stay running for the startup checks. This does not replace WebDAV/SMB/playback or user-device testing.

## Granular patches, not old modules
The upstream selector queries the official Latest stable release dynamically, downloads its universal APK, and validates its official asset digest and APK signature. The downloaded APK is the actual input.

`scripts/granular.py` applies instruction hunks, field declarations and XML-property operations. The reviewed 6.5.5-to-V9.8.2 delta contains 110 hunks in 40 methods across 26 classes, 2 field changes and 37 XML operations in 11 files. NOP padding, formatting, label spelling and resource number allocation are not treated as feature patches.

`patches/v982-granular.json` stores the rules. During the initial test-branch build only, the rule file is extracted from the known official reference and saved V9.8.2 baseline and is versioned after the signed APK passes installation/startup tests. Existing baseline binary fragments are retained for archival/reference verification, not copied into the new candidate's DEX or modules.

New upstream versions are no longer blocked solely because the entire APK digest differs. Patch contexts, symbols, registers, dependencies and XML identities must match. Unrelated changes remain in place. A conflicting/ambiguous operation stops the build, without an old-version fallback. No guarantee of automatic compatibility with every future upstream version is made.

After assembly the candidate is decoded again and compared for instruction/control-flow/XML consistency; native libraries and assets must remain equal to the selected official APK. These are specified checks, not a proof of whole-program equivalence.

## Signing
Configure `NOVA_KEYSTORE_BASE64`, `NOVA_STORE_PASSWORD`, `NOVA_KEY_ALIAS` and `NOVA_KEY_PASSWORD` for a persistent private signing key. Without them a temporary TEST key is used and destroyed after signing. A test-signed APK cannot update an installation signed with another certificate. Back up application data before any uninstall; this workflow never removes data from your device.

## Workflow
One workflow, always named **Nova Video Player mod**. Daily, manual and main/ci branch push triggers. Only successful main (non-scheduled) runs publish a Release. The latest three managed Releases are retained. Test-branch artifacts are distinct from stable Releases.
