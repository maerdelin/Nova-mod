#!/usr/bin/env bash
set -euo pipefail
APK="${1:-migu/Migu-Smart-HD.apk}"
OUT="${2:-migu/evidence/original-apk}"
EXPECTED="cb4d644681e963acd4224b484e6412b32a4377e47898e54c02e134944f214eea"
PKG="com.migutv.audiomonitorx"
COMPONENT="com.migutv.audiomonitorx/com.migutv.remote.MiguRemoteService"
mkdir -p "$OUT"
if [ ! -f "$APK" ]; then
  echo "BLOCKED: original APK absent at $APK; do not substitute an app." >&2
  exit 22
fi
echo "$EXPECTED  $APK" | sha256sum -c - | tee "$OUT/original_sha256_verified.txt"
test "$(adb shell getprop ro.build.version.sdk | tr -d '\r')" = 34
adb shell cmd package list packages | grep -F 'package:com.android.tv' > "$OUT/verified_android_tv.txt"
adb uninstall "$PKG" > "$OUT/uninstall.txt" 2>&1 || true
adb install "$APK" | tee "$OUT/install.txt"
adb logcat -c
adb shell dumpsys package "$PKG" > "$OUT/package_info.txt"
adb shell settings get secure enabled_accessibility_services > "$OUT/00_services_before.txt"
adb shell settings get secure accessibility_enabled > "$OUT/00_global_before.txt"
adb shell am start -a android.settings.ACCESSIBILITY_SETTINGS > "$OUT/settings_launch.txt" 2>&1 || true
sleep 3
adb shell uiautomator dump /sdcard/migu_accessibility.xml > "$OUT/ui_dump_command.txt" 2>&1 || true
adb pull /sdcard/migu_accessibility.xml "$OUT/ui_before.xml" >/dev/null 2>&1 || true
adb exec-out screencap -p > "$OUT/ui_before.png" || true
echo "UI_AUTHORIZATION_REQUIRED: automate or interact with the real TV Settings UI; never force-enable with settings put." | tee "$OUT/state.txt"
adb shell dumpsys accessibility > "$OUT/accessibility_before_ui.txt"
adb logcat -d -v threadtime > "$OUT/logcat_before_ui.txt"
echo "TEST INCOMPLETE: First activation must be performed through TV settings and logged." >&2
exit 23
