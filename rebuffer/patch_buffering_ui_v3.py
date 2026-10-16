#!/usr/bin/env python3
from pathlib import Path
import re,sys

root=Path(sys.argv[1])
smalis=list(root.rglob("*.smali"))
outer=None
listener=None
for p in smalis:
    s=p.read_text(errors="ignore")
    if ".class public Lcom/archos/mediacenter/video/player/PlayerActivity;" in s:
        outer=p
    if "Lcom/archos/mediacenter/video/player/PlayerActivity$PlayerListener;" in s and ".method public onBufferingUpdate(I)V" in s:
        listener=p
if not outer or not listener:
    raise SystemExit(f"PlayerActivity smali not found outer={outer} listener={listener}")

os=outer.read_text()
method=r'''
.method public novaSetNetworkBuffering(Z)V
    .locals 2

    iget-object v0, p0, Lcom/archos/mediacenter/video/player/PlayerActivity;->mProgressView:Landroid/view/View;

    if-eqz v0, :done

    if-eqz p1, :hide

    const/4 v1, 0x0
    invoke-virtual {v0, v1}, Landroid/view/View;->setVisibility(I)V
    goto :done

    :hide
    const/16 v1, 0x8
    invoke-virtual {v0, v1}, Landroid/view/View;->setVisibility(I)V

    :done
    return-void
.end method

'''
if ".method public novaSetNetworkBuffering(Z)V" not in os:
    marker=".method"
    pos=os.find(marker)
    if pos<0: raise SystemExit("no method marker in PlayerActivity")
    os=os[:pos]+method+os[pos:]
    outer.write_text(os)

ls=listener.read_text()
m=re.search(r'(?ms)^\.method public onBufferingUpdate\(I\)V\n.*?^\.end method\n',ls)
if not m: raise SystemExit("onBufferingUpdate method not found")
old=m.group(0)
new=r'''.method public onBufferingUpdate(I)V
    .locals 2

    const/4 v0, -0x1
    if-ne p1, v0, :check_end

    iget-object v0, p0, Lcom/archos/mediacenter/video/player/PlayerActivity$PlayerListener;->this$0:Lcom/archos/mediacenter/video/player/PlayerActivity;
    const/4 v1, 0x1
    invoke-virtual {v0, v1}, Lcom/archos/mediacenter/video/player/PlayerActivity;->novaSetNetworkBuffering(Z)V
    return-void

    :check_end
    const/4 v0, -0x2
    if-ne p1, v0, :normal

    iget-object v0, p0, Lcom/archos/mediacenter/video/player/PlayerActivity$PlayerListener;->this$0:Lcom/archos/mediacenter/video/player/PlayerActivity;
    const/4 v1, 0x0
    invoke-virtual {v0, v1}, Lcom/archos/mediacenter/video/player/PlayerActivity;->novaSetNetworkBuffering(Z)V
    return-void

    :normal
    iget-object v0, p0, Lcom/archos/mediacenter/video/player/PlayerActivity$PlayerListener;->this$0:Lcom/archos/mediacenter/video/player/PlayerActivity;
    invoke-static {v0}, Lcom/archos/mediacenter/video/player/PlayerActivity;->access$000(Lcom/archos/mediacenter/video/player/PlayerActivity;)Lcom/archos/mediacenter/video/player/Player;
    move-result-object v0
    invoke-virtual {v0}, Lcom/archos/mediacenter/video/player/Player;->isInPlaybackState()Z
    move-result v0
    if-nez v0, :done

    :done
    return-void
.end method
'''
# Preserve normal upstream behavior by using a safer body if access$000 is not present.
if "access$000(Lcom/archos/mediacenter/video/player/PlayerActivity;)" not in os:
    new=r'''.method public onBufferingUpdate(I)V
    .locals 2

    const/4 v0, -0x1
    if-ne p1, v0, :check_end
    iget-object v0, p0, Lcom/archos/mediacenter/video/player/PlayerActivity$PlayerListener;->this$0:Lcom/archos/mediacenter/video/player/PlayerActivity;
    const/4 v1, 0x1
    invoke-virtual {v0, v1}, Lcom/archos/mediacenter/video/player/PlayerActivity;->novaSetNetworkBuffering(Z)V
    return-void

    :check_end
    const/4 v0, -0x2
    if-ne p1, v0, :return_normal
    iget-object v0, p0, Lcom/archos/mediacenter/video/player/PlayerActivity$PlayerListener;->this$0:Lcom/archos/mediacenter/video/player/PlayerActivity;
    const/4 v1, 0x0
    invoke-virtual {v0, v1}, Lcom/archos/mediacenter/video/player/PlayerActivity;->novaSetNetworkBuffering(Z)V

    :return_normal
    return-void
.end method
'''
ls=ls[:m.start()]+new+ls[m.end():]
listener.write_text(ls)

# Structural verification.
for needle in ["novaSetNetworkBuffering(Z)V","mProgressView:Landroid/view/View;"]:
    if needle not in outer.read_text(): raise SystemExit("outer verify failed "+needle)
for needle in ["const/4 v0, -0x1","const/4 v0, -0x2","novaSetNetworkBuffering(Z)V"]:
    if needle not in listener.read_text(): raise SystemExit("listener verify failed "+needle)
print("PATCH_BUFFERING_UI=PASS")
