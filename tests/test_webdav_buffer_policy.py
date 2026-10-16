import unittest
from scripts import webdav_buffer_patch as p

class SimpleWebdavBufferPolicyTest(unittest.TestCase):
    def test_thresholds_are_locked(self):
        s = p.READ_AHEAD_SMALI
        self.assertIn('.field private static final CAPACITY:I = 0x4000000', s)
        self.assertIn('.field private static final LOW_WATERMARK:I = 0x1800000', s)
        self.assertIn('.field private static final START_WATERMARK:I = 0x2d00000', s)
        self.assertIn('BUFFER_LOW available<24MiB wait>45MiB', s)
        self.assertIn('BUFFER_READY available>45MiB', s)
        self.assertNotIn('rebuffer=16/24/28MiB', s)
        self.assertNotIn('low=2MiB', s)

    def test_resume_is_strictly_above_45(self):
        s = p.READ_AHEAD_SMALI
        self.assertIn('const v1, 0x2d00000', s)
        self.assertIn('if-le v0, v1, :wait_more', s)

    def test_low_trigger_is_strictly_below_24(self):
        s = p.READ_AHEAD_SMALI
        self.assertIn('const v1, 0x1800000', s)
        self.assertIn('if-ge v0, v1, :return', s)

if __name__ == '__main__':
    unittest.main()
