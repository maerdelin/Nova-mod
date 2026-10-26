#!/usr/bin/env python3
"""NOVA_TV_TRACK_LAYOUT_V2: double only TV audio/subtitle cards, fix spacing and centered header; all other popups unchanged."""
import json
from pathlib import Path
TAG="nova_tv_track_wide_v1"
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
    if ".locals 10" not in m:raise RuntimeError("PlayerActivity locals changed")
    for field in ("mSubtitleTVCardView","mAudioTracksTVCardView"):
        anchor="    iput-object v1, p0, "+ACT+"->"+field+":"+CARD
        changed=(anchor+
                 "\n\n    const-string v2, \""+TAG+"\""+
                 "\n\n    invoke-virtual {v1, v2}, Landroid/view/View;->setTag(Ljava/lang/Object;)V"+
                 "\n\n    invoke-virtual {v1}, Landroid/view/View;->getParent()Landroid/view/ViewParent;"+
                 "\n\n    move-result-object v2"+
                 "\n\n    check-cast v2, Landroid/view/View;"+
                 "\n\n    invoke-virtual {v1, v2}, "+CARD+"->setParentView(Landroid/view/View;)V")
        m=replace1(m,anchor,changed)
    return s[:start]+m+s[end:]

# Expanded width is 2.4*originalW and card center is originalX+0.5W.
# Thus the expanded left edge is originalX-0.7W. Shift each other
# card's ROOT WRAPPER by 0.7W+24px; the original 20px gap grows to
# ~44px. On focus(false), restore translations to zero.
# Compare immutable originalX, not child order (bringToFront reorders it).
SPACING_METHOD = '''
.method private novaOffsetTrackNeighbors(Z)V
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
            '    :nova_track_skip_slave_tag\n\n'+slave)
    m=replace1(m,slave,copied)
    # Call from the stable focus(Z) entry instead of relying on a
    # compiler-dependent branch-label/next-instruction pairing.
    m=replace1(m,'    move v0, p1',
               '    move v0, p1\n\n    invoke-direct {p0, p1}, '+CARD+'->novaOffsetTrackNeighbors(Z)V')
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

    :nova_track_width_normal

"""
    if m.count("    :cond_9\n")!=1:raise RuntimeError("Focused/unfocused branch missing")
    focused,unfocused=m.split("    :cond_9\n",1)
    focused=replace1(focused,anchor,additional+anchor)
    m=focused+"    :cond_9\n"+unfocused
    result=s[:start]+m+s[end:]
    if ".method private novaOffsetTrackNeighbors(Z)V" in result:
        raise RuntimeError("Track neighbor adjustment already installed")
    return result[:start]+SPACING_METHOD+"\n"+result[start:]

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
    report.write_text(json.dumps({"status":"PASS","marker":"NOVA_TV_TRACK_LAYOUT_V2",
        "target":["mSubtitleTVCardView","mAudioTracksTVCardView"],"width_multiplier":2,
        "header_centered":True,"neighbor_gap_px":24,"recenter":True,"other_card_widths_unchanged":True},indent=2))
    print("NOVA_TV_TRACK_LAYOUT_V2=PASS")
