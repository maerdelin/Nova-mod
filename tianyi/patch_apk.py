#!/usr/bin/env python3
"""Inject the read-only Tianyi cloud protocol without renumbering legacy connections.

Runs on the decoded, already-patched NOVA v6.6.4 APK. All anchors must match
exactly once; fail rather than building an APK with wrong protocol mappings.
"""
from pathlib import Path
import argparse
import re

ROOT = "Lcom/archos/mediacenter/video/leanback/network/NetworkServerCredentialsDialog;"
UI = "Lcom/archos/mediacenter/video/cloud189/TianyiUi;"
CLOUD = "Lcom/archos/mediacenter/video/cloud189/TianyiCloud;"

def unique(root, rel):
    hits = list(root.glob("smali*/" + rel))
    if len(hits) != 1:
        raise RuntimeError(f"Expected exactly one {rel}, got {hits}")
    return hits[0]

def once(text, old, new, name):
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{name}: expected one anchor, got {n}")
    return text.replace(old, new, 1)

def patch_resources(root):
    layout = root / "res/layout/network_credential_layout.xml"
    xml=layout.read_text()
    xml=once(xml,'android:entries="@array/protocol_types"',
             'android:entries="@array/nova_tianyi_protocol_types"',"network protocol spinner")
    layout.write_text(xml)
    # Use a distinct array so the mobile SSH dialog's old index mapping is intact.
    values = root / "res/values/nova_tianyi_protocol.xml"
    if values.exists():
        raise RuntimeError("Protocol resource already exists")
    values.write_text("""<?xml version="1.0" encoding="utf-8"?>
<resources>
  <string-array name="nova_tianyi_protocol_types">
    <item>FTP</item>
    <item>SFTP</item>
    <item>FTPS</item>
    <item>SSHJ</item>
    <item>SMB</item>
    <item>天翼云盘</item>
    <item>SMBJ</item>
    <item>WebDAV</item>
    <item>WebDAVS</item>
  </string-array>
</resources>
""")

def patch_listener(root):
    p=unique(root,"com/archos/mediacenter/video/leanback/network/NetworkServerCredentialsDialog$1.smali")
    t=p.read_text()
    head=".method public onItemSelected(Landroid/widget/AdapterView;Landroid/view/View;IJ)V"
    start=t.index(head); end=t.index(".end method",start)
    body=t[start:end]
    body=once(body,"    .locals 0","    .locals 2","onItemSelected registers")
    anchor="    const/4 p1, 0x1"
    snippet=f"""    # NOVA_TIANYI_UI_PROTOCOL_V1: visible index 5 is not a legacy protocol.
    iget-object v0, p0, {ROOT[:-1]}$1;->this$0:{ROOT}
    iget-object v1, p0, {ROOT[:-1]}$1;->val$v:Landroid/view/View;
    invoke-static {{v0, v1, p3}}, {UI}->onSelection(Ljava/lang/Object;Landroid/view/View;I)Z
    move-result v0
    if-eqz v0, :nova_tianyi_regular_protocol
    return-void
    :nova_tianyi_regular_protocol
    invoke-static {{p3}}, {UI}->toLegacyType(I)I
    move-result p3

"""
    body=once(body,anchor,snippet+anchor,"listener protocol mapping")
    p.write_text(t[:start]+body+t[end:])

def patch_ok_listener(root):
    p=unique(root,"com/archos/mediacenter/video/leanback/network/NetworkServerCredentialsDialog$3.smali")
    t=p.read_text()
    head=".method public onClick(Landroid/content/DialogInterface;I)V"
    start=t.index(head);end=t.index(".end method",start)
    body=t[start:end]
    anchor="    invoke-virtual {v3}, Landroid/widget/AdapterView;->getSelectedItemPosition()I\n\n    move-result v9"
    injection=f"""{anchor}

    # NOVA_TIANYI_OK_GUARD_V1: QR authorization adds the shortcut automatically.
    iget-object v3, v0, {ROOT[:-1]}$3;->this$0:{ROOT}
    invoke-static {{v3, v9}}, {UI}->onConfirm(Ljava/lang/Object;I)Z
    move-result v3
    if-eqz v3, :nova_tianyi_not_confirm
    return-void
    :nova_tianyi_not_confirm
    invoke-static {{v9}}, {UI}->toLegacyType(I)I
    move-result v9"""
    body=once(body,anchor,injection,"OK handler protocol position")
    p.write_text(t[:start]+body+t[end:])

def patch_dialog(root):
    p=unique(root,"com/archos/mediacenter/video/leanback/network/NetworkServerCredentialsDialog.smali")
    t=p.read_text()
    head=".method public onCreateDialog(Landroid/os/Bundle;)Landroid/app/Dialog;"
    start=t.index(head);end=t.index(".end method",start)
    body=t[start:end]
    anchor="    invoke-virtual {v5, v11}, Landroid/widget/AdapterView;->setSelection(I)V"
    body=once(body,anchor,
              f"    invoke-static {{v11}}, {UI}->toUiIndex(I)I\n\n    move-result v11\n\n{anchor}",
              "initial saved protocol index")
    p.write_text(t[:start]+body+t[end:])

def patch_network_on_resume(root):
    # Do not load the optional cloud bridge in CustomApplication.onCreate.
    # An optional cloud feature must never risk the player's cold start.
    # NetworkRootFragment is the sole lazy restoration trigger.
    p=unique(root,"com/archos/mediacenter/video/leanback/network/NetworkRootFragment.smali")
    t=p.read_text()
    m=re.search(r"(?ms)^\.method public onResume\(\)V\n.*?^\.end method",t)
    if not m:raise RuntimeError("NetworkRootFragment.onResume missing")
    body=m.group()
    if ".locals 2" not in body:raise RuntimeError("NetworkRootFragment register layout changed")
    anchor="    invoke-super {p0}, Lzd;->onResume()V"
    inject=f"""    # NOVA_TIANYI_LAZY_DAV_V2: restore on network page only.
    invoke-virtual {{p0}}, Landroidx/fragment/app/q;->getActivity()Landroidx/fragment/app/v;
    move-result-object v0
    if-eqz v0, :nova_tianyi_no_activity
    invoke-static {{v0}}, {CLOUD}->startIfSaved(Landroid/content/Context;)V
    :nova_tianyi_no_activity
"""
    body=once(body,anchor,anchor+"\n"+inject+"    invoke-static {p0}, "+UI+"->registerNetworkPage(Ljava/lang/Object;)V\n","network resume lazy DAV")
    # The successful QR authorization inserts a NOVA ShortcutDb row.
    # Re-run the same original async network shortcut loader immediately,
    # rather than opening an unrelated activity or waiting for navigation.
    cls="Lcom/archos/mediacenter/video/leanback/network/NetworkRootFragment;"
    loader="Lcom/archos/mediacenter/video/leanback/network/NetworkRootFragment$NetworkShortcutsLoaderTask;"
    loader_file=unique(root,"com/archos/mediacenter/video/leanback/network/NetworkRootFragment$NetworkShortcutsLoaderTask.smali")
    loader_code=loader_file.read_text()
    # The optimized APK can add a synthetic constructor marker argument.
    # Never guess: derive exact Smali descriptor from the decoded baseline.
    signatures=re.findall(r"(?m)^\.method[^\n]* constructor <init>\(([^)]*)\)V$",loader_code)
    # R8 may retain both the normal inner-class constructor and a synthetic
    # extra-int overload. Prefer the normal constructor whenever present.
    candidates=[sig for sig in signatures if sig in (cls,cls+"I")]
    if not candidates:
        raise RuntimeError(f"Unsupported network loader constructors: {signatures}")
    ctor=cls if cls in candidates else cls+"I"
    if ctor==cls:
        arguments="{v0, p0}"
        init_regs=""
    elif ctor==cls+"I":
        arguments="{v0, p0, v1}"
        init_regs="    const/4 v1, 0x0\n"
    else:
        raise RuntimeError(f"Unexpected network loader constructor: {ctor}")
    if ".method public execute()V" not in loader_code or ".method public cancel()V" not in loader_code:
        raise RuntimeError("Network shortcuts loader execute/cancel methods changed")
    if f"mNetworkShortcutsLoaderTask:{loader}" not in t:
        raise RuntimeError("NetworkRootFragment shortcut loader field absent")
    refresh=f"""
.method public novaTianyiRefreshShortcuts()V
    .locals 2

    iget-object v0, p0, {cls}->mNetworkShortcutsLoaderTask:{loader}
    if-eqz v0, :nova_tianyi_new_loader
    invoke-virtual {{v0}}, {loader}->cancel()V

    :nova_tianyi_new_loader
    new-instance v0, {loader}
{init_regs}    invoke-direct {arguments}, {loader}-><init>({ctor})V
    iput-object v0, p0, {cls}->mNetworkShortcutsLoaderTask:{loader}
    invoke-virtual {{v0}}, {loader}->execute()V
    return-void
.end method
"""
    print("NOVA_TIANYI_NETWORK_REFRESH_CONSTRUCTOR=VERIFIED",ctor)
    if "novaTianyiRefreshShortcuts" in t:
        raise RuntimeError("Already injected network refresh")
    patched=t[:m.start()]+body+t[m.end():]+"\n"+refresh
    # Some optimized MOD navigation flows retain NetworkRootFragment without
    # dispatching its original onResume method. Also register from onCreate,
    # which happens once per live network page and needs no extra registers.
    oncreate=re.search(r"(?ms)^\.method public onCreate\(Landroid/os/Bundle;\)V\n.*?^\.end method",patched)
    if not oncreate: raise RuntimeError("NetworkRootFragment.onCreate missing")
    created=oncreate.group()
    exits=created.count("    return-void")
    if not 1 <= exits <= 5:
        raise RuntimeError(f"Unexpected network onCreate returns: {exits}")
    created=created.replace("    return-void",
        f"    invoke-static {{p0}}, {UI}->registerNetworkPage(Ljava/lang/Object;)V\n    return-void")
    patched=patched[:oncreate.start()]+created+patched[oncreate.end():]
    p.write_text(patched)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--decoded",type=Path,required=True)
    a=p.parse_args()
    patch_resources(a.decoded)
    patch_listener(a.decoded)
    patch_ok_listener(a.decoded)
    patch_dialog(a.decoded)
    patch_network_on_resume(a.decoded)
    print("NOVA_TIANYI_PROTOCOL_SMALI_PATCH=PASS")

if __name__=="__main__":
    main()
