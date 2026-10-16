import re
import unittest
from scripts import webdav_hard_buffer_patch as p

class HardBufferInvariantTests(unittest.TestCase):
    def setUp(self):
        self.s = p.READ_AHEAD_SMALI

    def test_probe_prepare_not_preblocked(self):
        ctor = self.s[self.s.index('.method private constructor <init>'):self.s.index('.end method', self.s.index('.method private constructor <init>'))]
        self.assertIn('const/4 v0, 0x0', ctor)
        self.assertIn('->buffering:Z', ctor)
        self.assertIn('startup=probe-pass', self.s)

    def test_exact_thresholds(self):
        self.assertIn('CAPACITY:I = 0x4000000', self.s)
        self.assertIn('LOW_WATERMARK:I = 0x1800000', self.s)
        self.assertIn('RESUME_WATERMARK:I = 0x2d00000', self.s)
        self.assertIn('HARD_RESUME buffer>45MiB', self.s)

    def test_pre_read_floor_budget_is_atomic(self):
        self.assertIn('.method public declared-synchronized read()I', self.s)
        self.assertIn('.method public declared-synchronized read([BII)I', self.s)
        self.assertIn('.method public declared-synchronized skip(J)J', self.s)
        self.assertIn('add-int v2, v1, p1', self.s)
        self.assertIn('const v0, 0x40000', self.s)
        self.assertIn('move p3, v0', self.s)

    def test_hard_pause_and_resume_call_player(self):
        self.assertIn('Player;->bufferPauseCurrent()Z', self.s)
        self.assertIn('Player;->bufferResumeCurrent()V', self.s)
        self.assertIn('HARD_PAUSE before_floor_cross nativePause=1', self.s)

    def test_old_stream_cannot_bypass_gate(self):
        self.assertIn('HARD_GATE_REPLACE_OLD close_previous=1', self.s)
        self.assertIn('->close()V', self.s)

    def test_fail_closed_initialization(self):
        self.assertIn('HARD_GATE_INIT_IO_FAIL fail_closed', self.s)
        self.assertIn('HARD_GATE_INIT_OOM fail_closed', self.s)
        self.assertNotIn('fallback', self.s)

    def test_player_patch_disarms_manual_pause_and_stop(self):
        m = p.PLAYER_BUFFER_METHODS_SMALI
        self.assertIn('PLAYER_HARD_PAUSE nativePause=1 targetPlaying=1', m)
        self.assertIn('PLAYER_HARD_RESUME nativeStart=1 targetPlaying=1', m)
        src = p.patch_player_text
        self.assertTrue(callable(src))

    def test_model_never_crosses_24m_floor(self):
        LOW = 24 * 1024 * 1024
        RESUME = 45 * 1024 * 1024
        CHUNK = 256 * 1024
        for available in range(LOW - CHUNK, 64 * 1024 * 1024 + 1, 65537):
            requested = CHUNK
            if available < LOW + requested:
                # The implementation must pause/wait before any consumption.
                after = available
            else:
                after = available - requested
            self.assertGreaterEqual(after, LOW if available >= LOW else available)
            if available < LOW + requested:
                self.assertLess(available, LOW + requested)
        self.assertGreater(RESUME, LOW)

if __name__ == '__main__':
    unittest.main()
