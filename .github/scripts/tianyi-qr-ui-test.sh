#!/usr/bin/env bash
set -euo pipefail
mkdir -p reports
APK=testapk/dist/NOVA_Tianyi_Cloud_TEST_SIGNED.apk
adb install -r -g "$APK" | tee reports/install.txt
adb logcat -c || true
trap 'adb logcat -d -v threadtime > reports/logcat.txt || true' EXIT

dump_ui(){
  adb shell uiautomator dump /sdcard/nova-tianyi-ui.xml >/dev/null
  adb exec-out cat /sdcard/nova-tianyi-ui.xml > reports/current-ui.xml
}
tap_match(){
  local pattern="$1"
  dump_ui
  python3 - "$pattern" <<'PY'
import sys,xml.etree.ElementTree as ET,re,subprocess
p=sys.argv[1]
root=ET.parse("reports/current-ui.xml").getroot()
opts=[]
labels=[]
for node in root.iter("node"):
 a=node.attrib
 label=a.get("text","")+" "+a.get("content-desc","")
 if label.strip(): labels.append(label.strip())
 if re.search(p,label,re.I):
  bounds=a.get("bounds","")
  v=list(map(int,re.findall(r"\d+",bounds)))
  if len(v)==4:
   opts.append((label,(v[0]+v[2])//2,(v[1]+v[3])//2))
if not opts:
 print("AVAILABLE_UI_LABELS",repr(labels[:85]))
 raise SystemExit("NO_UI_MATCH:"+p)
label,x,y=opts[0]
print("UI_MATCH",repr(label),"tap",x,y)
subprocess.check_call(["adb","shell","input","tap",str(x),str(y)])
PY
}
screenshot(){
  adb exec-out screencap -p > "reports/$1.png"
  dump_ui
  cp reports/current-ui.xml "reports/$1.xml"
}
adb shell monkey -p org.courville.nova -c android.intent.category.LAUNCHER 1
sleep 5
screenshot "home"
# NOVA opens with its drawer already expanded on a fresh install.
tap_match '^Network\s*$'
sleep 5
screenshot "network"
tap_match 'browse|add server|add network|network connection|服务器|添加'
sleep 3
screenshot "dialog-before"
tap_match 'WebDAV|FTP|SMB'
sleep 1
screenshot "protocol-list"
tap_match '天翼云盘'
sleep 20
screenshot "tianyi-panel"
adb logcat -d -v threadtime > reports/logcat.txt
# Only treat a fatal crash of the NOVA process as a crash. System
# components can independently log the same NPE text and are irrelevant.
if grep -E -A 16 'FATAL EXCEPTION|VerifyError|NoClassDefFoundError' reports/logcat.txt | grep -Eq 'Process: org.courville.nova|com.archos.mediacenter.video.cloud189'; then
  echo "NOVA_TIANYI_QR_TEST=FAIL" | tee reports/result.txt
  exit 1
fi
python3 - <<'PY'
import xml.etree.ElementTree as ET
root=ET.parse('reports/tianyi-panel.xml').getroot()
nodes=[n.attrib for n in root.iter('node')]
assert any('天翼云盘' in n.get('text','') for n in nodes), 'Tianyi protocol not selected'
assert any(n.get('class','').endswith('ImageView') and n.get('bounds')!='[0,0][0,0]' for n in nodes), 'QR image widget not found'
assert not any(('失败' in n.get('text','') or '重试' in n.get('text','')) for n in nodes), 'Cloud login failed; QR panel shows error'
print('NOVA_TIANYI_QR_PANEL_WIDGET=PASS')
PY
echo "NOVA_TIANYI_QR_PANEL=DISPLAYED" | tee reports/result.txt
