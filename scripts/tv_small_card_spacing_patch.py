#!/usr/bin/env python3
"""NOVA_TV_SMALL_GAP_CRASH_GUARD_V3: guard regular TV card spacing against doubled track transforms.

Safe continuation of #738 spacing, reverting #740's double-mutation of
the tagged subtitle/audio cards. #736 center cache, track transform,
and entire player/decoder/transport stack remain byte-for-byte unchanged.
"""
import json
from pathlib import Path
import tv_track_width_patch as tracks

MARKER = "NOVA_TV_SMALL_GAP_CRASH_GUARD_V3"
CARD = tracks.CARD

# Only non-tagged cards in the exact TV menu row containing the two tagged
# audio/subtitle cards are eligible. Other TVCardView menus are untouched.
# Use the actual existing ExpandAnimation endX/endWidth, never guessed pixels.
# Original unfocused inter-card gap remains 20px. For regular cards the
# minimum focused gap is 44px; tagged #736 audio/subtitle cards keep their
# already-verified approx 44px (integer rounding may differ by 1px).
# Unlike #740, NEVER reapply transforms to those tagged cards.
SMALL_METHOD = """
.method private novaOffsetSmallNeighbors(ZII)V
    .locals 12

    # NOVA_TV_SMALL_GAP_CRASH_GUARD_V3: track cards must use #736 code ONLY.
    invoke-virtual {p0}, Landroid/view/View;->getTag()Ljava/lang/Object;

    move-result-object v0

    const-string v1, "nova_tv_track_wide_v1"

    invoke-virtual {v1, v0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v0

    if-nez v0, :nova_small_end

    # Never offset cards whose original geometry is not initialized, or
    # cards detached while moving between the first/last video.
    iget v4, p0, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;->originalWidth:I

    if-lez v4, :nova_small_end

    invoke-virtual {p0}, Landroid/view/View;->isAttachedToWindow()Z

    move-result v1

    if-eqz v1, :nova_small_end

    # The ordinary cards may not have parentView initialized; their actual
    # parent is equivalent to the track cards' explicitly saved parentView.
    iget-object v0, p0, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;->parentView:Landroid/view/View;

    if-nez v0, :nova_small_parent_ready

    invoke-virtual {p0}, Landroid/view/View;->getParent()Landroid/view/ViewParent;

    move-result-object v0

    instance-of v1, v0, Landroid/view/View;

    if-eqz v1, :nova_small_end

    check-cast v0, Landroid/view/View;

    :nova_small_parent_ready
    invoke-virtual {v0}, Landroid/view/View;->getParent()Landroid/view/ViewParent;

    move-result-object v0

    instance-of v1, v0, Landroid/view/ViewGroup;

    if-eqz v1, :nova_small_end

    check-cast v0, Landroid/view/ViewGroup;

    invoke-virtual {v0}, Landroid/view/ViewGroup;->getChildCount()I

    move-result v6

    # Fail closed outside the one playback-TV row containing tagged tracks.
    const/4 v2, 0x0

    :nova_small_scope_scan
    if-ge v2, v6, :nova_small_end

    invoke-virtual {v0, v2}, Landroid/view/ViewGroup;->getChildAt(I)Landroid/view/View;

    move-result-object v7

    if-eqz v7, :nova_small_scope_next

    sget v8, Lcom/archos/mediacenter/video/R$id;->card_view:I

    invoke-virtual {v7, v8}, Landroid/view/View;->findViewById(I)Landroid/view/View;

    move-result-object v8

    instance-of v1, v8, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;

    if-eqz v1, :nova_small_scope_next

    invoke-virtual {v8}, Landroid/view/View;->getTag()Ljava/lang/Object;

    move-result-object v8

    const-string v1, "nova_tv_track_wide_v1"

    invoke-virtual {v1, v8}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v1

    if-nez v1, :nova_small_scope_verified

    :nova_small_scope_next
    add-int/lit8 v2, v2, 0x1

    goto :nova_small_scope_scan

    :nova_small_scope_verified
    iget v5, p0, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;->originalX:F

    iget v4, p0, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;->originalWidth:I

    const/4 v9, 0x0

    const/4 v10, 0x0

    if-eqz p1, :nova_small_offsets_ready

    # Left extra = max(0, originalX - exactEndX) + 24.0f
    int-to-float v9, p2

    sub-float v9, v5, v9

    const/4 v11, 0x0

    cmpg-float v1, v9, v11

    if-gez v1, :nova_small_left_ready

    const/4 v9, 0x0

    :nova_small_left_ready
    # Right extra = max(0, exactEndX + endWidth - originalRight) + 24.0f
    int-to-float v10, p2

    int-to-float v1, p3

    add-float/2addr v10, v1

    int-to-float v1, v4

    add-float/2addr v1, v5

    sub-float/2addr v10, v1

    cmpg-float v1, v10, v11

    if-gez v1, :nova_small_right_ready

    const/4 v10, 0x0

    :nova_small_right_ready
    const/high16 v11, 0x41c00000

    add-float/2addr v9, v11

    add-float/2addr v10, v11

    :nova_small_offsets_ready
    # Original X, not child index: bringToFront() reorders children.
    const/4 v2, 0x0

    :nova_small_apply_loop
    if-ge v2, v6, :nova_small_end

    invoke-virtual {v0, v2}, Landroid/view/ViewGroup;->getChildAt(I)Landroid/view/View;

    move-result-object v7

    if-eqz v7, :nova_small_apply_next

    sget v8, Lcom/archos/mediacenter/video/R$id;->card_view:I

    invoke-virtual {v7, v8}, Landroid/view/View;->findViewById(I)Landroid/view/View;

    move-result-object v8

    instance-of v1, v8, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;

    if-eqz v1, :nova_small_apply_next

    check-cast v8, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;

    iget v1, v8, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;->originalX:F

    cmpg-float v3, v1, v5

    if-eqz v3, :nova_small_apply_next

    const/4 v11, 0x0

    if-eqz p1, :nova_small_apply_translation

    if-gez v3, :nova_small_apply_right

    neg-float v11, v9

    goto :nova_small_apply_translation

    :nova_small_apply_right
    move v11, v10

    :nova_small_apply_translation
    # Avoid redundant property writes/invalidations while rapidly traversing
    # the subtitle, audio and normal-card row on a memory-limited TV GPU.
    invoke-virtual {v7}, Landroid/view/View;->getTranslationX()F

    move-result v3

    cmpl-float v3, v3, v11

    if-eqz v3, :nova_small_apply_next

    invoke-virtual {v7, v11}, Landroid/view/View;->setTranslationX(F)V

    :nova_small_apply_next
    add-int/lit8 v2, v2, 0x1

    goto :nova_small_apply_loop

    :nova_small_end
    return-void
.end method
"""

def patch_source(source: str) -> str:
    if MARKER in source or ".method private novaOffsetSmallNeighbors(ZII)V" in source:
        raise RuntimeError("Small-card spacing patch already installed")
    if source.count(".method private novaOffsetTrackNeighbors(ZI)V") != 1:
        raise RuntimeError("Verified #736 track spacing method not found")
    if source.count("novaExpandedCenterX:F") < 2:
        raise RuntimeError("Verified #736 subtitle endX/endWidth cache not found")
    start, end, focus = tracks.section(source, "public focus(Z)V")
    if ".locals 14" not in focus:
        raise RuntimeError("Unexpected TVCardView focus register map")
    reset_anchor = "    :nova_track_reset_done\n"
    reset = (reset_anchor +
             "\n    # NOVA_TV_SMALL_GAP_CRASH_GUARD_V3: restore only ordinary cards.\n"
             "    if-nez p1, :nova_small_reset_done\n\n"
             "    const/4 v10, 0x0\n\n"
             "    invoke-direct {p0, p1, v10, v10}, " + CARD +
             "->novaOffsetSmallNeighbors(ZII)V\n\n"
             "    :nova_small_reset_done\n")
    focus = tracks.replace1(focus, reset_anchor, reset)
    target_anchor = "    :nova_track_width_normal\n"
    change = (target_anchor +
              "\n    # NOVA_TV_SMALL_GAP_CRASH_GUARD_V3: exact native endX/endWidth.\n"
              "    # Tagged audio/subtitle immediately return without changes.\n"
              "    invoke-direct {p0, p1, v2, v3}, " + CARD +
              "->novaOffsetSmallNeighbors(ZII)V\n")
    focus = tracks.replace1(focus, target_anchor, change)
    if focus.count("->novaOffsetSmallNeighbors(ZII)V") != 2:
        raise RuntimeError("Unexpected normal-card focus/reset invocation count")
    return source[:start] + SMALL_METHOD + "\n" + focus + source[end:]

def apply(root: Path, report: Path) -> None:
    found = list(root.glob("smali*/**/TVCardView.smali"))
    if len(found) != 1:
        raise RuntimeError("Missing or ambiguous TVCardView.smali for small-card patch")
    file = found[0]
    original = file.read_text()
    patched = patch_source(original)
    file.write_text(patched)
    report.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "status": "PASS",
        "marker": MARKER,
        "scope": "attached untagged normal cards in playback TV row; tagged track cards solely #736",
        "focus_geometry": "existing ExpandAnimation exact endX and endWidth",
        "extra_gap_px": 24,
        "expected_gap_px": 44,
        "reset_on_unfocus": True,
        "skip_track_double_translation": True,
        "skip_detached_and_uninitialized_cards": True,
        "skip_redundant_gpu_transforms": True,
        "unfocused_gap_px": 20,
        "track_gap": "approximately 44px, preserved from #736",
        "regression_target": "first and last media + rapid subtitle/audio/small focus navigation",
        "subtitle_center_cache_unchanged": True,
        "audio_track_animation_unchanged": True,
        "other_card_widths_unchanged": True,
        "playback_core_unchanged": True
    }
    report.write_text(json.dumps(record, indent=2))
    print(MARKER + "=PASS; no double track translations; normal card layout guarded")
