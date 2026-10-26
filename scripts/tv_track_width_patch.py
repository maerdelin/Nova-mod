#!/usr/bin/env python3
"""Only double expanded TV audio/subtitle track cards. No other layouts changed."""
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
        m=replace1(m,anchor,anchor+"\n\n    const-string v2, \""+TAG+"\"\n\n    invoke-virtual {v1, v2}, Landroid/view/View;->setTag(Ljava/lang/Object;)V")
    return s[:start]+m+s[end:]
def card(s):
    start,end,m=section(s,"public focus(Z)V")
    if ".locals 14" not in m:raise RuntimeError("TVCardView locals changed")
    anchor="    invoke-direct/range {v0 .. v9}, "+CARD[:-1]+"$ExpandAnimation;-><init>("
    additional="""    # NOVA_TV_TRACK_POPUP_WIDTH_2X_V1
    invoke-virtual {p0}, Landroid/view/View;->getTag()Ljava/lang/Object;

    move-result-object v10

    const-string v11, "nova_tv_track_wide_v1"

    invoke-virtual {v11, v10}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v10

    if-eqz v10, :nova_track_width_normal

    div-int/lit8 v10, v3, 0x2

    sub-int/2addr v2, v10

    mul-int/lit8 v3, v3, 0x2

    :nova_track_width_normal

"""
    if m.count("    :cond_9\n")!=1:raise RuntimeError("Missing focused/unfocused label")
    focused,unfocused=m.split("    :cond_9",1)
    focused=replace1(focused,anchor,additional+anchor)
    m=focused+"    :cond_9"+unfocused
    return s[:start]+m+s[end:]
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
    report.write_text(json.dumps({"status":"PASS","marker":"NOVA_TV_TRACK_POPUP_WIDTH_2X_V1",
        "target":["mSubtitleTVCardView","mAudioTracksTVCardView"],"width_multiplier":2,
        "recenter":True,"other_card_widths_unchanged":True},indent=2))
    print("NOVA_TV_TRACK_POPUP_WIDTH_2X_V1=PASS")
