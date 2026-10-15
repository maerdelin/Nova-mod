#!/usr/bin/env python3
"""Install the final signed APK on an ephemeral CI emulator and check startup.
This is not a WebDAV/SMB playback or device-fleet acceptance test.
Never run this on a user's device: use only a fresh CI emulator.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time

PACKAGE = 'org.courville.nova'

def adb(*args, timeout=90, check=True):
    p = subprocess.run(['adb', *args], text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError('adb command failed: ' + p.stdout)
    return p.stdout.strip()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk', type=Path)
    parser.add_argument('--reports', type=Path, required=True)
    args = parser.parse_args()
    args.reports.mkdir(parents=True, exist_ok=True)
    report = {'status': 'FAIL', 'device': 'GitHub Actions Android emulator',
              'package': PACKAGE, 'apk': str(args.apk), 'launches': [],
              'scope': 'clean installation and launcher startup only; no WebDAV/playback tests'}
    try:
        adb('wait-for-device')
        report['android_api'] = adb('shell', 'getprop', 'ro.build.version.sdk')
        report['abi'] = adb('shell', 'getprop', 'ro.product.cpu.abi')
        existing = adb('shell', 'pm', 'path', PACKAGE, check=False)
        if 'package:' in existing:
            raise RuntimeError('Expected a fresh CI emulator; refusing to uninstall existing data')
        installed = adb('install', '--no-streaming', '-r', '-g', str(args.apk), timeout=180)
        (args.reports / 'adb-install.txt').write_text(installed + '\n')
        report['install_output'] = installed
        if 'Success' not in installed:
            raise RuntimeError('Package manager did not confirm successful installation: ' + installed)
        if 'package:' not in adb('shell', 'pm', 'path', PACKAGE):
            raise RuntimeError('Installed package missing')
        for category in ('android.intent.category.LAUNCHER', 'android.intent.category.LEANBACK_LAUNCHER'):
            resolved = adb('shell', 'cmd', 'package', 'resolve-activity', '--brief',
                           '-a', 'android.intent.action.MAIN', '-c', category, PACKAGE)
            components = [x.strip() for x in resolved.splitlines() if x.strip().startswith(PACKAGE + '/')]
            if len(components) != 1:
                raise RuntimeError('Launcher could not be resolved for ' + category + ': ' + resolved)
            component = components[0]
            adb('shell', 'am', 'force-stop', PACKAGE)
            adb('logcat', '-c')
            start = adb('shell', 'am', 'start', '-W', '-n', component, timeout=90)
            if 'Status: ok' not in start or 'Error:' in start:
                raise RuntimeError('Launcher failed: ' + start)
            time.sleep(12)
            pid = adb('shell', 'pidof', PACKAGE, check=False)
            crash = adb('logcat', '-b', 'crash', '-d', check=False)
            key = category.rsplit('.', 1)[-1].lower()
            (args.reports / (key + '-start.txt')).write_text(start + '\n')
            (args.reports / (key + '-crash.txt')).write_text(crash + '\n')
            if not pid or ('Process: ' + PACKAGE) in crash:
                raise RuntimeError('App exited or crashed after ' + category + '\n' + crash[-5000:])
            report['launches'].append({'category': category, 'component': component,
                                       'status': 'PASS', 'pid': pid, 'observation_seconds': 12})
        report['status'] = 'PASS'
        print('INSTALL_AND_LAUNCH=PASS')
    except Exception as exc:
        report['error'] = str(exc)
        raise
    finally:
        (args.reports / 'installation.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
