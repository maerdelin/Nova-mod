#!/usr/bin/env bash
# Emulator-only integration test: no real 189Cloud account is used.
set -euo pipefail
mkdir -p reports
PACKAGE=org.courville.nova
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
print('UI_TAP',term,repr(label),flush=True)
subprocess.run(['adb','shell','input','tap',str(x),str(y)],check=True)
PY
}
capture() {
  adb exec-out screencap -p > "reports/$1.png"
  dump_ui
  cp reports/current-ui.xml "reports/$1.xml"
}
assert_text() {
  python3 - "$1" "$2" <<'PY'
import sys,xml.etree.ElementTree as ET
path,term=sys.argv[1:3]
texts=[(n.get('text','')+' '+n.get('content-desc','')).strip() for n in (x.attrib for x in ET.parse(path).getroot().iter('node'))]
print('VIEW_TEXTS',repr([t for t in texts if t][:50]))
assert any(term in t for t in texts), 'Missing UI text: '+term
PY
}
assert_no_dialog() {
  python3 - "$1" <<'PY'
import sys,xml.etree.ElementTree as ET
texts=[n.get('text','').strip() for n in (x.attrib for x in ET.parse(sys.argv[1]).getroot().iter('node'))]
assert not any(t in ('OK','CANCEL','确定','取消') for t in texts), 'Dialog not dismissed'
PY
}
check_log() {
  adb logcat -d -v brief > reports/logcat-stage.txt
  grep -q "NOVA_TIANYI_QA.*$1" reports/logcat-stage.txt || {
    echo "QA_MISSING_LOG_MARKER=$1"
    exit 1
  }
}
enter_network() {
  tap '^Network\s*$'
  sleep 5
}

adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1
sleep 5
enter_network
tap 'browse|add server|network connection|服务器|添加'
sleep 3
tap 'WebDAV|FTP|SMB'
sleep 1
capture 'protocol-list'
# A full spinner UI check against the Always-new order is also performed at
# Smali and resource level in the production build.
tap '天翼云盘'
sleep 12
capture 'after-synthetic-authorized'
assert_text reports/after-synthetic-authorized.xml '天翼云盘'
assert_no_dialog reports/after-synthetic-authorized.xml
check_log SHORTCUT_SAVED
check_log DIALOG_DISMISS_CALLED
check_log NETWORK_REFRESH_INVOKED
echo 'MOCK_CALLBACK_AUTO_CLOSE_LIST_REFRESH=PASS' | tee reports/refresh.txt

tap '^天翼云盘'
sleep 8
capture 'root-before-restart'
assert_text reports/root-before-restart.xml 'QA Root Folder'
echo 'MOCK_DAV_ROOT_BEFORE_RESTART=PASS' | tee reports/root.txt

adb shell am force-stop "$PACKAGE"
adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1
sleep 6
enter_network
capture 'after-process-restart'
assert_text reports/after-process-restart.xml '天翼云盘'
check_log SAVED_DAV_BOUND
tap '^天翼云盘'
sleep 8
capture 'root-after-process-restart'
assert_text reports/root-after-process-restart.xml 'QA Root Folder'
echo 'MOCK_DAV_ROOT_AFTER_APP_RESTART=PASS' | tee reports/app-restart.txt

# Full Android reboot while preserving the app's private SharedPreferences,
# encrypted token, stable local path, and NOVA ShortcutDb record.
adb reboot
adb wait-for-device
for i in $(seq 1 90); do
  if [ "$(adb shell getprop sys.boot_completed | tr -d '\r')" = 1 ]; then break; fi
  sleep 2
done
test "$(adb shell getprop sys.boot_completed | tr -d '\r')" = 1
adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1
sleep 7
enter_network
capture 'after-system-reboot'
assert_text reports/after-system-reboot.xml '天翼云盘'
tap '^天翼云盘'
sleep 8
capture 'root-after-system-reboot'
assert_text reports/root-after-system-reboot.xml 'QA Root Folder'
echo 'MOCK_DAV_ROOT_AFTER_SYSTEM_REBOOT=PASS' | tee reports/system-reboot.txt

adb logcat -d -v threadtime > reports/logcat.txt
if grep -E -A 20 'FATAL EXCEPTION|VerifyError|NoClassDefFoundError' reports/logcat.txt | grep -Eq 'Process: org.courville.nova|com.archos.mediacenter.video.cloud189'; then
  echo 'SYNTHETIC_AUTH_RUNTIME=FAIL'
  exit 1
fi
echo 'NOVA_TIANYI_MOCK_INTEGRATION=PASS' | tee reports/result.txt
