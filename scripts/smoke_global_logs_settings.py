#!/usr/bin/env python3
"""Runtime check of the real Settings checkbox; run only on fresh CI emulator.

No forced setting values, root, pm clear, or application-data mutation.
UI changes are performed through the actual displayed preference control.
"""
import json
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from argparse import ArgumentParser

PACKAGE="org.courville.nova"
ACTIVITY="com.archos.mediacenter.video.utils.VideoPreferencesActivity"

def adb(*args, timeout=50):
    p=subprocess.run(["adb",*args],stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,text=True,timeout=timeout)
    if p.returncode:raise RuntimeError("ADB %s: %s"%(args,p.stdout))
    return p.stdout

def dump():
    adb("shell","uiautomator","dump","/sdcard/nova-global-logs-ui.xml",timeout=55)
    xml=adb("shell","cat","/sdcard/nova-global-logs-ui.xml")
    return ET.fromstring(xml[xml.index("<?xml"):])

def locate(root):
    for parent in root.iter():
        children=list(parent)
        for node in children:
            if node.get("text")=="日志":
                checkboxes=[x for x in parent.iter() if x.get("checkable")=="true"]
                if not checkboxes:
                    checkboxes=[x for x in root.iter() if x.get("checkable")=="true"]
                return node,checkboxes
    return None,[]

def click_bounds(node):
    nums=[int(x) for x in re.findall(r"\d+",node.get("bounds",""))]
    if len(nums)!=4:raise RuntimeError("Unable to locate checkbox bounds")
    adb("shell","input","tap",str((nums[0]+nums[2])//2),str((nums[1]+nums[3])//2))

def find_scroll():
    adb("shell","am","start","-W","-n",PACKAGE+"/"+ACTIVITY)
    for i in range(24):
        root=dump()
        item,boxes=locate(root)
        if item is not None:return item,boxes
        adb("shell","input","swipe","540","1440","540","310","310")
    raise RuntimeError("The Logs checkbox is not visible below Licenses")

def checked(boxes):
    for x in boxes:
        if x.get("checkable")=="true":
            return x.get("checked")=="true"
    return None

def main():
    ap=ArgumentParser()
    ap.add_argument("--reports",type=Path,required=True)
    args=ap.parse_args()
    args.reports.mkdir(parents=True,exist_ok=True)
    result={"status":"FAIL","key":"nova_logs_enabled","default":"true","tested":[]}
    try:
        item,boxes=find_scroll()
        if checked(boxes) is False:raise RuntimeError("New install default must be checked")
        result["tested"].append("logs preference visible beneath Licenses")
        # Trigger actual preference onChanged via UI tap, not a mock value.
        click_bounds(item)
        time.sleep(1)
        root=dump()
        found,boxes=locate(root)
        if found is None:raise RuntimeError("Logs vanished after disabling")
        if checked(boxes) is True:raise RuntimeError("Checkbox remained checked after tap")
        result["tested"].append("unchecked by actual Settings tap")
        click_bounds(found)
        time.sleep(1)
        root=dump()
        found,boxes=locate(root)
        if found is None or checked(boxes) is False:
            raise RuntimeError("Unable to re-enable diagnostics using Settings")
        result["tested"].append("rechecked by actual Settings tap")
        result["status"]="PASS"
        print("NOVA_GLOBAL_LOGS_UI_CHECKBOX=PASS")
    finally:
        (args.reports/"global-logs-settings.json").write_text(json.dumps(result,indent=2)+"\n")
        print(json.dumps(result,indent=2))

if __name__=="__main__":main()
