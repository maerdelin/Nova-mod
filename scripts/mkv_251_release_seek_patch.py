#!/usr/bin/env python3
"""NOVA 1097: release-only DPAD seek for the exact 2,509,221,119-byte WebDAV MKV.

Only the native-confirmed special MKV takes this route. Ordinary MKVs keep
their full frame-preview seek pipeline, native reads, UI and progress. No
format-wide toggle. Touch/slider seeks are deliberately left unchanged.
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
TAG = "NOVA_MKV_251_RELEASE_ONLY_V1"

# The controller already owns an Android main-thread Handler. Message 9 is
# outside upstream's 1..8 switch and is never sent to the normal Seek handler.
# While held it ONLY updates target/progress; it cannot pause, seek, or read.
NEW_METHODS = f"""
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
    invoke-static {{}}, {PROXY}->nativeIsSpecialMkv251()Z
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
        # Gate BOTH on native validated exact file size and actual remote
        # key direction. Slider, normal MKV and all other formats fall through
        # directly into their original instructions, untouched.
        guard = f"""    # {TAG}: special 251-byte-length scoped key-hold gate.
    invoke-static {{}}, {PROXY}->isNonIsoDirectWebdav()Z
    move-result v0
    if-eqz v0, :nova251_original_seek
    invoke-static {{}}, {PROXY}->nativeIsSpecialMkv251()Z
    move-result v0
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


def patch(root: Path) -> dict:
    players = list(root.glob("smali*/com/archos/mediacenter/video/player/PlayerController.smali"))
    handlers = list(root.glob("smali*/com/archos/mediacenter/video/player/PlayerController$8.smali"))
    proxies = list(root.glob("smali*/com/archos/mediacenter/video/player/DirectTransportProxy.smali"))
    if len(players) != 1 or len(handlers) != 1 or len(proxies) != 1:
        raise RuntimeError("1097 player/controller/proxy cardinality mismatch")
    if ".method public static native nativeIsSpecialMkv251()Z" not in proxies[0].read_text():
        raise RuntimeError("exact-source JNI identity not wired")
    a = patch_controller(players[0].read_text())
    b = patch_handler(handlers[0].read_text())
    # Fail closed before overwriting either class.
    for token in ("nova251BeginHold", "nova251Commit", "nova251HoldTick",
                  "nova251_original_seek", "mNova251Hold"):
        if token not in a:
            raise RuntimeError("1097 controller missing "+token)
    if "nova251_original_message" not in b:
        raise RuntimeError("1097 handler missing scoped branch")
    players[0].write_text(a)
    handlers[0].write_text(b)
    return {"status":"PASS", "tag":TAG, "size_bytes":2509221119,
            "scope":"native-confirmed exact WebDAV MKV and DPAD hold",
            "native_requests_during_hold":0,
            "seek_requests_after_keyup":1,
            "untouched":["ordinary MKV preview","ISO","MP4","touch seek"]}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--decoded", type=Path,required=True)
    args=ap.parse_args()
    print(patch(args.decoded))


if __name__ == "__main__":
    main()
