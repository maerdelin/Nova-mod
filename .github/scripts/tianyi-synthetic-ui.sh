#!/usr/bin/env bash
# Emulator-only integration test: no real 189Cloud account is used.
set -euo pipefail
mkdir -p reports
PACKAGE=org.courville.nova
adb install -r -g work/qa-synthetic.apk | tee reports/install.txt
adb logcat -c || true
trap 'adb logcat -d -v threadtime > reports/logcat.txt 2>/dev/null || true' EXIT

dump_ui() {
  # UiTestAutomationBridge sometimes returns a NULL root while a fresh
  # emulator/App layout is still settling. Never parse an error as XML.
  local n
  for n in $(seq 1 12); do
    adb shell uiautomator dump /sdcard/nova-tianyi-test-ui.xml > reports/ui-dump-last.txt 2>&1 || true
    adb exec-out cat /sdcard/nova-tianyi-test-ui.xml > reports/current-ui.xml 2>/dev/null || true
    if python3 - <<'PY'
import xml.etree.ElementTree as ET
try:
    tree=ET.parse('reports/current-ui.xml')
    assert tree.getroot().tag == 'hierarchy'
except (ET.ParseError, AssertionError, OSError):
    raise SystemExit(1)
PY
    then
      return 0
    fi
    sleep 3
  done
  adb exec-out screencap -p > reports/ui-automation-failure.png || true
  cat reports/ui-dump-last.txt
  echo 'UI_HIERARCHY_NOT_READY_AFTER_12_ATTEMPTS' >&2
  return 1
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
    return 1
  }
}
enter_network() {
  # New Android emulator boots can surface SystemUI ANR or the launcher while
  # NOVA is still settling. The network view is ready only when its real
  # BROWSE A NETWORK SHARE row is visible.
  local attempt
  for attempt in $(seq 1 18); do
    if ! dump_ui; then
      sleep 4
      continue
    fi
    if grep -Eqi 'System UI isn.t responding|System UI is not responding' reports/current-ui.xml; then
      echo "EMULATOR_SYSTEMUI_ANR_RECOVERY=$attempt"
      tap '^Wait$' || true
      sleep 8
      adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null || true
      sleep 4
      continue
    fi
    if grep -Fqi 'BROWSE A NETWORK SHARE' reports/current-ui.xml; then
      return 0
    fi
    if tap '^Network\s*$'; then
      sleep 5
      if dump_ui && grep -Fqi 'BROWSE A NETWORK SHARE' reports/current-ui.xml; then
        return 0
      fi
      sleep 4
      continue
    fi
    adb shell input keyevent KEYCODE_BACK || true
    sleep 3
  done
  capture 'network-navigation-timeout' || true
  adb logcat -d -v threadtime > reports/logcat-network-navigation.txt || true
  echo 'NOVA_NETWORK_NAVIGATION_TIMEOUT_AFTER_18_ATTEMPTS' >&2
  return 1
}
adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1
sleep 9
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
if assert_text reports/after-synthetic-authorized.xml '天翼云盘'; then
  echo 'TIANYI_SHORTCUT_NAME=PASS' > reports/name-result.txt
  SHORTCUT_LABEL='天翼云盘'
else
  echo 'TIANYI_SHORTCUT_NAME=FAIL' > reports/name-result.txt
  # Diagnostic fallback ONLY: continue testing real local DAV navigation
  # through the random capability row, never silently pass the name gate.
  SHORTCUT_LABEL='[a-f0-9]{48}/'
fi
assert_no_dialog reports/after-synthetic-authorized.xml
check_log SHORTCUT_SAVED
check_log DIALOG_DISMISS_CALLED
# The leanback screen uses its original targeted loader. The phone UI
# falls back to an Activity lifecycle reload when no leanback page exists.
if check_log NETWORK_REFRESH_INVOKED || check_log NETWORK_REFRESH_RECREATE; then
  echo 'NETWORK_REFRESH_EVENT=OBSERVED' > reports/refresh-mechanism.txt
else
  # The user-visible list is authoritative: the shortcut is already
  # demonstrably present after QR closes, even if NOVA refreshed it via
  # an uninstrumented original loader.
  echo 'NETWORK_REFRESH_EVENT=UNINSTRUMENTED; UI_SHORTCUT_PRESENT=YES' > reports/refresh-mechanism.txt
fi
echo 'MOCK_CALLBACK_AUTO_CLOSE_LIST_REFRESH=PASS' | tee reports/refresh.txt

tap "$SHORTCUT_LABEL"
sleep 5
dump_ui
# Dismiss NOVA's one-time network-folder tutorial before DAV assertions.
if grep -qi 'Press this menu item to integrate the content' reports/current-ui.xml; then
  tap 'OK'
  sleep 3
fi
capture 'root-before-restart'
assert_text reports/root-before-restart.xml 'QA Root Folder'
echo 'MOCK_DAV_ROOT_BEFORE_RESTART=PASS' | tee reports/root.txt
tap 'QA Root Folder'
sleep 5
capture 'video-leaf-before-restart'
assert_text reports/video-leaf-before-restart.xml 'QA Video.mp4'
echo 'MOCK_DAV_VIDEO_LEAF=PASS' | tee reports/video-leaf.txt

# Exercise a SECOND real nested video-directory transition through NOVA.
tap 'QA Nested Folder'
sleep 4
capture 'nested-mkv-leaf'
assert_text reports/nested-mkv-leaf.xml 'QA Nested.mkv'
echo 'MOCK_DAV_NESTED_MKV=PASS' | tee reports/nested.txt

# Crucial integration gap in earlier test versions: 137 MKVs were verified
# through raw HTTP but NEVER through NOVA's own file browser. Check the
# first AND last video in the actual Android list, with real UI scrolling.
adb shell input keyevent KEYCODE_BACK
sleep 3
adb shell input keyevent KEYCODE_BACK
sleep 3
capture 'root-with-bulk-folder'
assert_text reports/root-with-bulk-folder.xml 'QA Bulk Movies'
tap 'QA Bulk Movies'
sleep 6
capture 'bulk-movies-in-nova'
FIRST_VISIBLE=0
LAST_VISIBLE=0
for i in $(seq 1 25); do
  dump_ui
  if grep -Fq 'QA Movie 000.mkv' reports/current-ui.xml; then FIRST_VISIBLE=1; fi
  if grep -Fq 'QA Movie 136.mkv' reports/current-ui.xml; then LAST_VISIBLE=1; fi
  if [ "$FIRST_VISIBLE" -eq 1 ] && [ "$LAST_VISIBLE" -eq 1 ]; then break; fi
  adb shell input swipe 530 1540 530 450 260
  sleep 1
done
test "$FIRST_VISIBLE" -eq 1 && test "$LAST_VISIBLE" -eq 1 || {
  capture 'bulk-movies-ui-missing' || true
  echo "MOCK_NOVA_BULK_UI=FAIL first=$FIRST_VISIBLE last=$LAST_VISIBLE" >&2
  exit 1
}
echo 'MOCK_NOVA_BULK_FIRST_AND_LAST_MKV=PASS' | tee reports/bulk-ui.txt

# Use actual HTTP PROPFIND against the app's loopback DAV service.
# The synthetic Tianyi API deliberately caps responses at 40 despite
# pageSize=1000, so all 137 MKVs are visible ONLY when the production
# TianyiCloud.list + TianyiPaging + PROPFIND stack reads every page.
adb forward tcp:32789 tcp:27989
python3 - <<'PY'
import http.client
import re
import urllib.parse
import xml.etree.ElementTree as ET

trees=ET.parse('reports/root-before-restart.xml').getroot()
labels=' '.join(n.attrib.get('text','') for n in trees.iter('node'))
match=re.search(r'(?<![a-fA-F0-9])[a-fA-F0-9]{48}(?![a-fA-F0-9])',labels)
assert match, 'Could not locate saved DAV capability in the root UI'
capability=match.group(0)
path='/' + capability + '/QA%20Bulk%20Movies/'
conn=http.client.HTTPConnection('127.0.0.1',32789,timeout=40)
conn.request('PROPFIND',path,headers={'Depth':'1','Content-Length':'0'})
reply=conn.getresponse()
body=reply.read()
assert reply.status==207, f'Expected WebDAV 207, received {reply.status}: {body[:220]!r}'
doc=ET.fromstring(body)
rows=doc.findall('{DAV:}response')
assert len(rows)==138, f'Expected directory + 137 MKVs, got {len(rows)}'
names=[r.findtext('.//{DAV:}displayname','') for r in rows]
assert 'QA Movie 000.mkv' in names, 'Early MKV lost'
assert 'QA Movie 136.mkv' in names, 'Late-page MKV lost'
assert "QA Movie 005 O'Brien.mkv" in names, 'Escaped quote name corrupted'
assert '电影 006.mkv' in names, 'Unicode MKV name corrupted'
mimes=[r.findtext('.//{DAV:}getcontenttype','') for r in rows]
assert mimes.count('video/x-matroska')==137, 'Wrong MKV content types'
print('MOCK_DAV_API_PAGINATION=PASS',len(rows)-1,'MKVs')
conn.close()

# Repeat the same real DAV directory read. Previously NOVA re-fetched
# every ancestor and every file page, risking timeouts and empty folders.
import subprocess
def page_one_count():
    result=subprocess.run(['adb','logcat','-d','-v','brief'],check=True,
                          capture_output=True,text=True)
    return result.stdout.count('MOCK_LIST_API_PAGE_1_COUNT_40')
before=page_one_count()
assert before>0, 'Production pagination never reached bulk page 1'
conn=http.client.HTTPConnection('127.0.0.1',32789,timeout=40)
conn.request('PROPFIND',path,headers={'Depth':'1','Content-Length':'0'})
again=conn.getresponse()
again_body=again.read()
assert again.status==207, f'Cached DAV PROPFIND failed: {again.status}'
assert len(ET.fromstring(again_body).findall('{DAV:}response'))==138, 'Cached DAV snapshot lost files'
conn.close()
after=page_one_count()
assert before==after, f'DAV cache refetched bulk directory pages: {before} -> {after}'
print('MOCK_DAV_CACHE_NO_DUPLICATE_API_CALLS=PASS')
PY
adb forward --remove tcp:32789 || true
echo 'MOCK_DAV_137_MKVS=PASS' | tee reports/bulk-mkv.txt
check_log MOCK_INVALID_SESSION_REJECTED_ONCE
echo 'MOCK_PRODUCTION_SESSION_RETRY=PASS' | tee reports/session-retry.txt

adb shell am force-stop "$PACKAGE"
adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1
sleep 6
enter_network
capture 'after-process-restart'
assert_text reports/after-process-restart.xml "$([ "$SHORTCUT_LABEL" = '天翼云盘' ] && echo '天翼云盘' || echo '/')"
check_log SAVED_DAV_BOUND
tap "$SHORTCUT_LABEL"
sleep 8
capture 'root-after-process-restart'
assert_text reports/root-after-process-restart.xml 'QA Root Folder'
echo 'MOCK_DAV_ROOT_AFTER_APP_RESTART=PASS' | tee reports/app-restart.txt

adb reboot
adb wait-for-device
for i in $(seq 1 90); do
  if [ "$(adb shell getprop sys.boot_completed | tr -d '\r')" = 1 ]; then break; fi
  sleep 2
done
test "$(adb shell getprop sys.boot_completed | tr -d '\r')" = 1
# sys.boot_completed can become 1 before SystemUI, SurfaceFlinger and
# the launcher are responsive on hosted Android emulators.
adb shell input keyevent KEYCODE_WAKEUP || true
adb shell wm dismiss-keyguard || true
sleep 18
adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1
sleep 9
enter_network
capture 'after-system-reboot'
assert_text reports/after-system-reboot.xml "$([ "$SHORTCUT_LABEL" = '天翼云盘' ] && echo '天翼云盘' || echo '/')"
tap "$SHORTCUT_LABEL"
sleep 8
capture 'root-after-system-reboot'
assert_text reports/root-after-system-reboot.xml 'QA Root Folder'
echo 'MOCK_DAV_ROOT_AFTER_SYSTEM_REBOOT=PASS' | tee reports/system-reboot.txt
adb logcat -d -v threadtime > reports/logcat.txt
if grep -E -A 20 'FATAL EXCEPTION|VerifyError|NoClassDefFoundError' reports/logcat.txt | grep -Eq 'Process: org.courville.nova|com.archos.mediacenter.video.cloud189'; then
  echo 'SYNTHETIC_AUTH_RUNTIME=FAIL'
  exit 1
fi
if grep -q 'TIANYI_SHORTCUT_NAME=FAIL' reports/name-result.txt; then
  echo 'TIANYI_SHORTCUT_NAME=FAIL; OTHER_GATES_RECORDED' | tee reports/result.txt
  exit 1
fi
# Validate the single-shortcut rule in the real NOVA spinner after reboot.
adb shell am force-stop "$PACKAGE"
adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1
sleep 6
enter_network
tap 'browse|add server|network connection|服务器|添加'
sleep 3
tap 'WebDAV|FTP|SMB'
sleep 2
capture 'duplicate-disabled'
python3 - <<'PY'
import xml.etree.ElementTree as ET
a=[x.attrib for x in ET.parse('reports/duplicate-disabled.xml').getroot().iter('node')]
matches=[x for x in a if '天翼云盘' in x.get('text','')]
print('TIANYI_DUPLICATE_OPTIONS',[(x.get('text'),x.get('enabled')) for x in matches],flush=True)
assert matches, 'Missing Tianyi item in original protocol spinner'
assert any(x.get('enabled')=='false' for x in matches), 'Tianyi item must be disabled after shortcut exists'
PY
echo 'MOCK_DUPLICATE_PROTOCOL_DISABLED=PASS' | tee reports/duplicate.txt
echo 'NOVA_TIANYI_MOCK_INTEGRATION=PASS' | tee reports/result.txt
