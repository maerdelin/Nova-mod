import unittest
from scripts.hide_home_header import (
    ORIGINAL_CALL,HIDDEN_CALL,ICON_HEADER_CALL,CODE_ITEM,
    HEADER_INVOKE_UNIT,INPUT_DEX_SHA,OUTPUT_DEX_SHA
)
class TestHomeHeader(unittest.TestCase):
    def test_home_invoke_register_only(self):
        self.assertEqual(len(ORIGINAL_CALL),len(HIDDEN_CALL))
        self.assertEqual(ORIGINAL_CALL[:4],HIDDEN_CALL[:4])
        self.assertEqual(ORIGINAL_CALL[5:],HIDDEN_CALL[5:])
        self.assertEqual((ORIGINAL_CALL[4],HIDDEN_CALL[4]),(0x51,0x31))
        self.assertEqual(ICON_HEADER_CALL,bytes.fromhex('6e20a9dc1200'))
    def test_pinned_method(self):
        self.assertEqual((CODE_ITEM,HEADER_INVOKE_UNIT),(4128208,58))
        self.assertEqual(len(INPUT_DEX_SHA),64)
        self.assertEqual(len(OUTPUT_DEX_SHA),64)
        self.assertNotEqual(INPUT_DEX_SHA,OUTPUT_DEX_SHA)
