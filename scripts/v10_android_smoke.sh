#!/usr/bin/env bash
set -euo pipefail
mkdir -p dist
export ANDROID_SERIAL=emulator-5554
adb install -r dist/v10-emulator.apk
adb shell wm size 1280x800
adb shell wm density 160
# Grant only permissions requested by the installed APK. Android 13 READ_EXTERNAL_STORAGE is obsolete.
for perm in android.permission.RECORD_AUDIO android.permission.READ_MEDIA_VIDEO android.permission.READ_MEDIA_AUDIO android.permission.POST_NOTIFICATIONS; do
  adb shell pm grant org.courville.nova "$perm" >/dev/null 2>&1 || true
done
adb shell appops set org.courville.nova MANAGE_EXTERNAL_STORAGE allow || true
adb shell settings put global window_animation_scale 0.0
adb shell settings put global transition_animation_scale 0.0
adb shell settings put global animator_duration_scale 0.0
adb logcat -c
adb shell monkey -p org.courville.nova 1
# Resolve native permission prompts; never confuse these prompts with actual UI.
for attempt in 1 2 3 4 5 6; do
  sleep 7
  adb shell uiautomator dump /sdcard/v10_current.xml >/dev/null || true
  adb pull /sdcard/v10_current.xml dist/v10_current.xml >/dev/null 2>&1 || true
  if [[ ! -s dist/v10_current.xml ]]; then continue; fi
  button="$(python3 - <<'PY'
import xml.etree.ElementTree as ET,re
root=ET.parse('dist/v10_current.xml')
vals=[]
for a in root.iter('node'):
    z=a.attrib
    label=z.get('text','').strip().lower()
    if any(x in label for x in ['while using','only this time','allow','允许','使用应用时','仅在使用','继续','continue','确定','ok']):
        bounds=z.get('bounds','')
        m=re.findall(r'\d+',bounds)
        if len(m)==4:vals.append((label,(int(m[0])+int(m[2]))//2,(int(m[1])+int(m[3]))//2))
print(f'{vals[0][1]} {vals[0][2]}' if vals else '')
PY
)"
  if [[ -n "$button" ]]; then
    adb shell input tap $button
  else
    break
  fi
done
sleep 8
adb shell uiautomator dump /sdcard/v10_home.xml
adb pull /sdcard/v10_home.xml dist/mobile_v10_home.xml
adb shell screencap -p /sdcard/v10_home.png
adb pull /sdcard/v10_home.png dist/mobile_v10_home.png
python3 - <<'PY'
import xml.etree.ElementTree as ET,re
root=ET.parse('dist/mobile_v10_home.xml')
data=[]
for e in root.iter('node'):
    a=e.attrib
    txt=a.get('text','').strip()
    if txt:data.append((txt,a.get('bounds',''),a.get('resource-id','')))
print('ACTUAL MOBILE UI ELEMENTS:',data[:60])
for label,bound,_ in data:
    if 'permission' in label.lower() or '权限' in label or label.lower().startswith('an error'):
        raise SystemExit('FAIL: still showing permissions dialog, not app UI')
PY
adb shell pidof org.courville.nova
# Prepare a real decodable video, then use file browser's mobile click-to-play.
if command -v ffmpeg >/dev/null; then
  ffmpeg -hide_banner -loglevel error -y -f lavfi -i color=c=blue:s=320x180:r=12 -t 3 -c:v mpeg4 -q:v 5 dist/VideoClickTest.mp4
  adb shell mkdir -p /sdcard/Movies
  adb push dist/VideoClickTest.mp4 /sdcard/Movies/VideoClickTest.mp4
  adb shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/Movies/VideoClickTest.mp4 || true
fi
adb shell uiautomator dump /sdcard/v10_network.xml || true
adb pull /sdcard/v10_network.xml dist/mobile_v10_network.xml || true
adb shell screencap -p /sdcard/v10_network.png
adb pull /sdcard/v10_network.png dist/mobile_v10_network.png
adb logcat -b crash -d -v time > dist/v10_crash.log
adb logcat -d -v time > dist/v10_full.log
if grep -Eq 'FATAL EXCEPTION|VerifyError|NoSuchMethodError|NoSuchFieldError' dist/v10_crash.log; then
  echo "FAIL: app crashed or Dalvik verification error"
  tail -n 70 dist/v10_crash.log
  exit 1
fi
echo 'PASS: V10 installed, Android 13 mobile launched past permissions without a recorded crash.'
echo 'NOTE: navigation, card alignment and real video play are NOT certified unless later dedicated assertions are added.'
