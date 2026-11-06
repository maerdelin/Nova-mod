#!/usr/bin/env bash
set -euo pipefail
mkdir -p reports
APK="testapk/dist/NOVA_Tianyi_Cloud_TEST_SIGNED.apk"
PACKAGE="org.courville.nova"
API="$(adb shell getprop ro.build.version.sdk | tr -d '\r')"
echo "NOVA_TIANYI_EMULATOR_API=${API}"

adb logcat -c || true
collect_logs() {
    adb logcat -d -v threadtime > reports/logcat.txt 2>/dev/null || true
    grep -E -A 25 'FATAL EXCEPTION|VerifyError|NoClassDefFoundError|UnsatisfiedLinkError|Unable to create application|Fatal signal|Process: org.courville.nova' reports/logcat.txt > reports/fatal-summary.txt || true
}
trap collect_logs EXIT

echo "NOVA_TIANYI_INSTALL_BEGIN"
adb install -r -g "$APK" | tee reports/install.txt
grep -q 'Success' reports/install.txt
echo "NOVA_TIANYI_INSTALL_PASS"

echo "NOVA_TIANYI_PHONE_COLD_BOOT_BEGIN"
adb shell am force-stop "$PACKAGE" || true
adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 | tee reports/phone-launch.txt
sleep 8
adb shell pidof "$PACKAGE" > reports/phone-pid.txt || true
if ! grep -q '[0-9]' reports/phone-pid.txt; then
  echo "ANDROID${API}_PHONE_COLD_START=FAIL" | tee reports/result.txt
  exit 1
fi
collect_logs
if grep -E -q 'FATAL EXCEPTION|Fatal signal.*org.courville.nova' reports/logcat.txt; then
  echo "ANDROID${API}_PHONE_FATAL=FAIL" | tee reports/result.txt
  exit 1
fi
adb exec-out screencap -p > reports/phone-coldboot.png || true
adb shell uiautomator dump /sdcard/tianyi-test-ui.xml >/dev/null 2>&1 || true
adb pull /sdcard/tianyi-test-ui.xml reports/phone-ui.xml >/dev/null 2>&1 || true
 echo "NOVA_TIANYI_PHONE_COLD_BOOT_PASS"

echo "NOVA_TIANYI_PHONE_RESTART_BEGIN"
adb shell am force-stop "$PACKAGE"
adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 | tee reports/phone-restart.txt
sleep 8
adb shell pidof "$PACKAGE" > reports/phone-restart-pid.txt || true
if ! grep -q '[0-9]' reports/phone-restart-pid.txt; then
  echo "ANDROID${API}_PHONE_RESTART=FAIL" | tee reports/result.txt
  exit 1
fi
echo "NOVA_TIANYI_PHONE_RESTART_PASS"

echo "NOVA_TIANYI_LEANBACK_BEGIN"
adb shell am force-stop "$PACKAGE"
adb shell monkey -p "$PACKAGE" -c android.intent.category.LEANBACK_LAUNCHER 1 | tee reports/leanback-launch.txt
sleep 8
adb shell pidof "$PACKAGE" > reports/leanback-pid.txt || true
if ! grep -q '[0-9]' reports/leanback-pid.txt; then
  echo "ANDROID${API}_LEANBACK=FAIL" | tee reports/result.txt
  exit 1
fi
collect_logs
if grep -q 'FATAL EXCEPTION' reports/logcat.txt; then
  echo "ANDROID${API}_RUNTIME_FATAL=FAIL" | tee reports/result.txt
  exit 1
fi
adb exec-out screencap -p > reports/leanback.png || true
 echo "ANDROID${API}_TIANYI_INSTALL_COLD_RESTART_LEANBACK=PASS" | tee reports/result.txt
