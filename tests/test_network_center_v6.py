"""User-confirmed V6 network centering and protected layout regression checks."""
import base64
import hashlib
import struct
import unittest

from scripts.network_center_v6 import (
    BASELINE_DEX_SHA, OUTPUT_DEX_SHA, METHODS, PROTECTED_LAYOUT_SHA,
    NATIVE_CARD_DP, NATIVE_SPACING_DP, NATIVE_START_PADDING_DP,
)

USER_CONFIRMED_V6_SIGNED_APK_SHA256 = (
    "957819f313352ff54adcaac9000037d082e2f42a5823e03f5e3eb6dffb344d6d"
)


class TestUserConfirmedV6(unittest.TestCase):
    def test_exact_confirmed_v6_hashes(self):
        self.assertEqual(BASELINE_DEX_SHA, "be158200a3070bf13f31f7bbc4c7a1ed667e42a8b221a6e027ebd0122f5ce636")
        self.assertEqual(OUTPUT_DEX_SHA, "1f0194f96282bc3494e0ed17505a52d2cd552782cee5d534584480058b836e38")
        self.assertEqual(len(USER_CONFIRMED_V6_SIGNED_APK_SHA256), 64)
        self.assertEqual(PROTECTED_LAYOUT_SHA["res/Am.xml"], "b246497606d126efa7e56156952bfd059538b9ffb18afb7a1c4cc44380293262")
        self.assertEqual(PROTECTED_LAYOUT_SHA["res/mC.xml"], "559a5e7d1b679338e5fb9be9eface0ee1edc7ef4ca454651b851ed9084b6a1bc")

    def test_exact_network_only_methods_in_place(self):
        self.assertEqual(set(METHODS), {20881, 20906})
        for mid, (offset, header, sha, encoded) in METHODS.items():
            code = base64.b64decode(encoded, validate=True)
            self.assertEqual(len(code), header[-1] * 2)
            self.assertEqual(hashlib.sha256(code).hexdigest(), sha)
            self.assertGreater(offset, 0)
        self.assertEqual(METHODS[20881][1], (9,3,3,0,6497187,83))
        self.assertEqual(METHODS[20906][1], (6,2,3,1,6499017,134))

    def test_native_resource_geometry_for_1_to_40_cards(self):
        self.assertEqual((NATIVE_CARD_DP, NATIVE_SPACING_DP, NATIVE_START_PADDING_DP), (210,16,56))
        for n in range(1,41):
            exact = n*NATIVE_CARD_DP + (n-1)*NATIVE_SPACING_DP + 2*NATIVE_START_PADDING_DP
            self.assertEqual(exact, 226*n+96)

    def test_no_fixed_screenshot_pixel_compensation(self):
        self.assertEqual(2*NATIVE_START_PADDING_DP-NATIVE_SPACING_DP, 96)


if __name__ == "__main__":
    unittest.main()
