#!/usr/bin/env python3
from pathlib import Path
import re, sys

root = Path(sys.argv[1])
smalis = list(root.rglob("*.smali"))
outer = None
candidate_methods = []

OUTER_DESC = "Lcom/archos/mediacenter/video/player/PlayerActivity;"

method_re = re.compile(
    r"(?ms)^\\.method[^\\n]*\\s(?P<name>[^\\s(]+)\\(I\\)V\\n.*?^\\.end method\\n"
)

for p in smalis:
    ps = p.read_text(errors="ignore")
    if p.name == "PlayerActivity.smali" and OUTER_DESC in ps:
        outer = p

    for m in method_re.finditer(ps):
        body = m.group(0)
        score = 0
        if "->mBufferView:Landroid/widget/TextView;" in body:
            score += 8
        if "->isInPlaybackState()Z" in body:
            score += 6
        if "Landroid/widget/TextView;->setText" in body:
            score += 4
        if OUTER_DESC in body:
            score += 3
        if "%" in body:
            score += 1
        if score > 0:
            candidate_methods.append((score, p, m.start(), m.end(), body, m.group("name")))

if outer is None:
    raise SystemExit("PlayerActivity.smali not found")

if not candidate_methods:
    raise SystemExit("no behavioral buffering callback candidate found")

candidate_methods.sort(key=lambda x: (x[0], str(x[1]), x[2]), reverse=True)
best_score = candidate_methods[0][0]
best = [x for x in candidate_methods if x[0] == best_score]
if best_score < 14:
    details = "\n".join(f"score={x[0]} file={x[1]} method={x[5]}" for x in candidate_methods[:10])
    raise SystemExit("buffering callback score too weak:\n" + details)
if len(best) != 1:
    details = "\n".join(f"score={x[0]} file={x[1]} method={x[5]}" for x in best)
    raise SystemExit("ambiguous buffering callback candidates:\n" + details)

score, listener, start, end, old, method_name = best[0]
ls = listener.read_text(errors="ignore")
class_m = re.search(r"(?m)^\\.class[^\\n]*\\s(L[^;]+;)$", ls)
if not class_m:
    raise SystemExit("listener class descriptor not found")
listener_desc = class_m.group(1)

outer_field_m = re.search(
    re.escape(listener_desc) + r"->([^:]+):" + re.escape(OUTER_DESC),
    old,
)
if not outer_field_m:
    raise SystemExit(
        f"buffering callback found but outer PlayerActivity field not found: {listener} {method_name}"
    )
outer_field = outer_field_m.group(1)

print(f"BUFFER_UI_LISTENER={listener}")
print(f"BUFFER_UI_METHOD={method_name}")
print(f"BUFFER_UI_SCORE={score}")
print(f"BUFFER_UI_CLASS={listener_desc}")
print(f"BUFFER_UI_OUTER_FIELD={outer_field}")

# Add a small stable helper to PlayerActivity itself.
os = outer.read_text(errors="ignore")
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

# Re-read listener after outer patch in case both paths ever coincide.
ls = listener.read_text(errors="ignore")
matches = list(method_re.finditer(ls))
target = None
for m in matches:
    if m.group("name") != method_name:
        continue
    body = m.group(0)
    if "->mBufferView:Landroid/widget/TextView;" in body and "->isInPlaybackState()Z" in body:
        target = m
        break
if target is None:
    raise SystemExit("selected buffering callback disappeared before patch")

old = target.group(0)
if ":nova_ui_original" not in old:
    locals_m = re.search(r"(?m)^    \\.locals (\\d+)\\n", old)
    regs_m = re.search(r"(?m)^    \\.registers (\\d+)\\n", old)
    if locals_m:
        count = max(2, int(locals_m.group(1)))
        old = old[:locals_m.start()] + f"    .locals {count}\n" + old[locals_m.end():]
        insert_pos = old.find("\n", old.find(".locals")) + 1
    elif regs_m:
        count = int(regs_m.group(1)) + 2
        old = old[:regs_m.start()] + f"    .registers {count}\n" + old[regs_m.end():]
        insert_pos = old.find("\n", old.find(".registers")) + 1
    else:
        raise SystemExit("buffering callback has neither .locals nor .registers")

    prefix = f"""
    const/4 v0, -0x1
    if-ne p1, v0, :nova_ui_check_end

    iget-object v0, p0, {listener_desc}->{outer_field}:{OUTER_DESC}
    const/4 v1, 0x1
    invoke-virtual {{v0, v1}}, {OUTER_DESC}->novaSetNetworkBuffering(Z)V
    return-void

    :nova_ui_check_end
    const/4 v0, -0x2
    if-ne p1, v0, :nova_ui_original

    iget-object v0, p0, {listener_desc}->{outer_field}:{OUTER_DESC}
    const/4 v1, 0x0
    invoke-virtual {{v0, v1}}, {OUTER_DESC}->novaSetNetworkBuffering(Z)V
    return-void

    :nova_ui_original
"""
    new = old[:insert_pos] + prefix + old[insert_pos:]
    ls = ls[:target.start()] + new + ls[target.end():]
    listener.write_text(ls)

# Structural verification.
outer_text = outer.read_text(errors="ignore")
listener_text = listener.read_text(errors="ignore")
for needle in ["novaSetNetworkBuffering(Z)V", "mProgressView:Landroid/view/View;"]:
    if needle not in outer_text:
        raise SystemExit("outer verify failed " + needle)
for needle in [
    "const/4 v0, -0x1",
    "const/4 v0, -0x2",
    "novaSetNetworkBuffering(Z)V",
    ":nova_ui_original",
]:
    if needle not in listener_text:
        raise SystemExit("listener verify failed " + needle)

print("PATCH_BUFFERING_UI=PASS")
