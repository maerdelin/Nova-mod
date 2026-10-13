"""Regression tests for V7.14+ one-instruction fixed-four-card home overlay."""
import hashlib
import importlib.util
from pathlib import Path
import struct
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('four_cards', ROOT/'scripts'/'four_cards.py')
PATCH=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)

class StableFourCardTests(unittest.TestCase):
    def test_pinned_method_only(self):
        self.assertEqual(PATCH.METHOD_ID,19531)
        self.assertEqual(PATCH.METHOD_NAME,'updateNonScrapedVideosVisibility')
        self.assertEqual(PATCH.METHOD_CLASS,'Lcom/archos/mediacenter/video/leanback/MainFragment;')
        self.assertEqual(PATCH.RETURN_VOID,bytes.fromhex('0e00'))
        self.assertEqual(PATCH.EXPECTED_CODE_HEADER,(7,2,4,0,97))

    def test_patch_against_previous_verified_14tv_apk_if_available(self):
        # Runtime workflow generates this exact reference before tests.
        source=ROOT/'dist'/'NovaTV_V7_14_14TV_Exact.apk'
        if not source.is_file():
            self.skipTest('Exact V7.14 APK is generated only during build')
        with zipfile.ZipFile(source) as apk:
            old=apk.read('classes.dex')
        new=PATCH.patch_dex(old)
        self.assertEqual(new[PATCH.INSTRUCTION_OFFSET:PATCH.INSTRUCTION_OFFSET+2],b'\x0e\x00')
        self.assertEqual(old[:8],new[:8])
        self.assertEqual(new[32:PATCH.INSTRUCTION_OFFSET],old[32:PATCH.INSTRUCTION_OFFSET])
        self.assertEqual(new[PATCH.INSTRUCTION_OFFSET+2:],old[PATCH.INSTRUCTION_OFFSET+2:])
        self.assertNotEqual(hashlib.sha256(old).digest(),hashlib.sha256(new).digest())

if __name__=='__main__':unittest.main()
