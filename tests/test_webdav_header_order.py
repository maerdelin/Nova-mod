import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import webdav_fourfix_patch as patch

class HeaderOrderTests(unittest.TestCase):
    def test_interface_header_uses_roundtrip_canonical_order(self):
        src = '.class public LExample;\n.super Ljava/lang/Object;\n.source "example"\n'
        changed = patch.add_interface(src, 'LMarker;')
        self.assertEqual(changed, src.rstrip() + '\n.implements LMarker;\n')
        no_source = '.class public LExample;\n.super Ljava/lang/Object;\n'
        self.assertIn('.super Ljava/lang/Object;\n.implements LMarker;', patch.add_interface(no_source, 'LMarker;'))
        with self.assertRaises(RuntimeError): patch.add_interface(changed, 'LMarker;')
        with self.assertRaises(RuntimeError): patch.add_interface('.class public LExample;', 'LMarker;')

if __name__ == '__main__': unittest.main()
