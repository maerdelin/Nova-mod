#!/usr/bin/env bash
set -euo pipefail
mkdir -p migu/evidence
{
  date -u
  adb devices -l
  adb shell getprop ro.build.version.sdk
  adb shell getprop ro.build.version.release
  adb shell getprop ro.product.model
  adb shell getprop ro.build.characteristics
  adb shell getprop ro.product.cpu.abi
  adb shell cmd package list packages | grep -E 'tv|leanback|settings' | head -n 40 || true
} | tee migu/evidence/baseline.txt
test "$(adb shell getprop ro.build.version.sdk | tr -d '\r')" = 34
adb shell cmd package list packages | grep -F 'package:com.android.tv' > migu/evidence/tv_framework.txt
adb shell getprop ro.product.model | grep -Ei 'tv|television'
adb shell dumpsys accessibility > migu/evidence/accessibility_baseline.txt
adb shell uiautomator dump /sdcard/window.xml >/dev/null || true
adb pull /sdcard/window.xml migu/evidence/window.xml || true
echo 'PASS: Android 14 TV emulator booted; Android TV framework confirmed.'
