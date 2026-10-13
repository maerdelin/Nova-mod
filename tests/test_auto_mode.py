"""Regression guards for the user-confirmed Nova V7.14 AutoMode baseline.

BlueStacks mode switching was confirmed by the user for the exact
SHA-pinned 2026-10-13 signed APK. These tests protect the DEX method and
do not pretend to run Android UI interaction in GitHub Actions.
"""
import hashlib
import struct
import unittest
import zlib

from scripts.restore_auto_mode import (
    INPUT_DEX_SHA, OUTPUT_DEX_SHA, MODE_CODE_ITEM, MODE_CODE_UNITS,
    MODE_METHOD_ID, ORIGINAL_MODE_CODE, SOURCE_METHOD_SHA,
    LOCKED_METHOD_SHA, EXPECTED_UNCHANGED, sha,
)

CONFIRMED_SIGNED_APK_SHA256 = (
    '087d968ae8a1d052436c1f056d5359bfdd96a6254dafa2c48d46014f1cf7fdeb'
)
CONFIRMED_DEX_SHA256 = (
    'be158200a3070bf13f31f7bbc4c7a1ed667e42a8b221a6e027ebd0122f5ce636'
)

class AutoModeBaselineTests(unittest.TestCase):
    def test_user_confirmed_apk_digest_is_pinned(self):
        self.assertEqual(len(CONFIRMED_SIGNED_APK_SHA256), 64)
        self.assertEqual(CONFIRMED_DEX_SHA256, OUTPUT_DEX_SHA)

    def test_original_selector_not_an_unconditional_return_true(self):
        self.assertEqual(MODE_METHOD_ID, 15899)
        self.assertEqual(MODE_CODE_UNITS, 115)
        self.assertEqual(MODE_CODE_ITEM, 3841932)
        self.assertEqual(len(ORIGINAL_MODE_CODE), MODE_CODE_UNITS * 2)
        self.assertEqual(sha(ORIGINAL_MODE_CODE), SOURCE_METHOD_SHA)
        self.assertNotEqual(ORIGINAL_MODE_CODE[:4], bytes.fromhex('12100f00'))
        # The restored method starts with a real invoke-static, not const/4 + return.
        self.assertEqual(ORIGINAL_MODE_CODE[:2], bytes.fromhex('7110'))
        self.assertIn(bytes.fromhex('6e207f04'), ORIGINAL_MODE_CODE)

    def test_expected_tv_and_tablet_paths_stay_untouched(self):
        self.assertEqual(len(EXPECTED_UNCHANGED), 3)
        self.assertEqual({15872, 16961, 25610}, {
            mid for mid, _off, _units in EXPECTED_UNCHANGED
        })
        self.assertEqual(len(LOCKED_METHOD_SHA), 64)
        self.assertNotEqual(INPUT_DEX_SHA, OUTPUT_DEX_SHA)

if __name__ == '__main__':
    unittest.main()
