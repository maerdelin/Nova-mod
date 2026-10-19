"""Regression tests for porting the last working Blu-ray ISO proxy onto Run377."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import iso_fast_probe_patch
import iso_patch


class TestIsoRun377Integration(unittest.TestCase):
    def test_iso_fast_probe_leaves_generic_probe_intact(self):
        original = "BEGIN\n" + iso_fast_probe_patch.OLD + "\nNOVA_TS_BITRATE:\nEND\n"
        output = iso_fast_probe_patch.transform(original)
        self.assertEqual(output.count("NOVA_ISO_FAST_PROBE:"), 1)
        self.assertIn('"skip_estimate_duration_from_pts", "1"', output)
        self.assertIn('} else if (nova_iso_proxy) {', output)
        self.assertIn('} else {\n\t\tav_dict_set(&ff_p->fmt_opts, "probesize", "10000000", 0);', output)
        self.assertIn("NOVA_TS_BITRATE:", output)
        with self.assertRaises(RuntimeError):
            iso_fast_probe_patch.transform(output)

    def test_iso_player_hooks_are_present(self):
        self.assertIn("BlurayIsoProxy;->resolve", iso_patch.patch_player_text.__code__.co_consts.__repr__())
        self.assertIn("video/x-bluray-iso", iso_patch.MIME_NEW)
        self.assertIn("StreamOverHttp;-><init>", iso_patch.PROXY_SMALI)
        self.assertIn("IsoPlayerFactory;->create", iso_patch.patch_force_avos_player_text.__code__.co_consts.__repr__())

    def test_proxy_uses_localhost_mpegts_title_and_encryption_check(self):
        c = (ROOT / "iso" / "nova_iso.c").read_text()
        for needle in ("bd_open_stream(", "bd_get_main_title(", "bd_select_title(",
                       "bd_get_title_size(", "CACHE_MODE playback persistent_range=1",
                       "main.m2ts?mpegts&nova_iso=1", "AACS encrypted Blu-ray ISO"):
            self.assertIn(needle, c)

    def test_iso_bridge_does_not_overwrite_base_avos(self):
        s = (ROOT / "scripts" / "iso_patch.py").read_text()
        self.assertNotIn("shutil.copyfile(avos_src", s)
        self.assertIn("libnova_iso.so", s)


if __name__ == "__main__":
    unittest.main()
