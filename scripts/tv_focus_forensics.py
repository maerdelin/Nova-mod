#!/usr/bin/env python3
"""Dump original/modified TV layout smali and XML for first-focus forensic review."""
from pathlib import Path
import argparse,json,re,sys

def one_section(src, signature):
    token=".method "+signature
    hits=src.count(token)
    if hits!=1: return f"<section missing / ambiguous {signature}: {hits}>\n"
    i=src.index(token);j=src.index(".end method",i)+len(".end method")
    return src[i:j]+"\n"

def collect(root, out, label):
    files=[]
    for p in root.glob("smali*/**/*.smali"):
        if p.name in {"TVCardView.smali","TVMenuAdapter.smali","PlayerActivity.smali",
                      "TVMenu.smali","TVCardView$ExpandAnimation.smali",
                      "TVCardView$ResizeAnimation.smali"} or p.name.startswith("TVCardView$"):
            files.append(p)
    found={}
    for p in sorted(files):
        content=p.read_text(errors="replace")
        if p.name=="PlayerActivity.smali":
            body="\n".join(one_section(content,m) for m in
                          ("public createPlayerTVMenu()V",
                           "private createPlayerTVMenu()V"))
        else:
            body=content
        dst=out/label/(p.name+".txt")
        dst.parent.mkdir(parents=True,exist_ok=True)
        dst.write_text(body)
        found[p.name]={"lines":len(body.splitlines()),"path":str(p.relative_to(root))}
    for p in sorted(root.glob("res/layout*/**/*.xml")):
        if any(t in p.name.lower() for t in ("card", "tv_menu", "tvmenu", "subtitle", "player")):
            dest=out/label/"xml"/(p.parent.name+"__"+p.name)
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(p.read_bytes())
    return found

def main():
    a=argparse.ArgumentParser()
    a.add_argument("root",type=Path)
    a.add_argument("out",type=Path)
    args=a.parse_args()
    original=collect(args.root,args.out,"original")
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    import tv_track_width_patch, tv_small_card_spacing_patch
    tv_track_width_patch.apply(args.root,args.out/"wide.json")
    tv_small_card_spacing_patch.apply(args.root,args.out/"spacing.json")
    patched=collect(args.root,args.out,"patched")
    (args.out/"manifest.json").write_text(json.dumps(
       {"original":original,"patched":patched},ensure_ascii=False,indent=2)+"\n")
    assert original.keys()==patched.keys()
    assert "TVCardView.smali" in original
    assert "TVCardView$ExpandAnimation.smali" in original
    assert "TVMenuAdapter.smali" in original
    print("NOVA_TV_POPUP_ORIGINAL_AND_PATCHED_SMALI_AUDITED",json.dumps(original))

if __name__=="__main__":main()
