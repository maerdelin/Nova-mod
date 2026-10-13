"""Offline guards before fetching the original official Nova APK."""
from pathlib import Path
import base64
import importlib.util
import json
import unittest
import zlib

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('nova_exact',ROOT/'scripts'/'v714_exact.py')
MODULE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

class VerifiedReferenceTest(unittest.TestCase):
    def test_pinned_reference_and_manifest(self):
        manifest=json.loads((ROOT/'reference'/'v714-parity-manifest.json').read_text())
        self.assertEqual(manifest['reference_sha256'],MODULE.TARGET_SHA256)
        self.assertEqual(manifest['reference_size'],MODULE.TARGET_LENGTH)
        self.assertEqual(manifest['official_source_sha256'],MODULE.BASE_SHA256)
        self.assertEqual(len(manifest['modified_zip_entries']),4)
        self.assertEqual(len(manifest['modified_dex_methods']),22)
        self.assertEqual(set(manifest['modified_zip_entries']),MODULE.CHANGED_MEMBERS)

    def test_patch_blobs_and_signatures(self):
        self.assertEqual(len(base64.b64decode((ROOT/'reference'/'dex-insert.b64').read_text())),324)
        self.assertEqual(len(MODULE.sign_block()),2049)
        self.assertEqual(len(MODULE.XML_REPLACEMENTS),2)
        self.assertEqual(len(MODULE.RESOURCE_STRINGS),7)

    def test_clean_only_one_release_workflow(self):
        self.assertEqual([p.name for p in (ROOT/'.github/workflows').glob('*.yml')],['v714-exact.yml'])
        self.assertFalse((ROOT/'ui'/'apply.py').exists())
        self.assertFalse((ROOT/'scripts'/'v714_patch_dex.py').exists())

if __name__=='__main__':unittest.main()
