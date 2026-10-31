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
.field private mSpeed:Landroid/widget/TextView;
.field private mLastBytes:J
.field private mLastTime:J
.field private mRunning:Z

.method private constructor <init>(Landroid/view/View;)V
    .locals 3
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    iput-object p1, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mView:Landroid/view/View;
    const-string v0, "nova_speed"
    invoke-virtual {p1, v0}, Landroid/view/View;->findViewWithTag(Ljava/lang/Object;)Landroid/view/View;
    move-result-object v0
    instance-of v1, v0, Landroid/widget/TextView;
    if-eqz v1, :no_text
    check-cast v0, Landroid/widget/TextView;
    iput-object v0, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mSpeed:Landroid/widget/TextView;
    :no_text
    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->nativeStartupBytes()J
    move-result-wide v0
    iput-wide v0, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mLastBytes:J
    invoke-static {}, Landroid/os/SystemClock;->elapsedRealtime()J
    move-result-wide v0
    iput-wide v0, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mLastTime:J
    const/4 v0, 0x1
    iput-boolean v0, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mRunning:Z
    return-void
.end method

.method public static reset()V
    .locals 3
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

.method public static onPrepared(Landroid/view/View;)Z
    .locals 3
    if-eqz p0, :ordinary
    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->nativeStartupState()I
    move-result v0
    if-lez v0, :ordinary
    const/4 v1, 0x3
    if-ge v0, v1, :ordinary
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
    const/4 v0, 0x0
    iput-boolean v0, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mRunning:Z
    iget-object v1, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mView:Landroid/view/View;
    if-eqz v1, :clear
    const/16 v0, 0x8
    invoke-virtual {v1, v0}, Landroid/view/View;->setVisibility(I)V
    :clear
    sget-object v1, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->sCurrent:Lcom/archos/mediacenter/video/player/NovaStartupOverlay;
    if-ne p0, v1, :done
    const/4 v0, 0x0
    sput-object v0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->sCurrent:Lcom/archos/mediacenter/video/player/NovaStartupOverlay;
    invoke-static {}, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->end()V
    :done
    return-void
.end method

.method public run()V
    .locals 14
    iget-boolean v0, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mRunning:Z
    if-eqz v0, :done
    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->nativeStartupState()I
    move-result v0
    if-eqz v0, :finish
    const/4 v1, 0x3
    if-ge v0, v1, :finish
    invoke-static {}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->nativeStartupBytes()J
    move-result-wide v0
    invoke-static {}, Landroid/os/SystemClock;->elapsedRealtime()J
    move-result-wide v2
    iget-wide v4, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mLastTime:J
    sub-long v4, v2, v4
    const-wide/16 v6, 0x0
    cmp-long v8, v4, v6
    if-lez v8, :reschedule
    iget-wide v8, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mLastBytes:J
    sub-long v8, v0, v8
    cmp-long v10, v8, v6
    if-ltz v10, :zero_rate
    goto :calculate
    :zero_rate
    const-wide/16 v8, 0x0
    :calculate
    iput-wide v0, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mLastBytes:J
    iput-wide v2, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mLastTime:J
    const-wide/16 v10, 0x3e8
    mul-long/2addr v8, v10
    div-long/2addr v8, v4
    const-wide/32 v10, 0x100000
    cmp-long v12, v8, v10
    if-ltz v12, :k_rate
    div-long/2addr v8, v10
    invoke-static {v8, v9}, Ljava/lang/String;->valueOf(J)Ljava/lang/String;
    move-result-object v10
    new-instance v11, Ljava/lang/StringBuilder;
    invoke-direct {v11}, Ljava/lang/StringBuilder;-><init>()V
    invoke-virtual {v11, v10}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    const-string v10, "M/S"
    invoke-virtual {v11, v10}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v11}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v10
    goto :show
    :k_rate
    const-wide/16 v10, 0x400
    div-long/2addr v8, v10
    invoke-static {v8, v9}, Ljava/lang/String;->valueOf(J)Ljava/lang/String;
    move-result-object v10
    new-instance v11, Ljava/lang/StringBuilder;
    invoke-direct {v11}, Ljava/lang/StringBuilder;-><init>()V
    invoke-virtual {v11, v10}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    const-string v10, "K/S"
    invoke-virtual {v11, v10}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v11}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v10
    :show
    iget-object v11, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mSpeed:Landroid/widget/TextView;
    if-eqz v11, :reschedule
    invoke-virtual {v11, v10}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V
    :reschedule
    iget-object v0, p0, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->mView:Landroid/view/View;
    if-eqz v0, :done
    const-wide/16 v1, 0x190
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
    prepare='''    invoke-static {}, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->end()V

    invoke-virtual {v0, v1}, Landroid/view/View;->setVisibility(I)V'''
    replacement='''    invoke-static {v0}, Lcom/archos/mediacenter/video/player/NovaStartupOverlay;->onPrepared(Landroid/view/View;)Z
    move-result v4
    if-nez v4, :nova994_keep_spinner
    invoke-static {}, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->end()V
    invoke-virtual {v0, v1}, Landroid/view/View;->setVisibility(I)V
    :nova994_keep_spinner'''
    if(src.count(prepare)!=1):raise RuntimeError("994 prepared spinner anchor count")
    src=src.replace(prepare,replacement,1)
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
    part=part.replace(stop_hook,\n        "    iget-object v0, p0, Lcom/archos/mediacenter/video/player/PlayerActivity;->mProgressView:Landroid/view/View;\\n"\n        "    invoke-static {v0}, "+NAME+"->resetIfOwned(Landroid/view/View;)V\\n"+stop_hook,1)
    src=src[:p]+part+src[tail:]
    player.write_text(src)

    proxy=one(root.glob("smali*/com/archos/mediacenter/video/player/DirectTransportProxy.smali"),"proxy")
    txt=proxy.read_text()
    anchor='.method private constructor <init>()V'
    if(txt.count(anchor)!=1):raise RuntimeError("994 native JNI anchor")
    txt=txt.replace(anchor,'''# NOVA_STARTUP_UI_STATE_V1
.method public static native nativeStartupState()I
.end method
.method public static native nativeStartupBytes()J
.end method

'''+anchor,1)
    proxy.write_text(txt)

    layout=root/"res/layout/player.xml"
    xml=layout.read_text()
    old='''        <ProgressBar android:layout_gravity="center" android:id="@android:id/progress" android:layout_width="wrap_content" android:layout_height="wrap_content" style="?android:progressBarStyleLarge" />'''
    new='''        <FrameLayout android:layout_gravity="center" android:layout_width="58.0dp" android:layout_height="58.0dp">
            <ProgressBar android:layout_gravity="center" android:id="@android:id/progress" android:layout_width="58.0dp" android:layout_height="58.0dp" style="?android:progressBarStyleLarge" />
            <TextView android:tag="nova_speed" android:gravity="center" android:singleLine="true" android:maxLines="1" android:textSize="10.0sp" android:textStyle="bold" android:textColor="#ffffffff" android:layout_gravity="center" android:layout_width="52.0dp" android:layout_height="wrap_content" android:text="0K/S" />
        </FrameLayout>'''
    if(xml.count(old)!=1):raise RuntimeError("994 progress layout anchor")
    layout.write_text(xml.replace(old,new,1))

    target=proxy.parent/"NovaStartupOverlay.smali"
    if target.exists():raise RuntimeError("994 overlay already installed")
    target.write_text(OVERLAY)
    print("NOVA_STARTUP_994_UI_PATCH=PASS retained loading text; centered speed; native resume")

if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("root",type=Path)
    patch(ap.parse_args().root)
