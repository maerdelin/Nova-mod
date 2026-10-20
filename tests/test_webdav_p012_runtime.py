"""Run the actual production Java classes and native C publication helpers.

These are deterministic fault-injection and loopback HTTP tests, not measurements
of a user's WebDAV throughput, decoder stability or ten seconds of playable data.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import webdav_p012_patch as patch
import webdav_parallel4_patch as smali

C_MAIN = r'''
#include <assert.h>
#include <strings.h>
int main(void) {
    int port = 0; uint64_t size = 0;
    assert(nova_cap_identity("http://localhost:38697/video.mkv", "", 80573952464ULL, &port, &size));
    assert(port == 38697 && size == 80573952464ULL);
    assert(nova_cap_publish("http://localhost:38697/video.mkv", "", 80573952464ULL, 119072740) == 38697);
    const char *iso = "&nova_iso=1&nova_iso_duration_us=7023000000&nova_iso_source_size=90117505024&nova_iso_source_port=39123";
    assert(nova_cap_identity("http://127.0.0.1:39222/main.m2ts", iso, 87096612864ULL, &port, &size));
    assert(port == 39123 && size == 90117505024ULL);
    assert(nova_cap_publish("http://127.0.0.1:39222/main.m2ts", iso, 87096612864ULL, 124015370) == 39123);
    assert(!nova_cap_identity("http://remote:123/x", iso, 1, &port, &size));
    assert(!nova_cap_identity("http://localhost:70000/x", "", 1, &port, &size));
    assert(!nova_cap_identity("http://localhost:12/x", "&nova_iso=1", 1, &port, &size));
    assert(!nova_cap_identity("http://localhost:12/x", "&nova_iso=1&nova_iso_source_size=18446744073709551616&nova_iso_source_port=2", 1, &port, &size));
    assert(!nova_cap_identity("http://localhost:12/x", "&nova_iso=1&nova_iso_source_size=100&nova_iso_source_port=2&nova_iso_source_port=2", 1, &port, &size));
    assert(!nova_cap_publish("http://localhost:12/x", "", 1, 0));
    assert(nova_iso_range_total("HTTP/1.1 206 Partial Content\r\nContent-Range: bytes 0-2047/90117505024\r\nX: 1\r\n\r\n") == 90117505024ULL);
    assert(nova_iso_range_total("HTTP/1.1 206 Partial Content\r\ncontent-range: bytes 192937984-193986559/90117505024\r\n\r\n") == 90117505024ULL);
    assert(!nova_iso_range_total("HTTP/1.1 206\r\nContent-Range: bytes 0-50/50\r\n\r\n"));
    assert(!nova_iso_range_total("HTTP/1.1 206\r\nContent-Range: bytes 0-1/18446744073709551616\r\n\r\n"));
    assert(!nova_iso_range_total("HTTP/1.1 206\r\nContent-Range: bytes +0-1/50\r\n\r\n"));
    assert(!nova_iso_range_total("HTTP/1.1 206\r\nContent-Range: bytes 0-1/50\r\nContent-Range: bytes 0-1/60\r\n\r\n"));
    assert(!nova_iso_range_total("HTTP/1.1 206\r\nContent-Range: bytes */50\r\n\r\n"));
    puts("PASS native publisher: real LF, port identity, ISO source/title distinction, invalid metadata rejection");
    return 0;
}
'''

OLD_PUBLICATION = r'''    // Share the authoritative native 10X packet-queue capacity with the Java
    // producer. Atomic rename prevents Java from parsing a partial record.
    // The value is advisory until Java can associate it with this media.
    {
        const char *dst = "/data/user/0/org.courville.nova/cache/nova_range4_capacity";
        const char *tmp = "/data/user/0/org.courville.nova/cache/nova_range4_capacity.tmp";
        FILE *fp = fopen(tmp, "w");
        if (fp) {
            fprintf(fp, "%llu %d\\n", (unsigned long long)s->size,
                    s->rebuffer_capacity_bytes);
            if (fclose(fp) == 0 && rename(tmp, dst) == 0) {
                serprintf("NOVA_RANGE4_CAP_PUBLISH: size=%llu capacity=%d\\n",
                    (unsigned long long)s->size, s->rebuffer_capacity_bytes);
            } else {
                serprintf("NOVA_RANGE4_CAP_PUBLISH_FAILED: rename\\n");
            }
        } else {
            serprintf("NOVA_RANGE4_CAP_PUBLISH_FAILED: open\\n");
        }
    }
'''


class P012RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='nova-p012-')
        cls.work = Path(cls.tmp.name)
        cls.classes = cls.work / 'classes'
        cls.classes.mkdir()
        sources = sorted((ROOT / 'parallel_range4/src').rglob('*.java'))
        sources += [ROOT / 'tests/java/android/util/Log.java',
                    ROOT / 'tests/java/com/archos/filecorelibrary/P012Harness.java']
        subprocess.run(['javac', '-source', '8', '-target', '8', '-d', str(cls.classes)]
                       + [str(p) for p in sources], check=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_java(self, name, *args):
        result = subprocess.run(['java', '-Xmx384m', '-cp', str(self.classes),
            'com.archos.filecorelibrary.P012Harness', name] + list(args),
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS ', result.stdout)
        print(result.stdout.strip())

    def test_capacity_records(self): self.run_java('records')
    def test_no_reader_native_capacity_arrival_and_refill(self): self.run_java('autonomous')
    def test_wrong_media_stale_capacity_and_shrink(self): self.run_java('capacity')
    def test_byte_exact_segment_retry_and_nonzero_seek(self): self.run_java('retry')
    def test_repeated_cancel_first_byte_future_and_interrupt(self): self.run_java('cancel')
    def test_actual_copy_loop_recovery_reenters_four_lanes(self): self.run_java('copy')
    def test_access_denial_downstream_failure_and_timeout(self): self.run_java('terminal')
    def test_copy_cancel_and_zero_progress_exhaustion(self): self.run_java('zero')
    def test_sidecar_permission_isolation_and_backoff(self): self.run_java('sidecar')
    def test_long_play_seek_retains_only_own_budget(self): self.run_java('session')
    def test_small_file_bypass(self): self.run_java('bypass')
    def test_real_loopback_http_range_transport(self): self.run_java('http')

    def test_c_publication_bytes_consumed_by_actual_java_producer(self):
        root = self.work / 'capacity'
        source = self.work / 'publication.c'
        source.write_text('#define _GNU_SOURCE\n#define NOVA_RANGE4_CAP_ROOT "' + str(root) + '"\n'
                          + patch.CAP_HELPERS + '\n#include <strings.h>\n' + patch.ISO_HELPERS + C_MAIN)
        exe = self.work / 'publication'
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(exe)],
                       check=True, timeout=30)
        result = subprocess.run([str(exe)], check=True, capture_output=True, text=True, timeout=10)
        print(result.stdout.strip())
        for port, size, cap in [(38697, 80573952464, 119072740), (39123, 90117505024, 124015370)]:
            record = Path(str(root) + '_' + str(port))
            self.assertEqual(record.read_bytes(), f'{size} {cap}\n'.encode('ascii'))
            self.run_java('native', str(record), str(size), str(cap))
        self.assertFalse(Path(str(root) + '_39222').exists(), 'published under ISO title proxy instead of source')
        self.assertFalse(list(self.work.glob('*.tmp.*')), 'temporary publication files leaked')

    def test_native_patch_anchors_and_repeat_rejection(self):
        original = 'static int max_delay       = 100000;\nUNTOUCHED-BEGIN\n' + OLD_PUBLICATION + 'UNTOUCHED-END\n'
        changed = patch.native_text(original)
        self.assertIn('UNTOUCHED-BEGIN\n', changed)
        self.assertTrue(changed.endswith('UNTOUCHED-END\n'))
        self.assertIn('nova_cap_publish(s->src.url, s->src_query', changed)
        with self.assertRaises(RuntimeError): patch.native_text(changed)
        with self.assertRaises(RuntimeError): patch.native_text(original + OLD_PUBLICATION)
        # In the full checkout also patch the REAL generator output, not only a fixture.
        upstream = ROOT / 'scripts/native_rebuffer_patch.py'
        if upstream.exists():
            spec = importlib.util.spec_from_file_location('original_native_patch', upstream)
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            native = self.work / 'native'; (native / 'Source').mkdir(exist_ok=True, parents=True)
            target = native / 'Source/stream_parser_ffmpeg.c'
            target.write_text('static int max_delay       = 100000;\n\ts->duration = ff_p->duration;\n\ts->size     = ff_p->size;\n')
            module.patch_dynamic_bitrate(native)
            self.assertIn('nova_cap_publish(', patch.native_text(target.read_text()))
        elif os.environ.get('GITHUB_ACTIONS') == 'true':
            self.fail('CI checkout is missing original native generator')

    def test_smali_delegate_preserves_non_webdav_paths(self):
        outside = '.method public getUri(Ljava/lang/String;)Landroid/net/Uri;\n    .locals 1\n    return-object v0\n.end method\n'
        call = f'    invoke-direct/range {{p0 .. p6}}, {smali.OUTER}->novaCopyStreamRecovering{smali.COPY_PROTO}'
        body = outside + '\n# novaMediaResumeEligible()Z\n' + call + '\n.method private novaCopyStreamRecovering' + smali.COPY_PROTO + '\n    .locals 9\n    return-void\n.end method\n'
        changed = smali.patch_outer(body)
        self.assertTrue(changed.startswith(outside))
        self.assertEqual(changed.count('->copyRecovering('), 1)
        self.assertIn('move-wide v6, p4', changed)
        self.assertIn('novaWrapRange4(', changed)
        with self.assertRaises(RuntimeError): smali.patch_outer(changed)
        session = '.class public X\n.super Ljava/lang/Object;\n' + '\n'.join([
            'novaMediaResumeEligible()Z', 'novaRequestedStart()J', 'readOptions()', 'requestedStart:J',
            'publishInput(Ljava/io/InputStream;)V', 'getInputStream(JLcom/archos/filecorelibrary/ReadOptions;)'])
        bound = smali.patch_session(session)
        self.assertIn('.implements ' + smali.MANAGED, bound)
        self.assertIn('publishRange4(Ljava/io/InputStream;)V', bound)
        self.assertIn('capacityPort()I', bound)
        with self.assertRaises(RuntimeError): smali.patch_session(bound)

    def test_sidecar_smali_is_exact_file_put_wrapper(self):
        get = '.method public get(Ljava/lang/String;)Ljava/io/InputStream;\n    .locals 1\n    return-object v0\n.end method\n'
        put = '.method public put' + patch.PUT_PROTO + '\n    .locals 0\n    return-void\n.end method\n'
        changed = patch.sidecar_text(get + put)
        self.assertTrue(changed.startswith(get))
        self.assertEqual(changed.count('.method public put' + patch.PUT_PROTO), 1)
        self.assertEqual(changed.count('.method public novaPutOriginalFile' + patch.PUT_PROTO), 1)
        self.assertIn('throw v0', changed)
        self.assertLess(changed.index('->beforePut('), changed.index(':nova_sidecar_put_start'))
        with self.assertRaises(RuntimeError): patch.sidecar_text(changed)
        with self.assertRaises(RuntimeError): patch.sidecar_text(get)
        with self.assertRaises(RuntimeError): patch.sidecar_text(get + put + put)

    def test_iso_patch_leaves_title_timeline_untouched(self):
        iso = ROOT / 'iso/nova_iso.c'
        if not iso.exists():
            # Exact anchors only; full-source assembly is a separate mandatory CI gate.
            original = ('    char path[4096];\n'
                'static ssize_t fetch_range(iso_input *in, int64_t start, size_t want, uint8_t *out) {\n'
                '    LOGI("RANGE_HEADERS id=%" PRIu64\n'
                '    size_t prefix = used - (size_t)body_at;\n'
                '        char out[160];\n'
                '        result = (*env)->NewStringUTF(env, out);\n')
        else:
            original = iso.read_text()
        changed = patch.iso_text(original)
        self.assertIn('nova_iso_source_size=', changed)
        self.assertIn('nova_iso_source_port=', changed)
        self.assertEqual(changed.count('bd_seek('), original.count('bd_seek('))
        self.assertEqual(changed.count('bd_select_title('), original.count('bd_select_title('))
        with self.assertRaises(RuntimeError): patch.iso_text(changed)

if __name__ == '__main__':
    unittest.main()
