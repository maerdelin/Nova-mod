#!/usr/bin/env python3
"""NOVA 1199: stop constructing first-party Java startup diagnostics in OFF.

Run only after all player/UI Smali patches and the global Android Log wrappers.
Do not disable overlay progress or any network/HTTP/playback method itself.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

MARK="NOVA_1199_JAVA_DIAGNOSTIC_SOURCE_GATE"
CLASS="Lcom/archos/mediacenter/video/NovaGlobalLogs;"
TRACE="Lcom/archos/mediacenter/video/player/NovaLoadingTrace;"

METHOD=re.compile(r"(?ms)^\.method [^\n]+\n.*?^\.end method")
GUARDED={
    "begin()V": "V",
    "visible()V": "V",
    "visibility(I)V": "V",
    "markMessage(Landroid/os/Message;)V": "V",
    "mark(Ljava/lang/String;)V": "V",
    "markHttp(Ljava/lang/String;II)V": "V",
    "nextHttp()I": "I",
    "markReq(Ljava/lang/String;III)V": "V",
}


def patch_trace(src: str) -> str:
    matched=set()
    def apply(m):
        body=m.group(0)
        signature=body.splitlines()[0]
        kinds=[(sig,k) for sig,k in GUARDED.items() if signature.endswith(" "+sig)]
        if not kinds:
            return body
        sig,ret=kinds[0]
        if sig in matched:
            raise RuntimeError("duplicated trace method "+sig)
        matched.add(sig)
        head=re.search(r"(?m)^    \.locals ([0-9]+)\s*$",body)
        if head is None or int(head.group(1))<1:
            raise RuntimeError("trace method must have at least one local register: "+sig)
        if ":nova_1199_off" in body:
            raise RuntimeError("1199 trace guard already installed "+sig)
        off=("    const/4 v0, 0x0\n    return v0\n" if ret=="I"
             else "    return-void\n")
        gate=(
            f"    invoke-static {{}}, {CLASS}->enabled()Z\n"
            "    move-result v0\n"
            "    if-eqz v0, :nova_1199_off\n"
        )
        # The guard must dominate all diagnostic-only StringBuilder, clock,
        # atomic counter and phase-recording instructions.
        body=body[:head.end()]+"\n"+gate+body[head.end():]
        ending=body.rfind(".end method")
        body=body[:ending]+"    :nova_1199_off\n"+off+body[ending:]
        return body
    out=METHOD.sub(apply,src)
    # 1200: end() must always clear diagnostic session state, even while
    # OFF, but must not construct the UI_SPINNER_HIDE diagnostic marker.
    matches=[m for m in METHOD.finditer(out)
             if m.group(0).splitlines()[0]==".method public static end()V"]
    if len(matches)!=1:
        raise RuntimeError("startup trace end() missing or duplicated")
    end_body=matches[0].group(0)
    prefix='.method public static end()V\n    .locals 1\n'
    if end_body.count(prefix)!=1 or ":nova_1200_end_reset" in end_body:
        raise RuntimeError("startup trace end() anchor drift")
    gate=('    invoke-static {}, '+CLASS+'->enabled()Z\n'
          '    move-result v0\n'
          '    if-eqz v0, :nova_1200_end_reset\n')
    end_body=end_body.replace(prefix,prefix+gate,1)
    reset=('    const/4 v0, 0x0\n'
           '    sput-boolean v0, '+TRACE+'->sActive:Z\n')
    if end_body.count(reset)!=1:
        raise RuntimeError("startup trace end() reset missing")
    end_body=end_body.replace(reset,'    :nova_1200_end_reset\n'+reset,1)
    out=out[:matches[0].start()]+end_body+out[matches[0].end():]
    if matched!=set(GUARDED):
        raise RuntimeError("startup diagnostic method coverage mismatch: "+str(sorted(matched)))
    if out.count(CLASS+"->enabled()Z")!=9:
        raise RuntimeError("not all eight producers and the end reset are gated")
    # end() is still allowed to clear sActive when switching OFF mid-session,
    # but the end marker itself calls gated mark().
    if ".method public static end()V" not in out:
        raise RuntimeError("startup diagnostic end-state reset removed")
    return out


def patch(root: Path) -> None:
    matches=list(root.glob("smali*/com/archos/mediacenter/video/player/NovaLoadingTrace.smali"))
    if len(matches)!=1:
        raise RuntimeError("NOVA 1199 startup Java trace missing or duplicated")
    p=matches[0]
    old=p.read_text()
    p.write_text(patch_trace(old))
    print(MARK+"=PASS eight sources plus end marker gated; reset preserved")


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--smali",required=True,type=Path)
    args=ap.parse_args()
    patch(args.smali)


if __name__=="__main__":
    main()
