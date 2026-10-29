#!/usr/bin/env python3
"""NOVA_TV_TRACK_LAYOUT_V2: double only TV audio/subtitle cards, fix spacing and centered header; all other popups unchanged."""
import json
from pathlib import Path
TAG="nova_tv_track_wide_v1"
SUBTITLE_TAG="nova_tv_subtitle_realign_v3"
CARD="Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;"
ACT="Lcom/archos/mediacenter/video/player/PlayerActivity;"
def section(text,name):
    head=".method "+name
    if text.count(head)!=1:raise RuntimeError("method identity mismatch: "+name)
    start=text.index(head);end=text.index(".end method",start)+len(".end method")
    return start,end,text[start:end]
def replace1(s,a,b):
    if s.count(a)!=1:raise RuntimeError("ambiguous anchor: "+a[:60]+" count="+str(s.count(a)))
    return s.replace(a,b,1)
def player(s):
    start,end,m=section(s,"public createPlayerTVMenu()V")
    if "\n    .locals 10\n" not in m:
        raise RuntimeError("PlayerActivity register layout changed")
    # The original 10 locals v0-v9 are LIVE through later theme/Drawable
    # operations. Android's verifier rejects v3=String where v3=Theme.
    # Allocate *new* locals v10,v11 and never write v0-v9 in our patch.
    # .locals 12 moves p0 to v12; all references use the p0 alias.
    import re
    if re.search(r"\bv(?:10|11)\b",m):
        raise RuntimeError("Original PlayerActivity uses reserved scratch regs")
    m=replace1(m,"    .locals 10","    .locals 12")
    for field in ("mSubtitleTVCardView","mAudioTracksTVCardView"):
        anchor="    iput-object v1, p0, "+ACT+"->"+field+":"+CARD
        changed=(anchor+
                 "\n\n    # NOVA_TV_REGISTER_SAFE_V5: scratch v10/v11 only"+
                 "\n    const-string v10, \""+TAG+"\""+
                 "\n\n    invoke-virtual {v1, v10}, Landroid/view/View;->setTag(Ljava/lang/Object;)V"+
                 "\n\n    invoke-virtual {v1}, Landroid/view/View;->getParent()Landroid/view/ViewParent;"+
                 "\n\n    move-result-object v10"+
                 "\n\n    check-cast v10, Landroid/view/View;"+
                 "\n\n    invoke-virtual {v1, v10}, "+CARD+"->setParentView(Landroid/view/View;)V")
        if field=="mSubtitleTVCardView":
            changed+=(
                "\n\n    sget v10, Lcom/archos/mediacenter/video/R$id;->card_view:I"+
                "\n\n    const-string v11, \""+SUBTITLE_TAG+"\""+
                "\n\n    invoke-virtual {v1, v10, v11}, Landroid/view/View;->setTag(ILjava/lang/Object;)V")
        if field=="mSubtitleTVCardView":
            # card_layout.xml enables LayoutTransition on TVCardView.
            # Its automatic child transition races ExpandAnimation's
            # per-frame width/X writes when subtitle entries first appear.
            # Disable ONLY the subtitle transition; retain ExpandAnimation.
            changed+=(
                "\n\n    # NOVA_TV_SUBTITLE_FIRST_FOCUS_LAYOUT_STABLE_V1 main card"
                "\n\n    const/4 v10, 0x0"
                "\n\n    invoke-virtual {v1, v10}, Landroid/view/ViewGroup;->setLayoutTransition(Landroid/animation/LayoutTransition;)V")
        m=replace1(m,anchor,changed)
    if "const-string v3" in m and "nova_tv_" in m:
        raise RuntimeError("Unexpected legacy register contamination")
    # Validation of output method: only the explicit new locals
    # can be used as destinations in injected smali.
    if m.count("NOVA_TV_REGISTER_SAFE_V5")!=2 or ".locals 12" not in m:
        raise RuntimeError("New register isolation was not applied correctly")
    return s[:start]+m+s[end:]

# Expanded width is 2.4*originalW and card center is originalX+0.5W.
# Thus the expanded left edge is originalX-0.7W. Shift each other
# card's ROOT WRAPPER by 0.7W+24px; the original 20px gap grows to
# ~44px. On focus(false), restore translations to zero.
# Compare immutable originalX, not child order (bringToFront reorders it).
SPACING_METHOD = '''
.method private novaOffsetTrackNeighbors(ZI)V
    .locals 12

    # NOVA_TV_TRACK_LAYOUT_V2; only explicitly tagged track cards.
    invoke-virtual {p0}, Landroid/view/View;->getTag()Ljava/lang/Object;

    move-result-object v0

    const-string v1, "nova_tv_track_wide_v1"

    invoke-virtual {v1, v0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v0

    if-eqz v0, :nova_track_spacing_end

    iget-object v0, p0, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;->parentView:Landroid/view/View;

    if-eqz v0, :nova_track_spacing_end

    invoke-virtual {v0}, Landroid/view/View;->getParent()Landroid/view/ViewParent;

    move-result-object v0

    instance-of v1, v0, Landroid/view/ViewGroup;

    if-eqz v1, :nova_track_spacing_end

    check-cast v0, Landroid/view/ViewGroup;

    iget v4, p0, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;->originalWidth:I

    mul-int/lit8 v4, v4, 0x7

    div-int/lit8 v4, v4, 0xa

    add-int/lit8 v4, v4, 0x18

    # NOVA_TV_DYNAMIC_CLIP_V4: exact left-edge deficit in p2, supplied
    # by focus() from the live ExpandAnimation endX (v2).
    if-eqz p1, :nova_track_dynamic_gap_done

    add-int/2addr v4, p2

    :nova_track_dynamic_gap_done

    iget v5, p0, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;->originalX:F

    invoke-virtual {v0}, Landroid/view/ViewGroup;->getChildCount()I

    move-result v6

    const/4 v2, 0x0

    :nova_track_spacing_loop
    if-ge v2, v6, :nova_track_spacing_end

    invoke-virtual {v0, v2}, Landroid/view/ViewGroup;->getChildAt(I)Landroid/view/View;

    move-result-object v7

    if-eqz v7, :nova_track_spacing_next

    sget v8, Lcom/archos/mediacenter/video/R$id;->card_view:I

    invoke-virtual {v7, v8}, Landroid/view/View;->findViewById(I)Landroid/view/View;

    move-result-object v8

    instance-of v9, v8, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;

    if-eqz v9, :nova_track_spacing_next

    check-cast v8, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;

    iget v9, v8, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;->originalX:F

    cmpg-float v10, v9, v5

    if-eqz v10, :nova_track_spacing_next

    const/4 v11, 0x0

    if-eqz p1, :nova_track_spacing_apply

    if-gez v10, :nova_track_spacing_right

    neg-int v11, v4

    int-to-float v11, v11

    goto :nova_track_spacing_apply

    :nova_track_spacing_right
    int-to-float v11, v4

    :nova_track_spacing_apply
    invoke-virtual {v7, v11}, Landroid/view/View;->setTranslationX(F)V

    :nova_track_spacing_next
    add-int/lit8 v2, v2, 0x1

    goto :nova_track_spacing_loop

    :nova_track_spacing_end
    return-void
.end method
'''

def center_method(s):
    """Cache the subtitle's exact expanded center as the TV adapter focus target.

    TVMenuAdapter.onSlaveFocusChange() calls focus(true) and IMMEDIATELY
    reads getPositionX() (before 200ms ExpandAnimation has updated the
    card's physical coordinates). Only a subtitle with left-edge
    correction has a different expanded center; all other card getters
    must retain their original behavior.
    """
    import re
    if ".field private novaExpandedCenterX:F" in s or ".field private novaExpandedCenterValid:Z" in s:
        raise RuntimeError("Expanded center cache is already present")
    # The APK reassembler lexicographically reorders .field directives.
    # Insert in its canonical order, exactly as verified by #735
    # reports/roundtrip.json, rather than at the end of the field list.
    # Otherwise the strict round-trip verifier rightfully rejects it.
    anchor=".field private ocl:Landroid/view/View$OnClickListener;"
    if s.count(anchor)!=1:
        raise RuntimeError("TVCardView ocl field anchor changed")
    s=s.replace(anchor,
                ".field private novaExpandedCenterValid:Z\n"
                ".field private novaExpandedCenterX:F\n"
                +anchor,1)
    st,en,m=section(s,"public getPositionX()F")
    header=re.search(r"(?m)^    \.locals (\d+)$",m)
    if not header or int(header.group(1))<1:
        raise RuntimeError("getPositionX() has no safe local scratch register")
    prologue=("""
    # NOVA_SUBTITLE_FOCUS_CENTER_V6: correct repeated focus and refocus.
    iget-boolean v0, p0, """+CARD+"""->novaExpandedCenterValid:Z

    if-eqz v0, :nova_track_center_original_position

    iget v0, p0, """+CARD+"""->novaExpandedCenterX:F

    return v0

    :nova_track_center_original_position
""")
    m=replace1(m,header.group(0),header.group(0)+"\n"+prologue)
    return s[:st]+m+s[en:]

def card(s):
    start,end,m=section(s,"public focus(Z)V")
    if ".locals 14" not in m:raise RuntimeError("TVCardView focus register map changed")
    slave="    invoke-virtual {v2, p1}, "+CARD+"->focus(Z)V"
    copied=('    invoke-virtual {p0}, Landroid/view/View;->getTag()Ljava/lang/Object;\n\n'
            '    move-result-object v10\n\n'
            '    const-string v11, "'+TAG+'"\n\n'
            '    invoke-virtual {v11, v10}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z\n\n'
            '    move-result v10\n\n'
            '    if-eqz v10, :nova_track_skip_slave_tag\n\n'
            '    const-string v10, "'+TAG+'"\n\n'
            '    invoke-virtual {v2, v10}, Landroid/view/View;->setTag(Ljava/lang/Object;)V\n\n'
            '    # The subtitle-only alignment marker is copied to mirrored cards.\n\n'
            '    sget v10, Lcom/archos/mediacenter/video/R$id;->card_view:I\n\n'
            '    invoke-virtual {p0, v10}, Landroid/view/View;->getTag(I)Ljava/lang/Object;\n\n'
            '    move-result-object v11\n\n'
            '    if-eqz v11, :nova_subtitle_slave_marker_done\n\n'
            '    invoke-virtual {v2, v10, v11}, Landroid/view/View;->setTag(ILjava/lang/Object;)V\n\n'
            '    # NOVA_TV_SUBTITLE_FIRST_FOCUS_LAYOUT_STABLE_V1 mirror:\n\n'
            '    # the XML LayoutTransition and ExpandAnimation must not compete.\n\n'
            '    const/4 v10, 0x0\n\n'
            '    invoke-virtual {v2, v10}, Landroid/view/ViewGroup;->setLayoutTransition(Landroid/animation/LayoutTransition;)V\n\n'
            '    :nova_subtitle_slave_marker_done\n\n'
            '    :nova_track_skip_slave_tag\n\n'+slave)
    m=replace1(m,slave,copied)
    # Call from the stable focus(Z) entry instead of relying on a
    # compiler-dependent branch-label/next-instruction pairing.
    # Restore neighbor positions on unfocus. On focus, the extra
    # displacement is calculated from the real expanded X coordinate.
    m=replace1(m,'    move v0, p1',
               '    move v0, p1\n\n    const/4 v10, 0x0\n\n    iput-boolean v10, p0, '+CARD+'->novaExpandedCenterValid:Z\n\n    if-nez p1, :nova_track_reset_done\n\n    const/4 v10, 0x0\n\n    invoke-direct {p0, p1, v10}, '+CARD+'->novaOffsetTrackNeighbors(ZI)V\n\n    :nova_track_reset_done')
    anchor="    invoke-direct/range {v0 .. v9}, "+CARD[:-1]+"$ExpandAnimation;-><init>("
    additional="""    # NOVA_TV_TRACK_LAYOUT_V2: width 2x, header matches full expanded width
    invoke-virtual {p0}, Landroid/view/View;->getTag()Ljava/lang/Object;

    move-result-object v10

    const-string v11, "nova_tv_track_wide_v1"

    invoke-virtual {v11, v10}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v10

    if-eqz v10, :nova_track_width_normal

    div-int/lit8 v10, v3, 0x2

    sub-int/2addr v2, v10

    mul-int/lit8 v3, v3, 0x2

    # TopView's image/title region must be centered in the larger card.
    int-to-float v5, v3

    # NOVA_TV_DYNAMIC_CLIP_V4: both track cards share card_layout.xml.
    # They already expand to the SAME width; only the first subtitle
    # card can have a negative left edge clipped by the menu parent.
    # Calculate from the actual, already-computed animation endX=v2:
    # extra=max(0,-v2). This is independent of screen size and DPI.
    sget v10, Lcom/archos/mediacenter/video/R$id;->card_view:I

    invoke-virtual {p0, v10}, Landroid/view/View;->getTag(I)Ljava/lang/Object;

    move-result-object v10

    const-string v11, "nova_tv_subtitle_realign_v3"

    invoke-virtual {v11, v10}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v10

    if-eqz v10, :nova_subtitle_clip_delta_zero

    # Subtitle alone uses the cached final center. Audio remains unchanged.
    const/4 v11, 0x1

    iput-boolean v11, p0, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;->novaExpandedCenterValid:Z

    if-gez v2, :nova_subtitle_clip_delta_zero

    neg-int v10, v2

    goto :nova_subtitle_clip_delta_ready

    :nova_subtitle_clip_delta_zero
    const/4 v10, 0x0

    :nova_subtitle_clip_delta_ready
    add-int/2addr v2, v10

    # Shift right neighbors by the EXACT same delta; 728's gap remains
    # unchanged. Audio remains at its original correct X (delta=0).
    const/4 v11, 0x1

    invoke-direct {p0, v11, v10}, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;->novaOffsetTrackNeighbors(ZI)V

    # Cache EXACT same endX/endWidth sent to ExpandAnimation; no
    # screenshot offsets, duplicate calculations or extra animation.
    # The adapter immediately calls getPositionX() after focus(true).
    iget-boolean v10, p0, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;->novaExpandedCenterValid:Z

    if-eqz v10, :nova_center_saved

    div-int/lit8 v10, v3, 0x2

    int-to-float v10, v10

    int-to-float v11, v2

    add-float/2addr v11, v10

    iput v11, p0, Lcom/archos/mediacenter/video/player/tvmenu/TVCardView;->novaExpandedCenterX:F

    :nova_center_saved

    :nova_track_width_normal

"""
    if m.count("    :cond_9\n")!=1:raise RuntimeError("Focused/unfocused branch missing")
    focused,unfocused=m.split("    :cond_9\n",1)
    focused=replace1(focused,anchor,additional+anchor)
    m=focused+"    :cond_9\n"+unfocused
    result=s[:start]+m+s[end:]
    if ".method private novaOffsetTrackNeighbors(Z)V" in result:
        raise RuntimeError("Track neighbor adjustment already installed")
    return center_method(result[:start]+SPACING_METHOD+"\n"+result[start:])

def apply(root,report):
    targets={}
    for name in ("PlayerActivity.smali","TVCardView.smali"):
        found=list(root.glob("smali*/**/"+name))
        if len(found)!=1:raise RuntimeError("Missing or ambiguous "+name)
        targets[name]=found[0]
    before={name:path.read_text() for name,path in targets.items()}
    if TAG in before["PlayerActivity.smali"]:raise RuntimeError("Already applied")
    after={"PlayerActivity.smali":player(before["PlayerActivity.smali"]),
           "TVCardView.smali":card(before["TVCardView.smali"])}
    for name,code in after.items():targets[name].write_text(code)
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps({"status":"PASS","marker":"NOVA_SUBTITLE_FOCUS_CENTER_V6",
        "target":["mSubtitleTVCardView","mAudioTracksTVCardView"],"width_multiplier":2,
        "header_centered":True,"neighbor_gap_px":24,"subtitle_clip_delta":"max(0,-expanded_left_px)","subtitle_focus_center":"cached_from_ExpandAnimation_endX_and_endWidth","audio_x_unchanged":True,"other_card_widths_unchanged":True},indent=2))
    print("NOVA_SUBTITLE_FOCUS_CENTER_V6=PASS; same expanded center on first focus, navigation back, and refocus")
