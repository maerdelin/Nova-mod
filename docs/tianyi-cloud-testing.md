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
