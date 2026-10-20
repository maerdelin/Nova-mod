import sys
import re
import unittest
import tempfile
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import webdav_single_stream as patch
import webdav_parallel4_patch as old
import webdav_parallel4_dex as build

class SingleStreamTests(unittest.TestCase):
    def test_single_copier_runtime_and_http(self):
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td)
            source = ROOT / 'single_stream/src/com/archos/filecorelibrary/NovaSingleStreamInputStream.java'
            subprocess.run(['javac', '-source', '8', '-target', '8', '-d', str(cp),
                            str(ROOT / 'tests/java/android/util/Log.java'), str(source),
                            str(ROOT / 'tests/android/SingleStreamHarness.java')], check=True, timeout=45)
            result = subprocess.run(['java', '-cp', str(cp), 'nova.test.SingleStreamHarness'],
                                    capture_output=True, text=True, timeout=90)
            print(result.stdout + result.stderr)
            self.assertEqual(result.returncode, 0)
            self.assertIn('SINGLE_STREAM_PROBE=PASS', result.stdout)
            self.assertIn('HTTP32MiB+37 one GET, exact bytes', result.stdout)

    def test_build_excludes_parallel_source(self):
        with tempfile.TemporaryDirectory() as td:
            files = build.prepare_sources(Path(td))
            self.assertNotIn('NovaParallelRangeInputStream.java', [p.name for p in files])
            self.assertIn('NovaSingleStreamInputStream.java', [p.name for p in files])
            self.assertTrue(all(patch.OLD not in p.read_text() for p in files))
            for p in files:
                if p.name in ('NovaWebdavOpenPolicy.java', 'NovaWebdavSidecarPolicy.java', 'NovaIsoSessionGuard.java'):
                    original = ROOT / 'parallel_range4/src/com/archos/filecorelibrary' / p.name
                    self.assertEqual(p.read_text(), original.read_text().replace(patch.OLD, patch.NEW))

    def test_no_workers_or_window_in_single_copy(self):
        text=(ROOT/'single_stream/src/com/archos/filecorelibrary/NovaSingleStreamInputStream.java').read_text()
        for forbidden in ('newFixedThreadPool', 'executor.submit', 'new Thread(', 'Future<', 'maxPrefetchBytes', 'nova_range4_capacity'):
            self.assertNotIn(forbidden,text)
        self.assertIn('output.write(buffer, 0, n)',text)

    def test_exact_media_bridge_rollback(self):
        outer=('    invoke-virtual {p6, p1, p4, p5}, '+patch.SESSION+
               '->novaWrapRange4(Ljava/io/InputStream;J)Ljava/io/InputStream;\n'
               '    move-result-object p1\n'+old.COPY_METHOD)
        out=patch.outer_text(outer)
        self.assertNotIn('novaWrapRange4',out)
        self.assertNotIn(patch.OLD,out)
        self.assertEqual(out.count('NovaSingleStreamInputStream;->copyRecovering('),1)
        with self.assertRaises(RuntimeError):patch.outer_text(out)
        with self.assertRaises(RuntimeError):patch.outer_text(outer+outer)

    def test_remove_only_parallel_session_ownership(self):
        src='.class public '+patch.SESSION+'\n.super Ljava/lang/Object;\n.implements '+patch.BASE+patch.OLD+'$ManagedSource;\n'+old.SESSION_METHODS
        out=patch.session_text(src)
        self.assertNotIn(patch.OLD,out)
        self.assertNotIn('novaWrapRange4(',out)
        self.assertNotIn('capacityOwner(',out)
        self.assertNotIn('capacityPort(',out)
        self.assertIn('publishSingle(',out)
        self.assertIn('novaMediaResumeEligible()Z',out)
        self.assertIn('publishInput(Ljava/io/InputStream;)V',out)
        with self.assertRaises(RuntimeError):patch.session_text(out)

if __name__=='__main__':unittest.main()
