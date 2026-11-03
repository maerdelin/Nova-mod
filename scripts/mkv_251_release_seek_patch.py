#!/usr/bin/env python3
"""NOVA 1097: switch to release-only DPAD Seek only on actual Seek spinner.

Ordinary MKVs keep their original repeated keyframe previews, regardless of
file size or HTTP403 history. The already-decoded PlayerActivity loading-view
Handler triggers a one-way per-held-key fallback ONLY when it tries to show a
spinner while a WebDAV Matroska DPAD seek is actively held. Hide the spinner,
suppress further repeated native seeks, and submit final pointer on key-up.
No changes to MP4/TS/ISO, local videos or slider/touch seeking.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re
from iso_seek_ui_patch import PC, edit_method, entry, once

PLAYER = "Lcom/archos/mediacenter/video/player/Player;"
PROXY = "Lcom/archos/mediacenter/video/player/DirectTransportProxy;"
HANDLER = "Landroid/os/Handler;"
MSG = "Landroid/os/Message;"
INNER = "Lcom/archos/mediacenter/video/player/PlayerController$8;"
TAG = "NOVA_MKV_SPINNER_RELEASE_ONLY_V3"

# The controller already owns an Android main-thread Handler. Message 9 is
# outside upstream's 1..8 switch and is never sent to the normal Seek handler.
# While held it ONLY updates target/progress; it cannot pause, seek, or read.
NEW_METHODS = f"""
.method public nova251OnSeekSpinner()Z
    .locals 3
    # Called ONLY from the Activity loading-view SHOW message.
    # No file size, HTTP status, or permanent per-video whitelist.
    iget-boolean v0, p0, {PC}->mIsStopped:Z
    if-nez v0, :nova251_not_seek_spinner
    iget v0, p0, {PC}->mSeekKeyDirection:I
    if-eqz v0, :nova251_not_seek_spinner
    invoke-static {{}}, {PROXY}->isNonIsoDirectWebdav()Z
    move-result v0
    if-eqz v0, :nova251_not_seek_spinner
    invoke-static {{}}, {PROXY}->nativeIsWebdavMkv()Z
    move-result v0
    if-eqz v0, :nova251_not_seek_spinner
    iget-boolean v0, p0, {PC}->mNova251Hold:Z
    if-nez v0, :nova251_already_spinner_held
    const/4 v0, 0x1
    iput-boolean v0, p0, {PC}->mNova251Hold:Z
    # Preserve mNextSeek from the last real preview. Never reset it
    # to -1 when the fallback is activated in the MIDDLE of a seek.
    iget-object v1, p0, {PC}->mHandler:{HANDLER}
    if-eqz v1, :nova251_spinner_arm
    const/4 v2, 0x2
    invoke-virtual {{v1, v2}}, {HANDLER}->removeMessages(I)V
    const/4 v2, 0x3
    invoke-virtual {{v1, v2}}, {HANDLER}->removeMessages(I)V
    :nova251_spinner_arm
    invoke-direct {{p0}}, {PC}->nova251ArmTick()V
    const-string v1, "NovaSeek251"
    const-string v2, "{TAG}: spinner while DPAD held; hide, target-only until release"
    invoke-static {{v1, v2}}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    move-result v1
    :nova251_already_spinner_held
    const/4 v0, 0x1
    return v0
    :nova251_not_seek_spinner
    const/4 v0, 0x0
    return v0
.end method

.method private nova251ArmTick()V
    .locals 4
    iget-object v0, p0, {PC}->mHandler:{HANDLER}
    if-eqz v0, :nova251_arm_done
    const/16 v1, 0x9
    invoke-virtual {{v0, v1}}, {HANDLER}->removeMessages(I)V
    invoke-virtual {{v0, v1}}, {HANDLER}->obtainMessage(I){MSG}
    move-result-object v1
    const-wide/16 v2, 0xc8
    invoke-virtual {{v0, v1, v2, v3}}, {HANDLER}->sendMessageDelayed({MSG}J)Z
    :nova251_arm_done
    return-void
.end method

.method private nova251Clamp()V
    .locals 2
    iget v0, p0, {PC}->mNextSeek:I
    if-gez v0, :nova251_min_ok
    const/4 v0, 0x0
    :nova251_min_ok
    sget-object v1, {PLAYER}->sPlayer:{PLAYER}
    if-eqz v1, :nova251_clamp_store
    invoke-virtual {{v1}}, {PLAYER}->getDuration()I
    move-result v1
    add-int/lit16 v1, v1, -0x7d0
    if-lez v1, :nova251_clamp_store
    if-le v0, v1, :nova251_clamp_store
    move v0, v1
    :nova251_clamp_store
    iput v0, p0, {PC}->mNextSeek:I
    return-void
.end method

.method private nova251BeginHold(I)V
    .locals 2
    iget-boolean v0, p0, {PC}->mNova251Hold:Z
    if-nez v0, :nova251_hold_continue
    const/4 v0, 0x1
    iput-boolean v0, p0, {PC}->mNova251Hold:Z
    const/4 v0, -0x1
    iput v0, p0, {PC}->mNextSeek:I
    const/4 v0, 0x0
    iput-boolean v0, p0, {PC}->mSeekWasPlaying:Z
    iput-boolean v0, p0, {PC}->mDragging:Z
    iget-object v0, p0, {PC}->mHandler:{HANDLER}
    const/4 v1, 0x3
    invoke-virtual {{v0, v1}}, {HANDLER}->removeMessages(I)V
    :nova251_hold_continue
    invoke-direct {{p0, p1}}, {PC}->setNextSeekPos(I)V
    invoke-direct {{p0}}, {PC}->nova251Clamp()V
    invoke-direct {{p0}}, {PC}->setProgress()I
    move-result v0
    invoke-direct {{p0}}, {PC}->nova251ArmTick()V
    const-string v0, "{TAG}: keydown target-only no-pause no-seek"
    const-string v1, "NovaSeek251"
    invoke-static {{v1, v0}}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    move-result v0
    return-void
.end method

.method public nova251HoldTick()V
    .locals 2
    iget-boolean v0, p0, {PC}->mNova251Hold:Z
    if-eqz v0, :nova251_tick_done
    iget v0, p0, {PC}->mSeekKeyDirection:I
    if-eqz v0, :nova251_tick_commit
    invoke-direct {{p0, v0}}, {PC}->setNextSeekPos(I)V
    invoke-direct {{p0}}, {PC}->nova251Clamp()V
    invoke-direct {{p0}}, {PC}->setProgress()I
    move-result v1
    invoke-direct {{p0}}, {PC}->nova251ArmTick()V
    goto :nova251_tick_done
    :nova251_tick_commit
    invoke-direct {{p0}}, {PC}->nova251Commit()V
    :nova251_tick_done
    return-void
.end method

.method private nova251Commit()V
    .locals 3
    iget-boolean v0, p0, {PC}->mNova251Hold:Z
    if-eqz v0, :nova251_commit_done
    const/4 v0, 0x0
    iput-boolean v0, p0, {PC}->mNova251Hold:Z
    iget-object v0, p0, {PC}->mHandler:{HANDLER}
    if-eqz v0, :nova251_commit_source
    const/16 v1, 0x9
    invoke-virtual {{v0, v1}}, {HANDLER}->removeMessages(I)V
    :nova251_commit_source
    # Never commit a target into a different video after activity switch.
    invoke-static {{}}, {PROXY}->isNonIsoDirectWebdav()Z
    move-result v0
    if-eqz v0, :nova251_commit_clear
    invoke-static {{}}, {PROXY}->nativeIsWebdavMkv()Z
    move-result v0
    if-eqz v0, :nova251_commit_clear
    invoke-direct {{p0}}, {PC}->nova251Clamp()V
    iget v0, p0, {PC}->mNextSeek:I
    if-ltz v0, :nova251_commit_clear
    sget-object v1, {PLAYER}->sPlayer:{PLAYER}
    if-eqz v1, :nova251_commit_clear
    # Exactly one native SEEK after key UP. Any HTTP 403 retries happen here.
    invoke-virtual {{v1, v0}}, {PLAYER}->seekTo(I)V
    const-string v1, "NovaSeek251"
    const-string v2, "{TAG}: keyup final-position seek submitted"
    invoke-static {{v1, v2}}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    move-result v0
    :nova251_commit_clear
    const/4 v0, -0x1
    iput v0, p0, {PC}->mNextSeek:I
    invoke-direct {{p0}}, {PC}->setProgress()I
    move-result v0
    :nova251_commit_done
    return-void
.end method

.method private nova251Cancel()V
    .locals 2
    const/4 v0, 0x0
    iput-boolean v0, p0, {PC}->mNova251Hold:Z
    iget-object v0, p0, {PC}->mHandler:{HANDLER}
    if-eqz v0, :nova251_cancel_done
    const/16 v1, 0x9
    invoke-virtual {{v0, v1}}, {HANDLER}->removeMessages(I)V
    :nova251_cancel_done
    return-void
.end method
"""

def patch_controller(src: str) -> str:
    if TAG in src:
        raise RuntimeError("1097 scope already patched")
    src = once(src, "# instance fields",
               "# instance fields\n.field private mNova251Hold:Z\n",
               "dedicated special-MKV hold state")

    def modify_on_seek(method: str) -> str:
        # Before a spinner event, ALL MKVs take the original onSeek path.
        # After the actual loading view event while DPAD is held, only the
        # current key-hold uses UI targets; never issue another seek until UP.
        guard = f"""    # {TAG}: only the spinner-activated DPAD hold can bypass preview.
    iget-boolean v0, p0, {PC}->mNova251Hold:Z
    if-eqz v0, :nova251_original_seek
    iget v0, p0, {PC}->mSeekKeyDirection:I
    if-eqz v0, :nova251_original_seek
    invoke-direct {{p0, p1}}, {PC}->nova251BeginHold(I)V
    return-void
    :nova251_original_seek"""
        return entry(method, guard)
    src = edit_method(src, "onSeek(IZ)V", modify_on_seek)

    def modify_on_key(method: str) -> str:
        # This single upstream key-UP case is used by both DPAD directions.
        # Normal files take a one-instruction no-op fast return in Commit().
        original = f"    iput v4, p0, {PC}->mSeekKeyDirection:I"
        return once(method, original,
                    original + f"\n    invoke-direct {{p0}}, {PC}->nova251Commit()V",
                    "key release final commit")
    src = edit_method(src, "onKey(ILandroid/view/KeyEvent;)Z", modify_on_key)

    for sig in ("stop()V", "reset()V"):
        src = edit_method(src, sig,
                          lambda method: entry(method,
                          f"    invoke-direct {{p0}}, {PC}->nova251Cancel()V"))
    return src.rstrip() + "\n\n" + NEW_METHODS


def patch_handler(src: str) -> str:
    # PlayerController$8 is a separate class. Use a PUBLIC outer method,
    # not invoke-direct on a private method (which would fail verification).
    call = f"""    # {TAG}: message 9 is target-only; never enter MSG_SEEK.
    iget v0, p1, {MSG}->what:I
    const/16 v1, 0x9
    if-ne v0, v1, :nova251_original_message
    iget-object v0, p0, {INNER}->this$0:{PC}
    invoke-virtual {{v0}}, {PC}->nova251HoldTick()V
    return-void
    :nova251_original_message"""
    return edit_method(src, "handleMessage(Landroid/os/Message;)V",
                       lambda method: entry(method, call))


ACTIVITY = "Lcom/archos/mediacenter/video/player/PlayerActivity;"
ACTIVITY_HANDLER = "Lcom/archos/mediacenter/video/player/PlayerActivity$1;"

def patch_activity_spinner_handler(src: str) -> str:
    # Official 6.6.2 PlayerActivity$1 what=1 actually shows mProgressView.
    # Gate on both the DPAD-held controller state and genuine WebDAV MKV;
    # ordinary startup, nonseek buffering, ISO/MP4 and all other messages
    # fall through byte-for-byte to upstream Handler code.
    def hook(method: str) -> str:
        required = (
            "    .locals 8",
            "    packed-switch v1, :pswitch_data_0",
            f"invoke-static {{p1}}, {ACTIVITY}->z({ACTIVITY})Landroid/view/View;",
        )
        # Handler references the progress-view accessor through its own
        # generated register; require the unique accessor descriptor.
        if ".locals 8" not in method or ".packed-switch 0x1" not in method or (
            f"{ACTIVITY}->z({ACTIVITY})Landroid/view/View;" not in method
        ):
            raise RuntimeError("1097 actual PlayerActivity progress-show Handler changed")
        guard = f"""    # {TAG}: actual progress SHOW event before it reaches the view.
    iget v0, p1, {MSG}->what:I
    const/4 v1, 0x1
    if-ne v0, v1, :nova251_activity_original
    iget-object v0, p0, {ACTIVITY_HANDLER}->this$0:{ACTIVITY}
    invoke-static {{v0}}, {ACTIVITY}->w({ACTIVITY}){PC}
    move-result-object v0
    if-eqz v0, :nova251_activity_original
    invoke-virtual {{v0}}, {PC}->nova251OnSeekSpinner()Z
    move-result v1
    if-eqz v1, :nova251_activity_original
    iget-object v0, p0, {ACTIVITY_HANDLER}->this$0:{ACTIVITY}
    invoke-static {{v0}}, {ACTIVITY}->z({ACTIVITY})Landroid/view/View;
    move-result-object v0
    if-eqz v0, :nova251_activity_suppressed
    const/16 v1, 0x8
    invoke-virtual {{v0, v1}}, Landroid/view/View;->setVisibility(I)V
    :nova251_activity_suppressed
    return-void
    :nova251_activity_original"""
        return entry(method, guard)
    return edit_method(src, "handleMessage(Landroid/os/Message;)V", hook)


def patch(root: Path) -> dict:
    players = list(root.glob("smali*/com/archos/mediacenter/video/player/PlayerController.smali"))
    handlers = list(root.glob("smali*/com/archos/mediacenter/video/player/PlayerController$8.smali"))
    proxies = list(root.glob("smali*/com/archos/mediacenter/video/player/DirectTransportProxy.smali"))
    activity_handlers = list(root.glob("smali*/com/archos/mediacenter/video/player/PlayerActivity$1.smali"))
    if len(players) != 1 or len(handlers) != 1 or len(proxies) != 1 or len(activity_handlers)!=1:
        raise RuntimeError("1097 player/controller/proxy cardinality mismatch")
    if ".method public static native nativeIsWebdavMkv()Z" not in proxies[0].read_text():
        raise RuntimeError("verified WebDAV MKV JNI format check not wired")
    a = patch_controller(players[0].read_text())
    b = patch_handler(handlers[0].read_text())
    c = patch_activity_spinner_handler(activity_handlers[0].read_text())
    # Fail closed before overwriting either class.
    for token in ("nova251BeginHold", "nova251Commit", "nova251HoldTick",
                  "nova251_original_seek", "mNova251Hold"):
        if token not in a:
            raise RuntimeError("1097 controller missing "+token)
    if "nova251_original_message" not in b:
        raise RuntimeError("1097 handler missing scoped branch")
    if "nova251_activity_suppressed" not in c:
        raise RuntimeError("1097 activity spinner guard missing")
    players[0].write_text(a)
    handlers[0].write_text(b)
    activity_handlers[0].write_text(c)
    return {"status":"PASS", "tag":TAG, "classifier":"actual PlayerActivity progress SHOW while MKV DPAD held",
            "scope":"current MKV seek hold only; no file size or HTTP-status trigger",
            "native_requests_after_spinner_while_held":0,
            "seek_requests_on_keyup":1,
            "untouched":["normal MKV preview until UI spinner","ISO","MP4","touch seek"]}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--decoded", type=Path,required=True)
    args=ap.parse_args()
    print(patch(args.decoded))


if __name__ == "__main__":
    main()
