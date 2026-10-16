#!/usr/bin/env python3
from pathlib import Path
import re, sys

root = Path(sys.argv[1])
OUTER_DESC = "Lcom/archos/mediacenter/video/player/PlayerActivity;"
LISTENER_DESC = "Lcom/archos/mediacenter/video/player/PlayerActivity$PlayerListener;"
FRONTEND_DESC = "Lcom/archos/mediacenter/video/player/PlayerService$PlayerFrontend;"

outer_paths = list(root.rglob("PlayerActivity.smali"))
listener_paths = list(root.rglob("PlayerActivity$PlayerListener.smali"))

if len(outer_paths) != 1:
    raise SystemExit(f"expected exactly one PlayerActivity.smali, got {outer_paths}")
if len(listener_paths) != 1:
    raise SystemExit(f"expected exactly one PlayerActivity$PlayerListener.smali, got {listener_paths}")

outer = outer_paths[0]
listener = listener_paths[0]
os = outer.read_text(errors="ignore")
ls = listener.read_text(errors="ignore")

class_re = re.compile(r"(?m)^\.class[^\n]*\s(L[^;]+;)$")
outer_class = class_re.search(os)
listener_class = class_re.search(ls)
if not outer_class or outer_class.group(1) != OUTER_DESC:
    raise SystemExit("PlayerActivity descriptor mismatch")
if not listener_class or listener_class.group(1) != LISTENER_DESC:
    raise SystemExit("PlayerListener descriptor mismatch")
if f".implements {FRONTEND_DESC}" not in ls:
    raise SystemExit("PlayerListener no longer implements PlayerService$PlayerFrontend")

method_re = re.compile(
    r"(?ms)^\.method[^\n]*\sonBufferingUpdate\(I\)V\n.*?^\.end method\n?"
)
m = method_re.search(ls)
if not m:
    raise SystemExit("exact PlayerListener.onBufferingUpdate(I)V method not found")

old = m.group(0)
if "Landroid/widget/TextView;->setText" not in old:
    raise SystemExit("onBufferingUpdate no longer contains TextView.setText; refuse unsafe patch")

field_re = re.compile(
    r"(?m)^\.field[^\n]*\s(?P<name>[^\s:]+):" + re.escape(OUTER_DESC) + r"$"
)
fm = field_re.search(ls)
if not fm:
    raise SystemExit("PlayerListener outer PlayerActivity field not found")
outer_field = fm.group("name")

print(f"BUFFER_UI_LISTENER={listener}")
print("BUFFER_UI_METHOD=onBufferingUpdate(I)V")
print(f"BUFFER_UI_OUTER_FIELD={outer_field}")

helper = r'''
.method public novaSetNetworkBuffering(Z)V
    .locals 2

    iget-object v0, p0, Lcom/archos/mediacenter/video/player/PlayerActivity;->mProgressView:Landroid/view/View;

    if-eqz v0, :nova_done

    if-eqz p1, :nova_hide

    const/4 v1, 0x0
    invoke-virtual {v0, v1}, Landroid/view/View;->setVisibility(I)V
    goto :nova_done

    :nova_hide
    const/16 v1, 0x8
    invoke-virtual {v0, v1}, Landroid/view/View;->setVisibility(I)V

    :nova_done
    return-void
.end method

'''

if ".method public novaSetNetworkBuffering(Z)V" not in os:
    pos = os.find(".method")
    if pos < 0:
        raise SystemExit("no method marker in PlayerActivity")
    os = os[:pos] + helper + os[pos:]
    outer.write_text(os)

ls = listener.read_text(errors="ignore")
m = method_re.search(ls)
if not m:
    raise SystemExit("onBufferingUpdate disappeared before patch")
old = m.group(0)

if ":nova_ui_original" not in old:
    locals_m = re.search(r"(?m)^    \.locals (\d+)\n", old)
    regs_m = re.search(r"(?m)^    \.registers (\d+)\n", old)
    if locals_m:
        count = max(2, int(locals_m.group(1)))
        old = old[:locals_m.start()] + f"    .locals {count}\n" + old[locals_m.end():]
        insert_pos = old.find("\n", old.find(".locals")) + 1
    elif regs_m:
        count = int(regs_m.group(1)) + 2
        old = old[:regs_m.start()] + f"    .registers {count}\n" + old[regs_m.end():]
        insert_pos = old.find("\n", old.find(".registers")) + 1
    else:
        raise SystemExit("onBufferingUpdate has neither .locals nor .registers")

    prefix = f"""
    const/4 v0, -0x1
    if-ne p1, v0, :nova_ui_check_end

    iget-object v0, p0, {LISTENER_DESC}->{outer_field}:{OUTER_DESC}
    const/4 v1, 0x1
    invoke-virtual {{v0, v1}}, {OUTER_DESC}->novaSetNetworkBuffering(Z)V
    return-void

    :nova_ui_check_end
    const/4 v0, -0x2
    if-ne p1, v0, :nova_ui_original

    iget-object v0, p0, {LISTENER_DESC}->{outer_field}:{OUTER_DESC}
    const/4 v1, 0x0
    invoke-virtual {{v0, v1}}, {OUTER_DESC}->novaSetNetworkBuffering(Z)V
    return-void

    :nova_ui_original
"""
    new = old[:insert_pos] + prefix + old[insert_pos:]
    ls = ls[:m.start()] + new + ls[m.end():]
    listener.write_text(ls)

outer_text = outer.read_text(errors="ignore")
listener_text = listener.read_text(errors="ignore")
for needle in ["novaSetNetworkBuffering(Z)V", "mProgressView:Landroid/view/View;"]:
    if needle not in outer_text:
        raise SystemExit("outer verify failed: " + needle)
for needle in [
    "const/4 v0, -0x1",
    "const/4 v0, -0x2",
    "novaSetNetworkBuffering(Z)V",
    ":nova_ui_original",
    f".implements {FRONTEND_DESC}",
]:
    if needle not in listener_text:
        raise SystemExit("listener verify failed: " + needle)

print("PATCH_BUFFERING_UI=PASS")
