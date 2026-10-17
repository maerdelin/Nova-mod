import unittest
from pathlib import Path
from scripts import rebuffer_poststart as r
from scripts import granular as g

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
        generated = r.READ_AHEAD_SMALI + r.PLAYER_HELPERS_SMALI
        for token in ('initialHold', 'beforeNativeStart', 'awaitBudget', 'bufferStartHeldCurrent', 'INITIAL_HOLD'):
            self.assertNotIn(token, generated)

    def test_startup_has_no_watermark_gate(self):
        started = r._method(r.READ_AHEAD_SMALI, ' onPlaybackStarted()V').group(0)
        self.assertNotIn('0x1800000', started)
        self.assertNotIn('0x2d00000', started)
        self.assertNotIn('ensureBudget', started)
        self.assertNotIn('initialHold', started)
        self.assertIn('PLAYBACK_STARTED main-start-complete protection-waiting-for-24MiB', started)

    def test_header_field_order_is_nonsemantic_but_field_content_is_strict(self):
        a = """.class public Lx;
.super Ljava/lang/Object;
.source "X.java"
.field private a:I = 0x1
.field public static b:Ljava/lang/String;
"""
        b = """.class public Lx;
.super Ljava/lang/Object;
.source "X.java"
.field public static b:Ljava/lang/String;
.field private a:I = 0x1
"""
        changed = """.class public Lx;
.super Ljava/lang/Object;
.source "X.java"
.field public static b:Ljava/lang/String;
.field private a:I = 0x2
"""
        ha = r._logical_header_field_order_insensitive(a, {}, g)
        hb = r._logical_header_field_order_insensitive(b, {}, g)
        hc = r._logical_header_field_order_insensitive(changed, {}, g)
        self.assertEqual(ha, hb)
        self.assertNotEqual(ha, hc)

    def test_only_vm_default_static_values_are_normalized(self):
        self.assertEqual(r._canonical_field('.field public static flag:Z = false'),
                         '.field public static flag:Z')
        self.assertEqual(r._canonical_field('.field public static count:I = 0x0'),
                         '.field public static count:I')
        self.assertEqual(r._canonical_field('.field public static obj:Ljava/lang/Object; = null'),
                         '.field public static obj:Ljava/lang/Object;')
        self.assertNotEqual(r._canonical_field('.field public static flag:Z = true'),
                            '.field public static flag:Z')
        self.assertNotEqual(r._canonical_field('.field public static count:I = 0x1'),
                            '.field public static count:I')
        self.assertNotEqual(r._canonical_field('.field public static obj:Ljava/lang/Object; = "x"'),
                            '.field public static obj:Ljava/lang/Object;')

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

    def test_bulk_read_is_capped_before_floor_check(self):
        s = r.READ_AHEAD_SMALI
        read = r._method(s, ' read([BII)I').group(0)
        self.assertIn('const v0, 0x40000', read)
        self.assertIn('move p3, v0', read)
        self.assertLess(read.index('move p3, v0'), read.index('ensureBudget(I)V'))

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
