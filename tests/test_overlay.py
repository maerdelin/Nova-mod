#!/usr/bin/env python3
"""Offline guardrails; cloud build also checks real upstream blob SHA + Gradle."""
import importlib.util
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('nova_ui', ROOT / 'ui/apply.py')
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)

class OverlayTests(unittest.TestCase):
    def test_git_blob(self):
        self.assertEqual(ui.git_blob(b'hello\n'), 'ce013625030ba8dba906f756967f9e9ca394464a')

    def test_anchors_must_be_unique(self):
        with self.assertRaises(ValueError):
            ui.replace_one('a a', 'a', 'b', 'test')
        with self.assertRaises(ValueError):
            ui.replace_one('bbb', 'a', 'b', 'test')

    def test_fixed_upstream_shas(self):
        self.assertEqual(len(ui.BLOBS), 10)
        self.assertTrue(all(len(blob) == 40 for blob in ui.BLOBS.values()))

    def test_manifest_pin(self):
        root = ET.parse(ROOT / 'upstream/locked.xml').getroot()
        projects = root.findall('extend-project')
        self.assertEqual(len(projects), 21)
        self.assertTrue(all(len(p.attrib['revision']) == 40 for p in projects))
        self.assertEqual(len({p.attrib['name'] for p in projects}), 21)

    def test_title_no_bottom_constraint(self):
        xml = '        android:layout_alignTop="@id/title_orb"\n        android:layout_alignBottom="@id/title_orb"\n'
        out = ui.process('res/layout/lb_my_title_view.xml', xml)
        self.assertIn('android:translationY="-5.2dp"', out)
        self.assertNotIn('layout_alignBottom', out)

if __name__ == '__main__':
    unittest.main()
