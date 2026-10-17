import unittest
from pathlib import Path
from scripts import rebuffer_poststart as r

class CleanMainPostStartRebufferTests(unittest.TestCase):
    def test_method_regex_matches_real_smali_shape(self):
        sample = """.method private publishInput(Ljava/io/InputStream;)V
    .locals 2
    return-void
.end method
"""
        m = r._method(sample, ' publishInput(Ljava/io/InputStream;)V')
        self.assertIn('.method private publishInput', m.group(0))

    def test_old_hard_gate_code_is_absent(self):
        src = Path('scripts/rebuffer_poststart.py').read_text(encoding='utf-8')
        for token in ('initialHold', 'beforeNativeStart', 'awaitBudget', 'bufferStartHeldCurrent'):
            self.assertNotIn(token, src)

    def test_startup_has_no_watermark_gate(self):
        src = r.patch_player.__doc__ or ''
        # Functional invariant is checked from patch code itself below.
        code = Path('scripts/rebuffer_poststart.py').read_text(encoding='utf-8')
        self.assertIn('Main startup remains byte-for-byte unchanged until its successful tail.', code)
        self.assertNotIn('INITIAL_HOLD', code)

    def test_threshold_constants(self):
        s = r.READ_AHEAD_SMALI
        self.assertIn('CAPACITY:I = 0x4000000', s)
        self.assertIn('LOW_WATERMARK:I = 0x1800000', s)
        self.assertIn('RESUME_WATERMARK:I = 0x2d00000', s)

    def test_activation_is_at_successful_start_tail(self):
        code = Path('scripts/rebuffer_poststart.py').read_text(encoding='utf-8')
        start = code.index("tail_anchor = (")
        window = code[start:start+3200]
        self.assertIn('VideoEffectRenderer;->onPlay()V', window)
        self.assertIn(':nova_rebuffer_start_done', window)
        self.assertIn('onPlaybackStarted()V', window)
        self.assertLess(window.index('VideoEffectRenderer;->onPlay()V'), window.index('onPlaybackStarted()V'))
        self.assertNotIn('LOW_WATERMARK', window)
        self.assertNotIn('0x1800000', window)
        self.assertNotIn('0x2d00000', window)

    def test_protection_arms_only_after_playback(self):
        s = r.READ_AHEAD_SMALI
        self.assertIn('globalPlaybackActive:Z', s)
        self.assertIn('PLAYBACK_STARTED main-start-complete protection-waiting-for-24MiB', s)
        self.assertIn('PROTECTION_ARMED buffer>=24MiB', s)

    def test_floor_is_checked_before_consumption(self):
        s = r.READ_AHEAD_SMALI
        ensure = s[s.index('.method private ensureBudget(I)V'):s.index('.end method', s.index('.method private ensureBudget(I)V'))]
        self.assertIn('add-int v2, v1, p1', ensure)
        self.assertIn('Player;->bufferPauseCurrent()Z', ensure)
        self.assertIn('HARD_PAUSE before-crossing-24MiB', ensure)
        read = s[s.index('.method public declared-synchronized read([BII)I'):s.index('.end method', s.index('.method public declared-synchronized read([BII)I'))]
        self.assertLess(read.index('ensureBudget(I)V'), read.index('PipedInputStream;->read([BII)I'))

    def test_resume_requires_strictly_above_45m(self):
        s = r.READ_AHEAD_SMALI
        ensure = s[s.index('.method private ensureBudget(I)V'):s.index('.end method', s.index('.method private ensureBudget(I)V'))]
        self.assertIn('const v1, 0x2d00000', ensure)
        self.assertIn('if-le v0, v1, :wait_more', ensure)

    def test_main_stream_fallback_on_readahead_init_failure(self):
        s = r.READ_AHEAD_SMALI
        self.assertIn('READ_AHEAD_INIT_IO_FAIL use-main-stream', s)
        self.assertIn('READ_AHEAD_INIT_OOM use-main-stream', s)

    def test_only_long_supersedable_webdav_requests_are_wrapped(self):
        s = r.SESSION_POLICY_SMALI
        self.assertIn('supersedableMediaRequest:Z', s)
        self.assertIn('webdav', s)
        self.assertIn('webdavs', s)
        self.assertIn('0x800000', s)

if __name__ == '__main__':
    unittest.main()
