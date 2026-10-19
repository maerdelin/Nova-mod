# Nova Video Player mod

## Install the correct file
Only `Nova_Video_Player_mod_SIGNED.apk` in the **Nova-installable-signed** artifact or Release is intended for installation. The former `Nova-granular-analysis/modified.apk` was an **UNSIGNED intermediate reference**, not an installer. Reports and diff files are not applications.

The pipeline now requires signing, signature verification, ZIP alignment, and a real clean installation on an Android 11 x86_64 CI emulator. Both normal and Leanback launcher entry points must stay running for the startup checks. This does not replace WebDAV/SMB/playback or user-device testing.

## Granular patches, not old modules
The upstream selector queries the official Latest stable release dynamically, downloads its universal APK, and validates its official asset digest and APK signature. The downloaded APK is the actual input.

`scripts/granular.py` applies instruction hunks, field declarations and XML-property operations. The reviewed 6.5.5-to-V9.8.2 delta contains 110 hunks in 40 methods across 26 classes, 2 field changes and 37 XML operations in 11 files. NOP padding, formatting, label spelling and resource number allocation are not treated as feature patches.

`patches/v982-granular.json` stores the rules. During the initial test-branch build only, the rule file is extracted from the known official reference and saved V9.8.2 baseline and is versioned after the signed APK passes installation/startup tests. Existing baseline binary fragments are retained for archival/reference verification, not copied into the new candidate's DEX or modules.

New upstream versions are no longer blocked solely because the entire APK digest differs. Patch contexts, symbols, registers, dependencies and XML identities must match. Unrelated changes remain in place. A conflicting/ambiguous operation stops the build, without an old-version fallback. No guarantee of automatic compatibility with every future upstream version is made.

After assembly the candidate is decoded again and checked for instruction/control-flow/XML consistency. **Narrow native exceptions:** the pipeline recompiles `libavos.so` from pinned `aos-avos` source with precisely anchored C patches for each supported ABI, and builds one *new* `libnova_iso.so` bridge per ABI from pinned `libbluray` and ISO C code. It does **not** copy archived old-version binaries. `scripts/granular_build.py` ensures existing `lib/*` and `assets/*` payloads are unchanged except rebuilt `libavos.so`; `scripts/iso_finalize.py` checks that the later ISO overlay preserves all existing native libraries/assets byte for byte and adds exactly the four expected `libnova_iso.so` ELF files. Both phases verify round-trip assembly. These are scoped integrity checks, not proof of whole-program equivalence.

## Tested Run382 functional baseline

Run382, commit `8e6a49d7ca0dbb8b1183f7e0899d252d81e79715`, is the tested functional baseline promoted to `main`. It retains the Run376 native buffering/WebDAV/TS fallback lineage and adds the Run379 Blu-ray ISO streaming integration plus isolated ISO-title-duration-to-X handoff.

- Preserve upstream official stable APK as input. Apply the reviewed `patches/v982-granular.json` instruction/field/XML operations with exact context checks; avoid wholesale old DEX/class/module overlays. Additional Java/Smali edits are localized, anchor-checked patches rather than copying archived classes.
- Preserve targeted audio routing and buffering guards, WebDAV transfer buffer/throughput tuning, connection-establishment retries, interrupted-body byte-accurate WebDAV resume, and terminal-error safe exit.
- Cold-start WebDAV credential loading is a **strictly hash-checked, in-place DEX instruction patch** in `scripts/webdav_credential_coldboot_patch.py`; it does not replace the candidate with an archived DEX. An unexpected upstream DEX/method layout stops the build instead of applying an unsafe patch.
- Native AVOS: parser-queue rebuffering with 2X low / 5X resume / 10X capacity based on average file bitrate X; 24/64/128 MiB fallback if reliable input is unavailable; conservative TS bitrate detection; and narrowly scoped invalid saved-position startup fallback for TS (play from beginning instead of fatal seek).
- For TS bookmark fallback, valid position seeks, seek requests after initial playback, MP4/MKV, and unrelated media errors are unaffected. `NOVA_TS_RESUME_FALLBACK` is the runtime diagnostic.
- Blu-ray ISO `.iso` recognition and main-title selection use a standalone `libbluray` bridge with WebDAV Range reads and a localhost MPEG-TS proxy; `scripts/iso_fast_probe_patch.py` limits duration probing to ISO traffic. The bridge exports validated selected-title duration using `nova_iso_duration_us` for the existing AVOS X/2X/5X/10X buffer calculation, without changing playback/seek timestamps. Unusable title duration retains the existing fallback.
- ISO Smali overlays run **after** the strict hash-checked WebDAV credential in-place DEX patch. `scripts/iso_finalize.py` checks the credential instructions before/after ISO assembly and verifies the assembly round-trip; no archived complete DEX is copied.
- Source patches are pinned to reviewed upstream versions and fail closed on missing/duplicate anchors. The only native changes/additions for four ABIs are rebuilt `libavos.so` and newly built `libnova_iso.so` respectively. Other existing `lib/*` and `assets/*` bytes must remain unchanged. Signing, alignment, emulator installation/startup, and upload remain CI gates.

Run382 passed CI regression, native compilation, APK signing, and Android 11 installation/startup smoke tests. Its ISO bitrate handoff was also observed in a BlueStacks playback log (`NOVA_TS_BITRATE: source=iso-title-metadata` and `NOVA_DYNAMIC_BUFFER: mode=average`). None of these proves all Blu-ray navigation, subtitle display, audio passthrough, WebDAV reconnect, or TS/MKV/ISO streaming cases on physical devices. Use the runtime tags and actual playback logs to validate those cases.

## Signing
Configure `NOVA_KEYSTORE_BASE64`, `NOVA_STORE_PASSWORD`, `NOVA_KEY_ALIAS` and `NOVA_KEY_PASSWORD` for a persistent private signing key. Without them a temporary TEST key is used and destroyed after signing. A test-signed APK cannot update an installation signed with another certificate. Back up application data before any uninstall; this workflow never removes data from your device.

## Workflow
One workflow, always named **Nova Video Player mod**. Daily, manual and main/ci branch push triggers. Only successful main (non-scheduled) runs publish a Release. The latest three managed Releases are retained. Test-branch artifacts are distinct from stable Releases.
