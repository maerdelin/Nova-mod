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
    <item>天翼云盘</item>
    <item>SMB</item>
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
    snippet=f"""    # NOVA_TIANYI_UI_PROTOCOL_V2: index 1 is inserted Tianyi; other UI indexes map back to the original Always-new IDs.
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
              f"    invoke-static {{v11}}, {UI}->toUiIndex(I)I\n\n    move-result v11\n\n{anchor}\n"
              f"    # NOVA_TIANYI_DISABLE_DUPLICATE: preserve original spinner IDs.\n"
              f"    invoke-static {{v5}}, {UI}->installProtocolGuard(Landroid/widget/Spinner;)V",
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

def patch_shortcut_display(root):
    # NOVA's optimized GenericNetworkShortcutMapper derives the visible title
    # from Uri.getPath(), ignoring ShortcutDb's friendly shortcut_name column.
    # Replace only the displayed title of the reserved localhost Tianyi URI;
    # never change the path used to open the shortcut or any other protocol.
    p=unique(root,"com/archos/mediacenter/video/leanback/adapter/GenericNetworkShortcutMapper.smali")
    t=p.read_text()
    head=".method public bind(Landroid/database/Cursor;)Ljava/lang/Object;"
    start=t.index(head)
    end=t.index(".end method",start)
    method=t[start:end]
    anchor="    move-result-object v5\n\n    move-object v6, v4"
    injection=f"""    move-result-object v5

    # NOVA_TIANYI_SHORTCUT_NAME: map only the private local DAV shortcut.
    invoke-static {{v4, v5}}, {UI}->displayCloudShortcutName(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;
    move-result-object v5

    move-object v6, v4"""
    method=once(method,anchor,injection,"cloud shortcut name mapping")
    p.write_text(t[:start]+method+t[end:])
    print("NOVA_TIANYI_SHORTCUT_NAME=PATCHED")

def patch_shared_shortcut_getname(root):
    # The original phone database Shortcut object has a separate mUri
    # and mName. Apply the Tianyi display alias in getName() itself so
    # callers cannot accidentally show its random DAV capability path.
    p=unique(root,"com/archos/mediacenter/utils/ShortcutDbAdapter$Shortcut.smali")
    t=p.read_text()
    start=t.index(".method public getName()Ljava/lang/String;")
    end=t.index(".end method",start)
    body=t[start:end]
    old="""    .locals 0

    iget-object p0, p0, Lcom/archos/mediacenter/utils/ShortcutDbAdapter$Shortcut;->mName:Ljava/lang/String;

    return-object p0
"""
    new=f"""    .locals 2

    iget-object v0, p0, Lcom/archos/mediacenter/utils/ShortcutDbAdapter$Shortcut;->mName:Ljava/lang/String;
    iget-object v1, p0, Lcom/archos/mediacenter/utils/ShortcutDbAdapter$Shortcut;->mUri:Ljava/lang/String;
    invoke-static {{v1, v0}}, {UI}->displayCloudShortcutName(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;
    move-result-object v0
    return-object v0
"""
    body=once(body,old,new,"phone shared shortcut getName")
    p.write_text(t[:start]+body+t[end:])
    print("NOVA_TIANYI_PHONE_GETNAME=PATCHED")

def patch_phone_shortcut_title(root):
    # The PHONE screen does not use GenericNetworkShortcutMapper. Its actual
    # RecyclerView adapter reads ShortcutDbAdapter$Shortcut.getName(), which
    # is the internal random path in this APK. Swap only the display string;
    # retain the untouched URI and Shortcut object for click/navigation.
    p=unique(root,"com/archos/mediacenter/video/browser/filebrowsing/network/RootFragmentAdapter.smali")
    t=p.read_text()
    head=".method public onBindViewHolder(Landroidx/recyclerview/widget/o;I)V"
    start=t.index(head);end=t.index(".end method",start)
    body=t[start:end]
    anchor="""    invoke-virtual {p2}, Lcom/archos/mediacenter/utils/ShortcutDbAdapter$Shortcut;->getName()Ljava/lang/String;

    move-result-object v1

    invoke-virtual {v0, v1}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V"""
    replacement=f"""    invoke-virtual {{p2}}, Lcom/archos/mediacenter/utils/ShortcutDbAdapter$Shortcut;->getName()Ljava/lang/String;

    move-result-object v1

    # NOVA_TIANYI_PHONE_SHORTCUT_NAME: only localhost:27989 is renamed.
    invoke-virtual {{p2}}, Lcom/archos/mediacenter/utils/ShortcutDbAdapter$Shortcut;->getUri()Ljava/lang/String;
    move-result-object v4
    invoke-static {{v4, v1}}, {UI}->displayCloudShortcutName(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1

    invoke-virtual {{v0, v1}}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V"""
    body=once(body,anchor,replacement,"phone shortcut name display")
    p.write_text(t[:start]+body+t[end:])
    print("NOVA_TIANYI_PHONE_SHORTCUT_NAME=PATCHED")

def patch_phone_shortcut_secondary_uri(root):
    # Phone/tablet shows two text rows. The second displays the raw
    # 48-character capability via getFriendlyUri, even when getName works.
    p=unique(root,"com/archos/mediacenter/video/browser/filebrowsing/network/RootFragmentAdapter.smali")
    t=p.read_text()
    head=".method public onBindViewHolder(Landroidx/recyclerview/widget/o;I)V"
    start=t.index(head);end=t.index(".end method",start)
    body=t[start:end]
    anchor="""    invoke-virtual {p2}, Lcom/archos/mediacenter/utils/ShortcutDbAdapter$Shortcut;->getFriendlyUri()Ljava/lang/String;

    move-result-object v1

    invoke-virtual {v0, v1}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V"""
    replacement=f"""    invoke-virtual {{p2}}, Lcom/archos/mediacenter/utils/ShortcutDbAdapter$Shortcut;->getFriendlyUri()Ljava/lang/String;

    move-result-object v1

    # NOVA_TIANYI_PHONE_SECONDARY_URI: keep real address for navigation.
    invoke-virtual {{p2}}, Lcom/archos/mediacenter/utils/ShortcutDbAdapter$Shortcut;->getUri()Ljava/lang/String;
    move-result-object v4
    invoke-static {{v4, v1}}, {UI}->displayCloudShortcutName(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1

    invoke-virtual {{v0, v1}}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V"""
    body=once(body,anchor,replacement,"phone secondary friendly URI")
    p.write_text(t[:start]+body+t[end:])
    print("NOVA_TIANYI_PHONE_SECONDARY_URI=PATCHED")

def patch_actual_phone_shortcut_adapter(root):
    # Verified on official NOVA v6.6.4: the PHONE/TABLET shortcut card is
    # rendered in ShortcutAdapter.onBindViewHolder, not RootFragmentAdapter.
    # That class extracts Uri.getPath() and directly calls setName(v3).
    # Keep the original URI (v2) for click and playback, translate ONLY v3.
    p=unique(root,"com/archos/mediacenter/video/browser/filebrowsing/network/ShortcutAdapter.smali")
    t=p.read_text()
    head=".method public onBindViewHolder(Landroidx/recyclerview/widget/o;I)V"
    start=t.index(head)
    end=t.index(".end method",start)
    body=t[start:end]
    anchor="""    :cond_1
    :goto_0
    invoke-virtual {p1, v3}, Lcom/archos/mediacenter/video/browser/filebrowsing/network/ShortcutAdapter$ShortcutViewHolder;->setName(Ljava/lang/String;)V"""
    replacement=f"""    :cond_1
    :goto_0
    # NOVA_TIANYI_ACTUAL_PHONE_SHORTCUT_NAME: typed URI is not modified.
    invoke-virtual {{v2}}, Landroid/net/Uri;->toString()Ljava/lang/String;
    move-result-object v4
    invoke-static {{v4, v3}}, {UI}->displayCloudShortcutName(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;
    move-result-object v3
    invoke-virtual {{p1, v3}}, Lcom/archos/mediacenter/video/browser/filebrowsing/network/ShortcutAdapter$ShortcutViewHolder;->setName(Ljava/lang/String;)V"""
    body=once(body,anchor,replacement,"actual phone shortcut display")
    p.write_text(t[:start]+body+t[end:])
    print("NOVA_TIANYI_ACTUAL_PHONE_SHORTCUT_NAME=PATCHED")

def patch_shortcut_model(root):
    # Both phone and leanback lists may construct the same shortcut object
    # through different cursor mappers. Patch the shared constructor so all
    # renderers see the friendly name, while its real URI remains unchanged.
    p=unique(root,"com/archos/mediacenter/video/leanback/adapter/object/GenericNetworkShortcut.smali")
    t=p.read_text()
    m=re.search(r"(?ms)^\.method[^\n]* constructor <init>\(JLjava/lang/String;Ljava/lang/String;Ljava/lang/String;\)V\n.*?^\.end method",t)
    if not m: raise RuntimeError("GenericNetworkShortcut constructor signature missing")
    body=m.group()
    if "NOVA_TIANYI_SHARED_SHORTCUT_NAME" in body:
        raise RuntimeError("Model shortcut already patched")
    call=re.search(r"(?m)^    invoke-direct(?:/range)? [^\n]+$",body)
    if not call: raise RuntimeError("GenericNetworkShortcut parent constructor missing")
    # p3 is the original WebDAV URI, p4 is the list display title. No extra
    # registers are required, and the token/capability remains in p3.
    inserted=f"""    # NOVA_TIANYI_SHARED_SHORTCUT_NAME
    invoke-static {{p3, p4}}, {UI}->displayCloudShortcutName(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;
    move-result-object p4

"""
    body=body[:call.start()]+inserted+body[call.start():]
    p.write_text(t[:m.start()]+body+t[m.end():])
    print("NOVA_TIANYI_SHARED_SHORTCUT_NAME=PATCHED")

def patch_application_foreground_lifecycle(root):
    # Register ActivityLifecycleCallbacks when the Android process is created.
    # Unlike the old foreground Service, this never starts DAV on its own:
    # only onActivityStarted (for ANY NOVA Activity, including the player) binds.
    import xml.etree.ElementTree as ET
    manifest=ET.parse(root / "AndroidManifest.xml").getroot()
    app=manifest.find("application")
    if app is None: raise RuntimeError("Application element missing")
    name=app.get("{http://schemas.android.com/apk/res/android}name","")
    if not name: raise RuntimeError("Application name missing")
    if name.startswith("."):
        name=manifest.attrib["package"]+name
    elif "." not in name:
        name=manifest.attrib["package"]+"."+name
    p=unique(root,name.replace(".","/")+".smali")
    original=p.read_text()
    m=re.search(r"(?ms)^\.method[^\n]* onCreate\(\)V\n.*?^\.end method",original)
    hook=f"""    # NOVA_TIANYI_ACTIVITY_LIFECYCLE: all NOVA Activities, no FGS notification.
    invoke-static {{p0}}, {CLOUD}->installForegroundLifecycle(Landroid/app/Application;)V"""
    if not m:
        if "onCreate()V" in original:
            raise RuntimeError("Unsupported custom Application.onCreate format")
        parent=re.search(r"(?m)^\.super (L[^\s]+;)$",original)
        if not parent: raise RuntimeError("Application superclass missing")
        method=f"""
.method public onCreate()V
    .locals 0
    invoke-super {{p0}}, {parent.group(1)}->onCreate()V
{hook}
    return-void
.end method
"""
        p.write_text(original+"\n"+method)
        print("NOVA_TIANYI_ACTIVITY_LIFECYCLE=OVERRIDE",name)
        return
    body=m.group()
    # R8 retypes p0 in some optimized blocks. Insert immediately after
    # invoke-super while p0 is still the Application reference.
    supercall=re.search(r"(?m)^    invoke-super \{p0\}, L[^\s]+;->onCreate\(\)V$",body)
    if not supercall: raise RuntimeError("Typed Application.onCreate super missing")
    body=body[:supercall.end()]+"\n"+hook+body[supercall.end():]
    p.write_text(original[:m.start()]+body+original[m.end():])
    print("NOVA_TIANYI_ACTIVITY_LIFECYCLE=APP_ONCREATE",name)

 

def patch_tianyi_shortcut_icons(root):
    # Target the two VERIFIED icon bind sites; never replace the generic
    # WebDAV resource, as ordinary network shares use the same icon.
    phone=unique(root,"com/archos/mediacenter/video/browser/filebrowsing/network/ShortcutAdapter$ShortcutViewHolder.smali")
    code=phone.read_text()
    head=".method public setUri(Landroid/net/Uri;)V"
    start=code.index(head);end=code.index(".end method",start)
    body=code[start:end]
    body=once(body,"    .locals 0\n","    .locals 1\n","phone icon local register")
    anchor="""    move-result p1

    invoke-virtual {p0, p1}, Landroid/widget/ImageView;->setImageResource(I)V"""
    replacement=f"""    move-result p1

    invoke-virtual {{p0, p1}}, Landroid/widget/ImageView;->setImageResource(I)V

    # NOVA_TIANYI_PHONE_SHORTCUT_ICON: v0 is original URI, p0 is ImageView.
    invoke-static {{p0, v0}}, {UI}->applyCloudShortcutIcon(Landroid/widget/ImageView;Landroid/net/Uri;)V"""
    body=once(body,"    iput-object p1, p0, Lcom/archos/mediacenter/video/browser/filebrowsing/network/ShortcutAdapter$ShortcutViewHolder;->mUri:Landroid/net/Uri;","""    iput-object p1, p0, Lcom/archos/mediacenter/video/browser/filebrowsing/network/ShortcutAdapter$ShortcutViewHolder;->mUri:Landroid/net/Uri;

    move-object v0, p1""","phone original URI backup")
    body=once(body,anchor,replacement,"phone icon bind")
    phone.write_text(code[:start]+body+code[end:])

    tv=unique(root,"com/archos/mediacenter/video/leanback/presenter/NetworkShortcutPresenter.smali")
    code=tv.read_text()
    head=".method public onBindViewHolder(Lsx0;Ljava/lang/Object;)V"
    start=code.index(head);end=code.index(".end method",start)
    body=code[start:end]
    anchor="""    invoke-virtual {p0, v0}, Landroid/widget/ImageView;->setImageResource(I)V"""
    replacement=f"""    invoke-virtual {{p0, v0}}, Landroid/widget/ImageView;->setImageResource(I)V

    # NOVA_TIANYI_TV_SHORTCUT_ICON: only our saved localhost DAV capability.
    invoke-virtual {{p2}}, Lcom/archos/mediacenter/video/leanback/adapter/object/Shortcut;->getUri()Landroid/net/Uri;
    move-result-object v0
    invoke-static {{p0, v0}}, {UI}->applyCloudShortcutIcon(Landroid/widget/ImageView;Landroid/net/Uri;)V"""
    body=once(body,anchor,replacement,"TV icon bind")
    tv.write_text(code[:start]+body+code[end:])

    # Preserve the exact logo as an APK asset. The pinned apktool's
    # aapt2 crashes on palette+alpha PNG resource compilation; assets
    # are copied verbatim and safely decoded by Android BitmapFactory.
    icon=root/"assets/tianyi_cloud_shortcut.png"
    if icon.exists():raise RuntimeError("Tianyi icon drawable already exists")
    icon.parent.mkdir(parents=True,exist_ok=True)
    import shutil
    shutil.copyfile(Path(__file__).parent/"assets/tianyi_cloud_shortcut.png",icon)
    print("NOVA_TIANYI_PHONE_TV_SHORTCUT_ICONS=PATCHED")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--decoded",type=Path,required=True)
    a=p.parse_args()
    patch_resources(a.decoded)
    patch_listener(a.decoded)
    patch_ok_listener(a.decoded)
    patch_dialog(a.decoded)
    patch_network_on_resume(a.decoded)
    patch_shortcut_display(a.decoded)
    patch_shortcut_model(a.decoded)
    patch_phone_shortcut_title(a.decoded)
    patch_phone_shortcut_secondary_uri(a.decoded)
    patch_shared_shortcut_getname(a.decoded)
    patch_actual_phone_shortcut_adapter(a.decoded)
    patch_application_foreground_lifecycle(a.decoded)
    patch_tianyi_shortcut_icons(a.decoded)
    print("NOVA_TIANYI_PROTOCOL_SMALI_PATCH=PASS")

if __name__=="__main__":
    main()
