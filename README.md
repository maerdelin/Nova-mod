# Nova Video Player mod

## Install the correct file
Only `Nova_Video_Player_mod_SIGNED.apk` in the **Nova-installable-signed** artifact or Release is intended for installation. The former `Nova-granular-analysis/modified.apk` was an **UNSIGNED intermediate reference**, not an installer. Reports and diff files are not applications.

The pipeline now requires signing, signature verification, ZIP alignment, and a real clean installation on an Android 11 x86_64 CI emulator. Both normal and Leanback launcher entry points must stay running for the startup checks. This does not replace WebDAV/SMB/playback or user-device testing.

## Granular patches, not old modules
The upstream selector queries the official Latest stable release dynamically, downloads its universal APK, and validates its official asset digest and APK signature. The downloaded APK is the actual input.

`scripts/granular.py` applies instruction hunks, field declarations and XML-property operations. The reviewed 6.5.5-to-V9.8.2 delta contains 110 hunks in 40 methods across 26 classes, 2 field changes and 37 XML operations in 11 files. NOP padding, formatting, label spelling and resource number allocation are not treated as feature patches.

`patches/v982-granular.json` stores the rules. During the initial test-branch build only, the rule file is extracted from the known official reference and saved V9.8.2 baseline and is versioned after the signed APK passes installation/startup tests. Existing baseline binary fragments are retained for archival/reference verification, not copied into the new candidate's DEX or modules.

New upstream versions are no longer blocked solely because the entire APK digest differs. Patch contexts, symbols, registers, dependencies and XML identities must match. Unrelated changes remain in place. A conflicting/ambiguous operation stops the build, without an old-version fallback. No guarantee of automatic compatibility with every future upstream version is made.

After assembly the candidate is decoded again and checked for instruction/control-flow/XML consistency. **Exception for native AVOS buffering:** the pipeline recompiles only `libavos.so` from pinned `aos-avos` source with narrowly anchored C patches, once for each official ABI; it does **not** copy an old-version binary. `scripts/granular_build.py` refuses changes to other native libraries or assets, checks that every expected `libavos.so` changed, and verifies round-trip content. These are scoped integrity checks, not proof of whole-program equivalence.

## Tested Run376 functional baseline

Run376, commit `9fe107d1bdb1474a135a12253746b04cf48fd0a3`, is the baseline for the functionality promoted to `main`.

- Preserve upstream official stable APK as input. Apply the reviewed `patches/v982-granular.json` instruction/field/XML operations with exact context checks; avoid wholesale old DEX/class/module overlays. Additional Java/Smali edits are localized, anchor-checked patches rather than copying archived classes.
- Preserve targeted audio routing and buffering guards, WebDAV transfer buffer/throughput tuning, connection-establishment retries, interrupted-body byte-accurate WebDAV resume, and terminal-error safe exit.
- Cold-start WebDAV credential loading is a **strictly hash-checked, in-place DEX instruction patch** in `scripts/webdav_credential_coldboot_patch.py`; it does not replace the candidate with an archived DEX. An unexpected upstream DEX/method layout stops the build instead of applying an unsafe patch.
- Native AVOS: parser-queue rebuffering with 2X low / 5X resume / 10X capacity based on average file bitrate X; 24/64/128 MiB fallback if reliable input is unavailable; conservative TS bitrate detection; and narrowly scoped invalid saved-position startup fallback for TS (play from beginning instead of fatal seek).
- For TS bookmark fallback, valid position seeks, seek requests after initial playback, MP4/MKV, and unrelated media errors are unaffected. `NOVA_TS_RESUME_FALLBACK` is the runtime diagnostic.
- Source patches are pinned to a reviewed upstream AVOS commit and fail closed on missing/duplicate anchors. The only native payload exception is freshly built `libavos.so` for the four supported ABIs. Other `lib/*` and `assets/*` bytes must match the freshly selected official APK. Signing, alignment, emulator installation/startup, and upload remain CI gates.

The branch acceptance tests and Android 11 installation/startup smoke test do **not** prove every WebDAV/TS resume case on physical devices. Use the generated log tags to confirm those cases in actual playback.

## Signing
Configure `NOVA_KEYSTORE_BASE64`, `NOVA_STORE_PASSWORD`, `NOVA_KEY_ALIAS` and `NOVA_KEY_PASSWORD` for a persistent private signing key. Without them a temporary TEST key is used and destroyed after signing. A test-signed APK cannot update an installation signed with another certificate. Back up application data before any uninstall; this workflow never removes data from your device.

## Workflow
One workflow, always named **Nova Video Player mod**. Daily, manual and main/ci branch push triggers. Only successful main (non-scheduled) runs publish a Release. The latest three managed Releases are retained. Test-branch artifacts are distinct from stable Releases.
