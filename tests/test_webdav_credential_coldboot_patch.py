from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = (ROOT / "scripts/webdav_credential_coldboot_patch.py").read_text()


class CredentialColdbootStructuralLocatorTests(unittest.TestCase):
    def test_no_fixed_code_offset_remains(self):
        self.assertNotIn("CODE_OFF =", PATCH)
        self.assertNotIn("INSNS_OFF =", PATCH)
        self.assertNotIn("4980816", PATCH)

    def test_target_is_located_from_dex_tables(self):
        for token in (
            "dex_strings",
            "dex_types",
            "dex_methods",
            "iter_class_methods",
            "find_target_code_off",
            '"/WebdavUtils;"',
            '"getSardine"',
        ):
            self.assertIn(token, PATCH)

    def test_sensitive_method_ids_are_resolved_dynamically(self):
        for token in (
            '"/NetworkCredentialsDatabase;"',
            '"getInstance"',
            '"getContext"',
            '"loadCredentials"',
            "find_method_idx",
        ):
            self.assertIn(token, PATCH)
        self.assertNotIn("12993", PATCH)
        self.assertNotIn("13714", PATCH)
        self.assertNotIn("12994", PATCH)

    def test_reviewed_target_shape_is_still_fail_closed(self):
        self.assertIn("(regs, ins, tries, size) == (13, 2, 2, 256)", PATCH)
        self.assertIn("words(70, 2) != [0x0038, 43]", PATCH)
        self.assertIn("words(72)[0] & 0xff != 0x22", PATCH)


if __name__ == "__main__":
    unittest.main()
