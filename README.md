# Nova V7.14 V6 — User-verified network centering (current `main`)

**Current user-verified baseline:** `Nova_V7_14_Network_Only_Centered_v6_ResourceExactCenter_TEST.apk`

- Full APK SHA-256 (exact user's tested APK): `957819f313352ff54adcaac9000037d082e2f42a5823e03f5e3eb6dffb344d6d`
- `classes.dex` SHA-256: `1f0194f96282bc3494e0ed17505a52d2cd552782cee5d534584480058b836e38`
- Verified by the user on BlueStacks, 2026-10-14: three centered TV home cards, dynamically centered network-storage tiles, and Android TV/phone-tablet AutoMode.
- Native network tile dimensions: 210dp width, 16dp inter-card spacing, 56dp left/right row inset; the runtime network-only container width is `226*N+96` dp, clamped to display width for horizontal scrolling.
- The TV home layout `res/Am.xml` and common Leanback row layout `res/mC.xml` are SHA-pinned and never modified by this V6 network-centering patch.

## Default GitHub Actions build

The only active build workflow, [`.github/workflows/v714-exact.yml`](.github/workflows/v714-exact.yml), **now builds V6**, not the older AutoMode-only artifact. It downloads pinned official Nova 6.5.5 and the pinned 3-card V7.14 ARM32 source, reconstructs the four-ABI Universal base, applies the R16 AutoMode and V6 network-only patches in sequence, zipaligns/signs, and verifies the **signed** APK's exact V6 DEX hash and preserved home resources.

Run `python3 scripts/build_universal.py merge <arm32.apk> <official-universal.apk> <unsigned-v6.apk>` followed by `verify` with the same three paths to reproduce the unsigned content. The network-only DEX patch is defined by [`scripts/network_center_v6.py`](scripts/network_center_v6.py). This is reproducible binary reconstruction, **not** a claim to have the original handwritten Java/Kotlin sources.

**Signing caveat:** Without repository signing secrets, each CI run uses a new temporary certificate. The functional file hashes match the user-tested V6, but the *whole newly signed APK* will not have the same hash or be install-upgradable over a differently signed APK. Preserve user data before replacing signatures. Old versions remain in Git history for rollback, but `main` and its default workflow point to V6.

See [README_CN.md](README_CN.md) for Chinese notes.
