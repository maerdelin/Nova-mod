#!/usr/bin/env python3
"""NOVA 994: keep the existing spinner/text through the actual native resume.

This script operates on the disassembled signed-993 smali and layout and runs
after startup_loading_diag_patch.apply_smali_trace. It never changes title
controls, subtitle views, or other player layouts.
"""
from pathlib import Path
import re

NAME="Lcom/archos/mediacenter/video/player/NovaStartupOverlay;"
PROXY="Lcom/archos/mediacenter/video/player/DirectTransportProxy;"
TRACE="Lcom/archos/mediacenter/video/player/NovaLoadingTrace;"

OVERLAY = r'''.class public final Lcom/archos/mediacenter/video/player/NovaStartupOverlay;
.super Ljava/lang/Object;
.implements Ljava/lang/Runnable;
.source "NovaStartupOverlay.java"

.field private static sCurrent:Lcom/archos/mediacenter/video/player/NovaStartupOverlay;
.field private mView:Landroid/view/View;
.field private mPercent:Landroid/widget/TextView;
.field private mRunning:Z
.field private mPrepared:Z

.method private constructor <init>(Landroid/view/View;)V
    .locals 2
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    iput-object p1, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mView:Landroid/view/View;
    const-string v0, "nova_buffer_percent"
    invoke-virtual {p1, v0}, Landroid/view/View;->findViewWithTag(Ljava/lang/Object;)Landroid/view/View;
    move-result-object v0
    instance-of v1, v0, Landroid/widget/TextView;
    if-eqz v1, :no_text
    check-cast v0, Landroid/widget/TextView;
    iput-object v0, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mPercent:Landroid/widget/TextView;
    :no_text
    const/4 v0, 0x1
    iput-boolean v0, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mRunning:Z
    return-void
.end method

.method public static reset()V
    .locals 2
    sget-object v0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->sCurrent:Lcom/archos/mediacenter/video/player/NovaStartupOverlay;
    if-eqz v0, :done
    const/4 v1, 0x0
    iput-boolean v1, v0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mRunning:Z
    iget-object v1, v0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mView:Landroid/view/View;
    if-eqz v1, :clear
    invoke-virtual {v1, v0}, Landroid/view/View;->removeCallbacks(Ljava/lang/Runnable;)Z
    :clear
    const/4 v0, 0x0
    sput-object v0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->sCurrent:Lcom/archos/mediacenter/video/player/NovaStartupOverlay;
    :done
    return-void
.end method

.method public static resetIfOwned(Landroid/view/View;)V
    .locals 1
    sget-object v0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->sCurrent:Lcom/archos/mediacenter/video/player/NovaStartupOverlay;
    if-eqz v0, :done
    iget-object v0, v0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mView:Landroid/view/View;
    if-ne v0, p0, :done
    invoke-static {}, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->reset()V
    :done
    return-void
.end method

.method public static armEarly(Landroid/view/View;I)V
    .locals 3
    if-eqz p0, :early_done
    if-nez p1, :early_done
    # Only the actual spinner root may own this updater.
    const-string v0, "nova_buffer_percent"
    invoke-virtual {p0, v0}, Landroid/view/View;->findViewWithTag(Ljava/lang/Object;)Landroid/view/View;
    move-result-object v0
    if-eqz v0, :early_done
    sget-object v0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->sCurrent:Lcom/archos/mediacenter/video/player/NovaStartupOverlay;
    if-eqz v0, :early_new
    iget-object v1, v0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mView:Landroid/view/View;
    if-eq v1, p0, :early_done
    invoke-static {}, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->reset()V
    :early_new
    new-instance v0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;
    invoke-direct {v0, p0}, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;-><init>(Landroid/view/View;)V
    sput-object v0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->sCurrent:Lcom/archos/mediacenter/video/player/NovaStartupOverlay;
    invoke-virtual {p0, v0}, Landroid/view/View;->post(Ljava/lang/Runnable;)Z
    const-string v1, "NOVA_EARLY_UI_V2"
    const-string v2, "spinner-visible-start"
    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    :early_done
    return-void
.end method

.method public static onPrepared(Landroid/view/View;)Z
    .locals 2
    if-eqz p0, :ordinary
    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->nativeStartupState()I
    move-result v0
    if-lez v0, :ordinary
    const/4 v1, 0x3
    if-ge v0, v1, :ordinary
    sget-object v1, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->sCurrent:Lcom/archos/mediacenter/video/player/NovaStartupOverlay;
    if-eqz v1, :fresh_prepared
    iget-object v0, v1, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mView:Landroid/view/View;
    if-ne v0, p0, :fresh_prepared
    const/4 v0, 0x1
    iput-boolean v0, v1, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mPrepared:Z
    return v0
    :fresh_prepared
    invoke-static {}, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->reset()V
    new-instance v0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;
    invoke-direct {v0, p0}, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;-><init>(Landroid/view/View;)V
    sput-object v0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->sCurrent:Lcom/archos/mediacenter/video/player/NovaStartupOverlay;
    const/4 v1, 0x0
    invoke-virtual {p0, v1}, Landroid/view/View;->setVisibility(I)V
    invoke-virtual {p0, v0}, Landroid/view/View;->post(Ljava/lang/Runnable;)Z
    const/4 v0, 0x1
    return v0
    :ordinary
    const/4 v0, 0x0
    return v0
.end method

.method private finish()V
    .locals 2
    sget-object v0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->sCurrent:Lcom/archos/mediacenter/video/player/NovaStartupOverlay;
    if-ne p0, v0, :done
    const/4 v0, 0x0
    iput-boolean v0, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mRunning:Z
    iget-object v1, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mView:Landroid/view/View;
    if-eqz v1, :clear
    const/16 v0, 0x8
    invoke-virtual {v1, v0}, Landroid/view/View;->setVisibility(I)V
    const-string v0, "NOVA_994_UI_HIDE"
    const-string v1, "after-native-resume"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    :clear
    const/4 v0, 0x0
    sput-object v0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->sCurrent:Lcom/archos/mediacenter/video/player/NovaStartupOverlay;
    invoke-static {}, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->end()V
    :done
    return-void
.end method

.method public run()V
    .locals 5
    iget-boolean v0, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mRunning:Z
    if-eqz v0, :done
    sget-object v0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->sCurrent:Lcom/archos/mediacenter/video/player/NovaStartupOverlay;
    if-ne p0, v0, :done
    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->nativeStartupState()I
    move-result v0
    if-eqz v0, :reschedule
    const/4 v1, 0x3
    if-ge v0, v1, :finish
    iget-object v2, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mPercent:Landroid/widget/TextView;
    if-eqz v2, :reschedule
    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->nativeStartupPercent()I
    move-result v3
    # NOVA_1052_INTEGER_ONLY_V1: no text for fractions: 0..0.999% is 0%.
    new-instance v4, Ljava/lang/StringBuilder;
    invoke-direct {v4}, Ljava/lang/StringBuilder;-><init>()V
    invoke-virtual {v4, v3}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    const-string v3, "%"
    invoke-virtual {v4, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v4}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v3
    invoke-virtual {v2, v3}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V
    const-string v0, "NOVA_994_UI_TICK"
    invoke-static {v0, v3}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    :reschedule
    iget-object v0, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mView:Landroid/view/View;
    if-eqz v0, :done
    const-wide/16 v1, 0xc8
    invoke-virtual {v0, p0, v1, v2}, Landroid/view/View;->postDelayed(Ljava/lang/Runnable;J)Z
    goto :done
    :finish
    invoke-direct {p0}, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->finish()V
    :done
    return-void
.end method
'''

def one(paths, name):
    got=list(paths)
    if len(got)!=1:raise RuntimeError(f"994 {name} count={len(got)}")
    return got[0]

def patch(root: Path):
    player=one(root.glob("smali*/com/archos/mediacenter/video/player/PlayerActivity.smali"),"activity")
    src=player.read_text()
    # The official build applies NovaLoadingTrace fresh and inserts its
    # end() hook directly above setVisibility, whereas signed 993 may have a
    # blank line there. Patch the target method only, preserving all other
    # visibility calls and allocating a new local register for the result.
    method_header=re.compile(
        r"(?m)^\.method[^\n]* postVideoInfoAndPrepared\(\)V\n")
    match_headers=list(method_header.finditer(src))
    if len(match_headers)!=1:
        raise RuntimeError("994 prepared method unique match required")
    method_begin=match_headers[0].start()
    method_end=src.index(".end method",method_begin)+len(".end method")
    method=src[method_begin:method_end]
    register=re.search(r"(?m)^    \.locals (\d+)$",method)
    if not register:
        raise RuntimeError("994 prepared method requires .locals to preserve p0")
    free_local=int(register.group(1))
    if free_local>=255:
        raise RuntimeError("994 prepared method has no safe scratch register")
    scratch="v"+str(free_local)
    method=method[:register.start(1)]+str(free_local+1)+method[register.end(1):]
    hide=re.compile(
        r"(?m)^[ \t]*invoke-static \{\}, "
        +re.escape(TRACE)+r"->end\(\)V[ \t]*\n"
        r"(?:[ \t]*\n)*"
        r"[ \t]*invoke-virtual(?:/range)? \{(v\d+), (v\d+)\}, "
        r"Landroid/view/View;->setVisibility\(I\)V[ \t]*$")
    matches=list(hide.finditer(method))
    if len(matches)!=1:
        raise RuntimeError("994 prepared spinner anchor count="+str(len(matches)))
    anchor=matches[0]
    view,visibility=anchor.group(1),anchor.group(2)
    invoke=("invoke-static/range {"+view+" .. "+view+"}, "
            if int(view[1:])>15 else "invoke-static {"+view+"}, ")
    keep_label=":nova994_keep_spinner"
    if keep_label in method:
        raise RuntimeError("994 prepared double patch")
    patched=(
        "    "+invoke+NAME+"->onPrepared(Landroid/view/View;)Z\n"
        "    move-result "+scratch+"\n"
        "    if-nez "+scratch+", "+keep_label+"\n"
        "    invoke-static {}, "+TRACE+"->end()V\n"
        "    invoke-virtual {"+view+", "+visibility+"}, Landroid/view/View;->setVisibility(I)V\n"
        "    "+keep_label)
    method=method[:anchor.start()]+patched+method[anchor.end():]
    src=src[:method_begin]+method+src[method_end:]
    start='''    invoke-static {}, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->begin()V'''
    if(src.count(start)!=1):raise RuntimeError("994 start hook count")
    src=src.replace(start,start+"\n    invoke-static {}, "+NAME+"->reset()V",1)
    # Lifecycle stop always wins over any remaining startup loader.
    stop_head='.method private stop()V'
    p=src.index(stop_head)
    tail=src.index('.end method',p)
    part=src[p:tail]
    stop_hook='    const-string v0, "UI_STOP"'
    if(part.count(stop_hook)!=1):raise RuntimeError("994 stop hook count")
    part=part.replace(stop_hook,
        '    iget-object v0, p0, Lcom/archos/mediacenter/video/player/PlayerActivity;->mProgressView:Landroid/view/View;' + chr(10) +
        '    invoke-static {v0}, '+NAME+'->resetIfOwned(Landroid/view/View;)V' + chr(10) + stop_hook,1)
    src=src[:p]+part+src[tail:]
    player.write_text(src)

    # Arm the same overlay at the actual View.VISIBLE operation instead of
    # waiting for postVideoInfoAndPrepared(). No original visibility call
    # is removed, and normal non-NOVA spinner remains owned by Android.
    handler_candidates=[]
    for hp in root.glob("smali*/com/archos/mediacenter/video/player/PlayerActivity$*.smali"):
        hsrc=hp.read_text()
        if "NovaLoadingTrace;->visibility(I)V" in hsrc:
            handler_candidates.append((hp,hsrc))
    if len(handler_candidates)!=1:
        raise RuntimeError("994 early UI handler marker count="+str(len(handler_candidates)))
    hp,hsrc=handler_candidates[0]
    pattern=re.compile(
        r"(?m)(^[ \t]*invoke-static(?:/range)? \{[^\n]+\}, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->visibility\(I\)V[ \t]*\n)"
        r"(^[ \t]*invoke-virtual(?:/range)? \{([^}\n]+)\}, Landroid/view/View;->setVisibility\(I\)V[ \t]*$)")
    matches=list(pattern.finditer(hsrc))
    if not matches:
        raise RuntimeError("994 early UI missing spinner visibility pair")
    for match in reversed(matches):
        operands=match.group(3).strip()
        # apktool may normalize invoke-virtual to /range {vN .. vN+1}.
        found=re.findall(r"[vp]\d+",operands)
        if len(found)!=2:
            raise RuntimeError("994 early UI unexpected View.setVisibility args: "+operands)
        view,vis=found
        vi,vis_i=int(view[1:]),int(vis[1:])
        if vi>=16 or vis_i>=16:
            if vis_i!=vi+1:raise RuntimeError("994 early UI non-adjacent high registers")
            invoke="invoke-static/range {"+view+" .. "+vis+"}, "
        else:
            invoke="invoke-static {"+view+", "+vis+"}, "
        inserted=match.group(1)+"    "+invoke+NAME+"->armEarly(Landroid/view/View;I)V\n"+match.group(2)
        hsrc=hsrc[:match.start()]+inserted+hsrc[match.end():]
    hp.write_text(hsrc)

    proxy=one(root.glob("smali*/com/archos/mediacenter/video/player/DirectTransportProxy.smali"),"proxy")
    txt=proxy.read_text()
    anchor='.method private constructor <init>()V'
    if(txt.count(anchor)!=1):raise RuntimeError("994 native JNI anchor")
    txt=txt.replace(anchor,'''# NOVA_STARTUP_UI_STATE_V1
.method public static native nativeStartupState()I
.end method
.method public static native nativeStartupPercent()I
.end method
.method public static native nativeStartupResidentBytes()J
.end method

'''+anchor,1)
    proxy.write_text(txt)

    layout=root/"res/layout/player.xml"
    xml=layout.read_text()
    old='''        <ProgressBar android:layout_gravity="center" android:id="@android:id/progress" android:layout_width="wrap_content" android:layout_height="wrap_content" style="?android:progressBarStyleLarge" />'''
    new='''        <FrameLayout android:layout_gravity="center" android:layout_width="58.0dp" android:layout_height="58.0dp">
            <ProgressBar android:layout_gravity="center" android:id="@android:id/progress" android:layout_width="58.0dp" android:layout_height="58.0dp" style="?android:progressBarStyleLarge" />
            <TextView android:tag="nova_buffer_percent" android:gravity="center" android:singleLine="true" android:maxLines="1" android:textSize="10.0sp" android:textStyle="bold" android:textColor="#ffffffff" android:layout_gravity="center" android:layout_width="52.0dp" android:layout_height="wrap_content" android:text="0%" />
        </FrameLayout>'''
    if(xml.count(old)!=1):raise RuntimeError("994 progress layout anchor")
    layout.write_text(xml.replace(old,new,1))

    target=proxy.parent/"NovaStartupOverlay.smali"
    if target.exists():raise RuntimeError("994 overlay already installed")
    target.write_text(OVERLAY)
    print("NOVA_STARTUP_994_UI_PATCH=PASS retained loading text; centered 200ms integer buffer percent; native resume")

if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("root",type=Path)
    patch(ap.parse_args().root)
