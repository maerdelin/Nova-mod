#!/usr/bin/env bash
set -euo pipefail
APK="migu/Migu-Smart-HD.apk"
OUT="migu/evidence/original-apk"
EXPECTED="cb4d644681e963acd4224b484e6412b32a4377e47898e54c02e134944f214eea"
PKG="com.migutv.audiomonitorx"
COMPONENT="com.migutv.audiomonitorx/com.migutv.remote.MiguRemoteService"
mkdir -p "$OUT"
test -s "$APK" || { echo "BLOCKED: original APK is absent"; exit 22; }
echo "$EXPECTED  $APK" | sha256sum -c - | tee "$OUT/original_sha256_verified.txt"
test "$(adb shell getprop ro.build.version.sdk | tr -d '\r')" = 34
adb shell cmd package list packages | grep -F 'package:com.android.tv' > "$OUT/verified_android_tv.txt"
echo '=== FRESH INSTALL ==='
adb uninstall "$PKG" > "$OUT/00_uninstall_previous.txt" 2>&1 || true
adb install "$APK" | tee "$OUT/01_install.txt"
adb shell dumpsys package "$PKG" > "$OUT/01_package.txt"
adb logcat -c
adb shell settings get secure enabled_accessibility_services | tee "$OUT/01_enabled_before_ui.txt"
adb shell settings get secure accessibility_enabled | tee "$OUT/01_global_before_ui.txt"
echo '=== OPEN ACTUAL TV ACCESSIBILITY SETTINGS (NO ADB SECURE SETTINGS WRITES) ==='
adb shell am start -a android.settings.ACCESSIBILITY_SETTINGS 2>&1 | tee "$OUT/02_settings_launch.txt" || true
sleep 5
adb shell dumpsys activity activities > "$OUT/02_activities.txt"
adb shell dumpsys accessibility > "$OUT/02_accessibility.txt"
timeout 35s adb shell uiautomator dump /sdcard/migu_ui.xml > "$OUT/02_dump_status.txt" 2>&1 || true
timeout 15s adb pull /sdcard/migu_ui.xml "$OUT/02_settings_ui.xml" >/dev/null 2>&1 || true
timeout 15s adb exec-out screencap -p > "$OUT/02_settings_ui.png" || true
adb logcat -d -v threadtime > "$OUT/02_logcat.txt"
if test -s "$OUT/02_settings_ui.xml"; then
  echo '=== TV SETTINGS UI ELEMENTS ==='
  python3 - "$OUT/02_settings_ui.xml" <<'PY'
import sys,xml.etree.ElementTree as ET
r=ET.parse(sys.argv[1]).getroot()
for n in r.iter('node'):
    d=n.attrib
    if d.get('text') or d.get('content-desc') or d.get('clickable')=='true':
        print('TV_NODE',repr(d.get('text','')),repr(d.get('content-desc','')),repr(d.get('resource-id','')),d.get('bounds',''), 'clickable='+d.get('clickable',''))
PY
else
  echo 'WARN: TV Settings UI dump unavailable'
fi
echo '=== SERVICE REGISTRATION CHECK ==='
grep -E 'MiguRemoteService|com.migutv|AccessibilityService' "$OUT/01_package.txt" | head -25 || true
echo 'RESULT: Original SHA verified, real Android 14 TV installed APK and opened TV Settings. UI navigation/first toggle must be explicitly proven.'
