#!/usr/bin/env python3
"""Inspect only TV audio/subtitle popup smali; avoid touching successful 714."""
from pathlib import Path
import re,sys
root=Path(sys.argv[1])
targets={
 "PlayerActivity.smali":[r"createPlayerTVMenu",r"mSubtitleTVCardView",r"mAudioTracksTVCardView"],
 "TVCardView.smali":[r"\.method public focus\(Z\)V",r"ExpandAnimation"],
 "TVMenuAdapter.smali":[r"createAndAddView"],
}
for name,needles in targets.items():
    found=list(root.glob("smali*/**/"+name))
    if not found: raise SystemExit(f"TV_WIDTH_AUDIT: missing {name}")
    path=found[0]; data=path.read_text();lines=data.splitlines()
    print(f"TV_WIDTH_AUDIT_FILE {name} {path} total={len(lines)}")
    points=[i for i,line in enumerate(lines) if any(re.search(p,line) for p in needles)]
    # Enough source to identify .locals and all affected registers without dumping APK.
    cap=24 if name=="TVCardView.smali" else 12
    windows=set()
    for i in points[:35]:
        for j in range(max(0,i-cap),min(len(lines),i+cap+1)):windows.add(j)
    last=-2
    for i in sorted(windows):
        if i>last+1:print("TV_WIDTH_AUDIT_GAP ...")
        print(f"TV_WIDTH_AUDIT {name}:{i+1}: {lines[i]}")
        last=i
print("TV_WIDTH_AUDIT_PASS")
