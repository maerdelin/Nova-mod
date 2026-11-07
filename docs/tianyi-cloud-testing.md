# NOVA 6.6.4 Tianyi Cloud integration - test gate

GitHub Actions build Run 42176822312 produced a signed installation candidate on 2026-11-06. The artifact is named NOVA-Tianyi-Cloud-TEST-SIGNED. Apktool repack, Java / DEX compilation, zipalign, apksigner and SHA-256 checks passed. The signing mode was temporary-test-key, because the repository signing secrets were not configured; it cannot update a different-signed installation without uninstalling. Back up user data and use a disposable Android test device.

Code reference: OpenListTeam/OpenList v4.2.9 drivers/189pc. The implementation uses the 189CloudPC QR code authentication challenge, Authorization state polling, AccessToken/RefreshToken exchange and persistence, PC session refresh, 5 minute keep-alive and root folder -11. It embeds a local read-only loopback DAV at 127.0.0.1:27989 using a high-entropy per-installation URL path. The original NOVA WebDAV browsing and Range-reading paths consume this local URL. No separately installed OpenList or router is needed.

Actual MOD protocol display order is WebDAV, SMB, Tianyi Cloud, FTP, SFTP, FTPS, SSHJ, SMBJ, WebDAVS. This is deliberately different from upstream vanilla NOVA resources. The patch preserves all eight legacy protocol IDs.

Acceptance still required on an authorized Tianyi account:
1. Add Tianyi protocol, see a live QR code only on the right, scan with Tianyi app and confirm on phone.
2. Verify automatic shortcut creation and open personal root and nested folders including Chinese filenames.
3. Test 1000+ entry folders, MP4, MKV, TS, ISO, Range reads, seek, exit and repeated playback.
4. Restart NOVA and Android, check token recovery, keep-alive, revoked token and QR expiration handling.
5. Verify existing WebDAV, SMB, FTP, SFTP, SMBJ etc. are unaffected and that logs contain no session token.

This is a first read-only functional candidate, NOT yet user-validated. Android may suspend idle background timers; wake-up restores session on demand. Cloud-side revocation, API changes or anti-abuse checks can still force QR reauthorization. Never present the result as proof of permanently valid login.

Workflow: .github/workflows/tianyi-build.yml
Source: tianyi/src/com/archos/mediacenter/video/cloud189
Patch: tianyi/patch_apk.py

Keep main and Always-new unchanged until physical-device acceptance.

## 2026-11-06 QR disappearance fix and independent verification

- **Root cause of the visible flash/disappearance**: QR code was rendered successfully; a subsequent AndroidKeyStore `verifyCrypto()` failure invoked `TianyiUi.showError()`, deliberately hiding the QR bitmap. OpenList has no such Android-only preflight dependency.
- `TianyiStore`: AES-GCM encryption now uses the **provider-generated IV**, not a caller-provided nonce, and the corresponding IV is stored with ciphertext. The read path continues authenticating using AES-GCM and application-specific AAD. Self-test reports sanitized failing phases.
- `TianyiCloud`: run encrypted-storage preflight **before** displaying the QR; never show a transient QR that will be immediately removed due to local key initialization failure.
- `TianyiUi`: preserve a displayed QR image when subsequent authorization/poll/network errors occur; retry and diagnostic UI remain available.
- **Live Android 14 emulator UI test Run 42193871328**: dynamically fetched real provider UUID and displayed QR still present at 20 seconds, PASS.
- **Live Android 14 emulator UI test Run 42195183235**, built from corrected driver Run 42194377767: QR still visible at both **20 and 60 seconds**, no visible error, PASS. Actual screenshots saved with the GitHub Actions artifact `NOVA-Tianyi-Real-QR-UI-test`.
- **OpenList driver parity correction**: In `OpenListTeam/OpenList v4.2.9 drivers/189pc/utils.go`, `getFilesWithPage` and `driver.go Link` call `y.get(fullURL, callback)` with callback-set **plain query parameters**, not `y.request(..., params)` that would encrypt a `params` field. Removed the incorrect encryption of directory/list link query parameters. Signed headers continue to use HMAC-SHA1, without an encrypted `params` item for these requests.
- **Still unverified**: a user completing real mobile QR approval and exchanging the tokens, automatic `ShortcutDb` insertion + refresh, local DAV `PROPFIND/GET/HEAD/Range` on an authorized account, and token refresh after long elapsed time. Do not distribute the result as a finished, fully working release, and keep `main`/`Always-new` untouched.
