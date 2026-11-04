#!/usr/bin/env python3
"""Fail-fast local tests for NOVA's on-device global diagnostic gate.

No emulator, cloud build, APK or user device is needed for these fixture tests.
Run them BEFORE starting the expensive Android compilation.
"""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


native = load('global_logs_native_coverage_patch')
ui = load('smoke_global_logs_settings')


class NativeGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        fixtures = {
            'Include/nova_global_flag.h': 'int nova_global_log_enabled(void);\n',
            'jni/libavosjni/libavos.h': '#include "android/log.h"\n'
                '#define LOGD(...) __android_log_print(ANDROID_LOG_DEBUG, LOG_TAG, ##__VA_ARGS__);\n'
                '#define LOGV(...) __android_log_print(ANDROID_LOG_VERBOSE, LOG_TAG, ##__VA_ARGS__);\n'
                '#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, ##__VA_ARGS__);\n',
            'Source/sub_engine_registry.c': '#include "sub_engine_registry.h"\n'
                '#define REG_LOGW(...) __android_log_print(ANDROID_LOG_WARN, REG_TAG, __VA_ARGS__)\n',
            'Source/jni_sub_engine.c': '#include "jni_sub_engine.h"\n'
                '#define JNI_LOGW(...) __android_log_print(ANDROID_LOG_WARN, JNI_TAG, __VA_ARGS__)\n',
            'Source/log_android.c': 'int writer(void) { return nova_diag_on()?__android_log_vprint(3, "avos", 0, 0):0; }\n',
            'jni/libavosjni/libavos.c': '#include "libavos.h"\nLOGV("nativeSetMaxPcmChannels");\n',
            'jni/libavosjni/avos_media_player.c': '#include "libavos.h"\nLOGV("event_thread: start");\n',
            'jni/libavosjni/avos_media_metadata_retriever.c': '#include "libavos.h"\nLOGE("bad bitmap");\n',
            'iso/nova_transport.c': '#define LOGI(...) do { if(nova_global_log_enabled()) __android_log_print(ANDROID_LOG_INFO,TAG,__VA_ARGS__); } while(0)\n'
                '#define LOGE(...) do { if(nova_global_log_enabled()) __android_log_print(ANDROID_LOG_ERROR,TAG,__VA_ARGS__); } while(0)\n',
        }
        for path, contents in fixtures.items():
            p = self.root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(contents)

    def test_instrument_every_known_native_writer(self):
        native.gate_native_direct_logs(self.root)
        native.audit_transport_logs(self.root / 'iso/nova_transport.c')
        hdr = (self.root / 'jni/libavosjni/libavos.h').read_text()
        self.assertEqual(hdr.count('if (nova_global_log_enabled())'), 3)
        self.assertIn('../../Include/nova_global_flag.h', hdr)

    def test_reject_unknown_android_log_writer(self):
        native.gate_native_direct_logs(self.root)
        (self.root / 'Source/rogue.c').write_text('int x(){return __android_log_print(5,"x","x");}')
        with self.assertRaisesRegex(RuntimeError, 'Unexpected ungated'):
            native.audit_raw_android_loggers(self.root)

    def test_reject_changed_upstream_jni_macro(self):
        p = self.root / 'jni/libavosjni/libavos.h'
        p.write_text(p.read_text().replace('#define LOGE(...)', '#define LOGERR(...)'))
        with self.assertRaisesRegex(RuntimeError, 'JNI LOGE'):
            native.gate_native_direct_logs(self.root)

    def test_reject_ungated_subtitle_diagnostics(self):
        native.gate_native_direct_logs(self.root)
        p = self.root / 'Source/jni_sub_engine.c'
        p.write_text(p.read_text().replace('if (nova_global_log_enabled()) ', ''))
        with self.assertRaisesRegex(RuntimeError, 'Unprotected direct'):
            native.audit_raw_android_loggers(self.root)

    def test_jni_macros_skip_arguments_while_off_and_recover_while_on(self):
        native.gate_native_direct_logs(self.root)
        h = (self.root / 'jni/libavosjni/libavos.h').read_text()
        definitions = '\n'.join(line for line in h.splitlines() if line.startswith('#define LOG'))
        source = ('#define ANDROID_LOG_DEBUG 3\n#define ANDROID_LOG_VERBOSE 2\n'
                  '#define ANDROID_LOG_ERROR 6\n#define LOG_TAG "test"\n'
                  'static int enabled, logs, evaluated;\n'
                  'int nova_global_log_enabled(void){return enabled;}\n'
                  'int log_out(int a,const char*b,const char*c,...){(void)a;(void)b;(void)c;logs++;return 0;}\n'
                  '#define __android_log_print log_out\n' + definitions + '\n'
                  'int arg(void){return ++evaluated;}\n'
                  'int main(void){'
                  'LOGD("x %d",arg());LOGV("x %d",arg());LOGE("x %d",arg());'
                  'if(logs||evaluated)return 1;'
                  'enabled=1;LOGD("x %d",arg());LOGV("x %d",arg());LOGE("x %d",arg());'
                  'if(logs!=3||evaluated!=3)return 2;'
                  'enabled=0;LOGD("x %d",arg());'
                  'return (logs!=3||evaluated!=3)?3:0;}\n')
        src = self.root / 'macro.c'
        src.write_text(source)
        exe = self.root / 'macro'
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Werror', str(src), '-o', str(exe)],
                       check=True, capture_output=True, text=True)
        subprocess.run([str(exe)], check=True)


class SharedGateTest(unittest.TestCase):
    def test_native_mmap_failure_recovers_and_toggle_is_two_way(self):
        """Build actual C source with only the Android file path redirected to a tmp test file."""
        actual = (ROOT / 'iso/nova_global_gate.c').read_text()
        self.assertIn('pthread_mutex_trylock', actual)
        self.assertIn('nova_logs_retry_after_ms', actual)
        self.assertNotIn('pthread_create', actual)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            target = root / 'shared.bin'
            source = actual.replace(
                '"/data/user/%u/org.courville.nova/files/nova_logs_enabled.bin",\n        user_id',
                f'"{target.as_posix()}"'
            ).replace(
                'unsigned user_id = (unsigned)getuid()/100000u;',
                'unsigned user_id = (unsigned)getuid()/100000u;\n    (void)user_id;'
            )
            (root / 'gate.c').write_text(source)
            program = r"""
#include <unistd.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <time.h>
int nova_global_log_enabled(void);
int main(int argc,char **argv) {
    if(argc!=2)return 99;
    if(nova_global_log_enabled()!=0)return 1;
    int fd=open(argv[1],O_RDWR|O_CREAT|O_TRUNC,0600);
    if(fd<0 || ftruncate(fd,1))return 2;
    void *p=mmap(0,4096,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
    if(p==MAP_FAILED)return 3;
    ((volatile unsigned char*)p)[0]=1;
    struct timespec delay={1,100000000};
    nanosleep(&delay,0);
    if(nova_global_log_enabled()!=1)return 4;
    ((volatile unsigned char*)p)[0]=0;
    if(nova_global_log_enabled()!=0)return 5;
    ((volatile unsigned char*)p)[0]=1;
    if(nova_global_log_enabled()!=1)return 6;
    munmap(p,4096);close(fd);return 0;
}
"""
            (root / 'test.c').write_text(program)
            binary = root / 'test_shared_gate'
            subprocess.run(['cc','-std=gnu11','-pthread','-Wall','-Wextra','-Werror',
                            str(root/'gate.c'),str(root/'test.c'),'-o',str(binary)],
                           capture_output=True,text=True,check=True)
            subprocess.run([str(binary),str(target)],check=True)


class EmulatorScriptTest(unittest.TestCase):
    def test_320_by_640_swipe_and_landscape(self):
        for output in ('Physical size: 320x640', 'Physical size: 1920x1080',
                       'Physical size: 1080x1920\nOverride size: 320x640'):
            with patch.object(ui, 'adb', return_value=output):
                w, h = ui.screen_size()
            x1, y1, x2, y2 = ui.swipe_coordinates(w, h)
            self.assertTrue(0 < x1 < w and 0 < x2 < w)
            self.assertTrue(0 < y2 < y1 < h)

    def test_preference_ui_bounds_and_boolean_state(self):
        from xml.etree import ElementTree as ET
        root = ET.fromstring('<hierarchy><node text=""><node text="日志"/>'
                             '<node checkable="true" checked="false" bounds="[220,300][300,360]"/>'
                             '</node></hierarchy>')
        target = ui.locate(root)
        self.assertIsNotNone(target)
        self.assertFalse(ui.state(target))
        with patch.object(ui, 'adb',
                          side_effect=lambda *args, **_: 'Physical size: 320x640' if args[:3] == ('shell', 'wm', 'size') else '') as fake:
            ui.tap(target)
            self.assertEqual(fake.call_args.args[:3], ('shell', 'input', 'tap'))
            self.assertEqual(fake.call_args.args[3:], ('260', '330'))

    def test_missing_checkbox_must_fail(self):
        from xml.etree import ElementTree as ET
        with self.assertRaisesRegex(RuntimeError, 'missing'):
            ui.state(ET.fromstring('<node checkable="true"/>'))

    def test_java_probe_is_gated(self):
        source = (ROOT / 'scripts/global_logs_smali_patch.py').read_text()
        self.assertIn('ON_AFTER_APPLY', source)
        self.assertIn('NovaGlobalLogs;->i(Ljava/lang/String;Ljava/lang/String;)I', source)
        self.assertIn('signatures.add(("i", "Ljava/lang/String;Ljava/lang/String;", "I"))', source)


class SmaliGateAuditTest(unittest.TestCase):
    def test_torrent_log_insertion_precedes_final_java_gate(self):
        code = (ROOT / 'scripts/direct_transport_apply.py').read_text()
        self.assertLess(
            code.index('torrent.write_text(patch_torrent_observer(torrent.read_text()))'),
            code.index('apply_nova_logs(root)'),
            'All Java and Smali mutations must happen before global Log interception',
        )
        torrent = (ROOT / 'scripts/torrent_crash_guard_patch.py').read_text()
        self.assertIn('Landroid/util/Log;->w', torrent)

    def test_logback_zero_local_void_methods_allocate_new_register(self):
        smali = load('global_logs_smali_patch')
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / 'smali/ch/qos/logback/classic'
            folder.mkdir(parents=True)
            methods = [
                f'.method public callAppenders({"I" * i})V\n'
                f'    .locals 0\n'
                f'    return-void\n'
                f'.end method\n'
                for i in range(1, 19)
            ]
            f = folder / 'Logger.smali'
            f.write_text('.class public Lch/qos/logback/classic/Logger;\n'
                         '.super Ljava/lang/Object;\n' + ''.join(methods))
            self.assertEqual(smali.gate_logback(Path(d)), 18)
            patched = f.read_text()
            self.assertEqual(patched.count('.locals 1'), 18)
            self.assertNotIn('.locals 0', patched)
            self.assertEqual(patched.count('NovaGlobalLogs;->enabled()Z'), 18)


if __name__ == '__main__':
    unittest.main(verbosity=2)
