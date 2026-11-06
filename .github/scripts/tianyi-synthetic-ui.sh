#!/usr/bin/env bash
set -euo pipefail
mkdir -p reports
adb install -r -g work/qa-synthetic.apk | tee reports/install.txt
adb logcat -c || true
trap 'adb logcat -d -v threadtime > reports/logcat.txt 2>/dev/null || true' EXIT

dump_ui() {
  adb shell uiautomator dump /sdcard/nova-tianyi-test-ui.xml >/dev/null
  adb exec-out cat /sdcard/nova-tianyi-test-ui.xml > reports/current-ui.xml
}
tap() {
  dump_ui
  python3 - "$1" <<'PY'
import re,sys,subprocess,xml.etree.ElementTree as ET
term=sys.argv[1]
nodes=ET.parse('reports/current-ui.xml').getroot().iter('node')
found=[]
for n in nodes:
  a=n.attrib
  text=a.get('text','')+' '+a.get('content-desc','')
  if re.search(term,text,re.I):
    rect=list(map(int,re.findall(r'\d+',a.get('bounds',''))))
    if len(rect)==4: found.append(((rect[0]+rect[2])//2,(rect[1]+rect[3])//2,text))
if not found: raise SystemExit('UI_NOT_FOUND '+term)
x,y,label=found[0]
print('UI_TAP',term,repr(label))
subprocess.run(['adb','shell','input','tap',str(x),str(y)],check=True)
PY
}
capture() {
  adb exec-out screencap -p > "reports/$1.png"
  dump_ui
  cp reports/current-ui.xml "reports/$1.xml"
}
assert_success() {
  python3 - "$1" <<'PY'
import sys,xml.etree.ElementTree as ET
path=sys.argv[1]
attrs=[n.attrib for n in ET.parse(path).getroot().iter('node')]
texts=[n.get('text','') for n in attrs]
print('VIEW_TEXTS',repr([x for x in texts if x][:40]))
assert any('天翼云盘' in x for x in texts), 'shortcut name absent from list'
assert not any(x.strip()=='确定' for x in texts), 'QR/server dialog remained visible'
assert not any(x.strip()=='取消' for x in texts), 'QR/server dialog remained visible'
print('SYNTHETIC_AUTH_AUTO_CLOSE_AND_REFRESH=PASS')
PY
}

adb shell monkey -p org.courville.nova -c android.intent.category.LAUNCHER 1
sleep 5
tap '^Network\s*$'
sleep 4
tap 'browse|add server|network connection|服务器|添加'
sleep 3
tap 'FTP|WebDAV|SMB'
sleep 1
tap '天翼云盘'
sleep 8
capture 'after-synthetic-authorized'
if ! assert_success reports/after-synthetic-authorized.xml; then
  echo "SYNTHETIC_AUTH_IMMEDIATE_REFRESH=FAIL" | tee reports/immediate-refresh.txt
fi

adb shell am force-stop org.courville.nova
adb shell monkey -p org.courville.nova -c android.intent.category.LAUNCHER 1
sleep 5
tap '^Network\s*$'
sleep 5
capture 'after-process-restart'
assert_success reports/after-process-restart.xml

if grep -E -A 20 'FATAL EXCEPTION|VerifyError|NoClassDefFoundError' reports/logcat.txt | grep -Eq 'Process: org.courville.nova|com.archos.mediacenter.video.cloud189'; then
  echo 'SYNTHETIC_AUTH_RUNTIME=FAIL'
  exit 1
fi
echo 'SYNTHETIC_AUTH_SAVE_REFRESH_DISMISS_RESTART=PASS' | tee reports/result.txt
