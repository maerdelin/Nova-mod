# Nova V7.14 — Exact verified 14TV release baseline

Read [README_CN.md](README_CN.md).

This clean branch contains the **reproducible rebuild implementation** for the original user-tested 29,767,890-byte Nova V7.14 ARM32 APK, not an unverified source-level approximation. Download the pinned official Nova 6.5.5 ARM32 release, replay the fully pinned DEX, resource, layout and signing modifications with `scripts/v714_exact.py`, then SHA-256-verify the entire reconstructed APK against `c9977d28e57b6a58e2f4d09da959a1b41db2028020d3175facfe792e108e77ff`.

GitHub Actions checks exact byte identity and signature before publishing one APK to Release `current`. A rebuilt **x86 or universal APK is not yet verified** and is never mislabeled as equivalent to the tested ARM32 file. APK patch/reconstruction source here is reproducible, but APKs cannot yield their original handwritten Java source losslessly. Official source revisions remain pinned in `upstream/locked.xml`.
