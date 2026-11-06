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
    <item>WebDAV</item>
    <item>SMB</item>
    <item>天翼云盘</item>
    <item>FTP</item>
    <item>SFTP</item>
    <item>FTPS</item>
    <item>SSHJ</item>
    <item>SMBJ</item>
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

def patch_application(root):
    p=unique(root,"com/archos/mediacenter/video/CustomApplication.smali")
    t=p.read_text()
    m=re.search(r"(?ms)^\.method (?:public|protected) onCreate\(\)V\n.*?^\.end method",t)
    if not m:raise RuntimeError("CustomApplication.onCreate absent")
    body=m.group()
    # The optimized NOVA v6.6.4 app has multiple legitimate exit points.
    # Instrument all return sites to avoid skipping startup on some paths.
    exits=body.count("    return-void")
    if not 1 <= exits <= 5:
        raise RuntimeError(f"Unexpected CustomApplication.onCreate return paths: {exits}")
    body=body.replace("    return-void",
        "    # NOVA_TIANYI_COLD_BOOT_V1\n"
        f"    invoke-static {{p0}}, {CLOUD}->startIfSaved(Landroid/content/Context;)V\n"
        "    return-void")
    p.write_text(t[:m.start()]+body+t[m.end():])

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--decoded",type=Path,required=True)
    a=p.parse_args()
    patch_resources(a.decoded)
    patch_listener(a.decoded)
    patch_ok_listener(a.decoded)
    patch_dialog(a.decoded)
    patch_application(a.decoded)
    print("NOVA_TIANYI_PROTOCOL_SMALI_PATCH=PASS")

if __name__=="__main__":
    main()
