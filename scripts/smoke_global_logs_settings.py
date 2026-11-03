#!/usr/bin/env python3
"""Verify real Settings checkbox and Java logcat gate on Android 11.

All gestures use actual emulator dimensions. A PASS requires a real Log.i
emitted after the onSharedPreferenceChanged callback, not only UI state.
No root, pm clear, force-setting or application data mutation.
"""
import json
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from argparse import ArgumentParser
from pathlib import Path

PACKAGE = "org.courville.nova"
ACTIVITY = "com.archos.mediacenter.video.utils.VideoPreferencesActivity"
TAG = "NOVA_GLOBAL_LOGS_TEST"


def adb(*args, timeout=65):
    proc = subprocess.run(["adb", *args], stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, errors="replace",
                          timeout=timeout)
    if proc.returncode:
        raise RuntimeError(f"ADB {args}: {proc.stdout[-1800:]}")
    return proc.stdout


def screen_size():
    output = adb("shell", "wm", "size")
    sizes = re.findall(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", output)
    if not sizes:
        raise RuntimeError("Cannot determine emulator screen size: " + output)
    width, height = map(int, sizes[-1])
    if width < 160 or height < 240:
        raise RuntimeError(f"Unexpected emulator display dimensions: {width}x{height}")
    return width, height


def swipe_coordinates(width, height):
    x = max(1, min(width - 2, width // 2))
    top = max(1, min(height - 2, round(height * 0.24)))
    bottom = max(1, min(height - 2, round(height * 0.78)))
    if bottom - top < 90:
        raise RuntimeError(f"Insufficient vertical space for scroll: {width}x{height}")
    return x, bottom, x, top


def dump():
    last = ""
    for _ in range(4):
        try:
            adb("shell", "uiautomator", "dump", "/sdcard/nova-global-logs-ui.xml", timeout=65)
            output = adb("shell", "cat", "/sdcard/nova-global-logs-ui.xml")
            start = output.find("<?xml")
            if start < 0:
                raise RuntimeError("uiautomator returned no XML document")
            return ET.fromstring(output[start:])
        except (RuntimeError, ET.ParseError) as exc:
            last = str(exc)
            time.sleep(0.4)
    raise RuntimeError("Unable to read preference XML after four attempts: " + last)


def locate(root):
    parents = {child: parent for parent in root.iter() for child in parent}
    for node in root.iter():
        if node.get("text") != "日志" and node.get("content-desc") != "日志":
            continue
        current = node
        while current in parents:
            current = parents[current]
            checkboxes = [child for child in current.iter()
                          if child.get("checkable") == "true" and child.get("checked") in ("true", "false")]
            if checkboxes:
                return checkboxes[0]
        raise RuntimeError("Logs text is present, but no checkable preference exists")
    return None


def locate_with_scroll(result):
    adb("shell", "am", "start", "-W", "-n", PACKAGE + "/" + ACTIVITY)
    width, height = screen_size()
    coords = swipe_coordinates(width, height)
    result["display"] = {"width": width, "height": height, "scroll": list(coords)}
    time.sleep(0.5)
    for attempt in range(24):
        item = locate(dump())
        if item is not None:
            result["scroll_attempts"].append(attempt)
            return item
        if attempt != 23:
            adb("shell", "input", "swipe", *(str(v) for v in coords), "320")
            time.sleep(0.12)
    raise RuntimeError("Logs checkbox not found after 24 in-bounds scroll inspections")


def state(item):
    if item is None or item.get("checked") not in ("true", "false"):
        raise RuntimeError("Logs checkbox has missing or non-Boolean checked state")
    return item.get("checked") == "true"


def tap(item):
    numbers = [int(v) for v in re.findall(r"\d+", item.get("bounds", ""))]
    if len(numbers) != 4:
        raise RuntimeError("Logs checkbox has no valid Android bounds")
    x0, y0, x1, y1 = numbers
    width, height = screen_size()
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise RuntimeError(f"Checkbox bounds {numbers} exceed {width}x{height}")
    adb("shell", "input", "tap", str((x0 + x1) // 2), str((y0 + y1) // 2))


def expect_state(expected, label):
    for _ in range(5):
        item = locate(dump())
        if item is not None and state(item) is expected:
            return item
        time.sleep(0.3)
    raise RuntimeError(f"{label}: checkbox never reached checked={expected}")


def probe_lines():
    return adb("logcat", "-d", "-v", "brief", "-s", TAG + ":I", "*:S")


def require_probe(expected, label):
    output = probe_lines()
    found = bool(re.search(r"\b" + re.escape(TAG) + r"\b.*\bON_AFTER_APPLY\b", output))
    if found is not expected:
        raise RuntimeError(f"{label}: expected Java gate probe={expected}, got {found}: {output[-1500:]}")


def main():
    parser = ArgumentParser()
    parser.add_argument("--reports", type=Path, required=True)
    args = parser.parse_args()
    args.reports.mkdir(parents=True, exist_ok=True)
    result = {"status": "FAIL", "key": "nova_logs_enabled", "default": True,
              "java_gate": "NOT_TESTED", "native_gate": "NOT_TESTED",
              "scroll_attempts": [], "tested": []}
    try:
        item = locate_with_scroll(result)
        if state(item) is not True:
            raise RuntimeError("Fresh install default must be checked")
        result["tested"].append("Logs preference and fresh install ON default")

        adb("logcat", "-c")
        tap(item)
        expect_state(False, "ON->OFF")
        require_probe(False, "OFF must suppress gate-guarded Java Log.i")
        result["tested"].append("ON->OFF suppresses Log.i in actual callback")

        adb("shell", "am", "force-stop", PACKAGE)
        item = locate_with_scroll(result)
        if state(item) is not False:
            raise RuntimeError("OFF not persisted across restart")
        result["tested"].append("OFF persisted across app restart")

        adb("logcat", "-c")
        tap(item)
        expect_state(True, "OFF->ON")
        require_probe(True, "ON must emit Java Log.i probe")
        result["tested"].append("OFF->ON restores real gated Java Log.i")

        adb("shell", "am", "force-stop", PACKAGE)
        item = locate_with_scroll(result)
        if state(item) is not True:
            raise RuntimeError("ON not persisted across restart")
        result["tested"].append("ON persisted across app restart")
        result["java_gate"] = "PASS"
        result["status"] = "PASS"
        print("NOVA_GLOBAL_LOGS_UI_JAVA_GATE=PASS")
    finally:
        path = args.reports / "global-logs-settings.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
