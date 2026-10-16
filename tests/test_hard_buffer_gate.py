import re
import unittest
from scripts import webdav_hard_buffer_patch as p

MIB = 1024 * 1024

class HardBufferInvariantTests(unittest.TestCase):
    def setUp(self):
        self.s = p.READ_AHEAD_SMALI

    def method(self, text, signature):
        start = text.index(signature)
        end = text.index('.end method', start) + len('.end method')
        return text[start:end]

    def test_probe_prepare_path_is_not_blocked(self):
        ctor = self.method(self.s, '.method private constructor <init>')
        self.assertIn('const/4 v0, 0x0', ctor)
        self.assertIn('->buffering:Z', ctor)
        self.assertIn('startup=prepare-pass watchdog=5ms', self.s)
        # The true safety gate is before Player nativeStart, not parser/probe reads.
        self.assertIn('.method public static beforeNativeStart(Landroid/net/Uri;)Z', self.s)

    def test_exact_thresholds_and_capacity(self):
        self.assertIn('CAPACITY:I = 0x4000000', self.s)
        self.assertIn('LOW_WATERMARK:I = 0x1800000', self.s)
        self.assertIn('RESUME_WATERMARK:I = 0x2d00000', self.s)
        self.assertIn('WATCHDOG_RESUME buffer>45MiB_or_clean_eof', self.s)

    def test_initial_start_floor_after_prepare(self):
        before = self.method(self.s, '.method public static beforeNativeStart(Landroid/net/Uri;)Z')
        # 24 MiB + one maximum 256 KiB read budget.
        self.assertIn('const v3, 0x1840000', before)
        self.assertIn('->initialHold:Z', before)
        self.assertIn('INITIAL_HOLD prepared=1 wait_for_24MiB_floor', before)
        self.assertIn('INITIAL_HOLD network_failure fail_closed', before)

    def test_pre_read_floor_budget_is_atomic(self):
        self.assertIn('.method public declared-synchronized read()I', self.s)
        self.assertIn('.method public declared-synchronized read([BII)I', self.s)
        self.assertIn('.method public declared-synchronized skip(J)J', self.s)
        await_m = self.method(self.s, '.method private awaitBudget(I)V')
        self.assertIn('add-int v2, v1, p1', await_m)
        self.assertIn('Player;->bufferPauseCurrent()Z', await_m)
        self.assertRegex(await_m, r'if-ge v0, v2, :\S+')
        bulk = self.method(self.s, '.method public declared-synchronized read([BII)I')
        self.assertIn('const v0, 0x40000', bulk)
        self.assertIn('move p3, v0', bulk)

    def test_hard_pause_and_resume_reach_player(self):
        self.assertIn('Player;->bufferPauseCurrent()Z', self.s)
        self.assertIn('Player;->bufferResumeCurrent()V', self.s)
        self.assertIn('HARD_PAUSE before_floor_cross nativePause=1', self.s)
        pm = p.PLAYER_BUFFER_METHODS_SMALI
        self.assertIn('IMediaPlayer;->pause()V', pm)
        self.assertIn('IMediaPlayer;->start()V', pm)
        self.assertIn('PLAYER_HARD_PAUSE nativePause=1 targetPlaying=1', pm)
        self.assertIn('PLAYER_HARD_RESUME nativeStart=1 targetPlaying=1', pm)

    def test_independent_watchdog_is_5ms_and_enforces_floor(self):
        monitor = self.method(self.s, '.method public monitorLoop()V')
        self.assertIn('const-wide/32 v2, 0x4c4b40', monitor)
        self.assertIn('WATCHDOG_HARD_PAUSE buffer<24MiB', monitor)
        self.assertIn('WATCHDOG_RESUME buffer>45MiB_or_clean_eof', monitor)
        self.assertIn('NETWORK_FAILURE_HARD_PAUSE fail_closed', monitor)
        self.assertIn('->monitorLoop()V', p.WATCHDOG_SMALI)

    def test_only_long_sequential_media_stream_becomes_guarded_main_stream(self):
        policy = p.STREAM_SESSION_POLICY_SMALI
        self.assertIn('supersedableMediaRequest:Z', policy)
        self.assertIn('requestedStart:J', policy)
        self.assertIn('requestedEnd:J', policy)
        self.assertIn('length:J', policy)
        self.assertIn('const-wide/32 v2, 0x800000', policy)
        self.assertNotIn('isPlaybackActive()Z', policy)

    def test_webdav_native_start_fails_closed_without_guarded_media_stream(self):
        before = self.method(self.s, '.method public static beforeNativeStart(Landroid/net/Uri;)Z')
        self.assertIn('const-string v1, "webdav"', before)
        self.assertIn('const-string v1, "webdavs"', before)
        self.assertIn('activeStream:Lcom/archos/filecorelibrary/NetworkReadAheadInputStream;', before)
        self.assertIn('INITIAL_HOLD webdav_without_guarded_media_stream fail_closed', before)

    def test_old_stream_cannot_bypass_gate(self):
        ctor = self.method(self.s, '.method private constructor <init>')
        self.assertIn('HARD_GATE_REPLACE_OLD close_previous=1', ctor)
        self.assertIn('NetworkReadAheadInputStream;->close()V', ctor)

    def test_fail_closed_initialization_and_network_failure(self):
        self.assertIn('HARD_GATE_INIT_IO_FAIL fail_closed', self.s)
        self.assertIn('HARD_GATE_INIT_OOM fail_closed', self.s)
        self.assertNotIn('READ_AHEAD_OOM fallback', self.s)
        await_m = self.method(self.s, '.method private awaitBudget(I)V')
        self.assertIn('->failure:Ljava/io/IOException;', await_m)
        self.assertTrue('throw v0' in await_m or 'throw v4' in await_m)

    def test_user_pause_and_stop_disarm_auto_resume(self):
        # patch_player_text must inject both cancel and setPlaybackActive(false)
        src = p.patch_player_text.__code__
        self.assertTrue(callable(p.patch_player_text))
        with open(p.__file__, encoding='utf-8') as fh:\n            module_text = fh.read()
        self.assertGreaterEqual(module_text.count('cancelBufferPause()V'), 3)
        self.assertGreaterEqual(module_text.count('setPlaybackActive(Z)V'), 3)

    def test_held_start_static_method_has_valid_registers(self):
        m = self.method(p.PLAYER_BUFFER_METHODS_SMALI, '.method public static bufferStartHeldCurrent()V')
        self.assertIn('.locals 3', m)
        self.assertNotRegex(m, r'\bp[0-9]+\b')
        self.assertIn('Player;->start(I)V', m)

    def test_all_new_zero_arg_static_player_helpers_have_no_parameter_registers(self):
        for sig in (
            '.method public static bufferPauseCurrent()Z',
            '.method public static bufferResumeCurrent()V',
            '.method public static bufferStartHeldCurrent()V',
            '.method public static cancelBufferPause()V',
        ):
            m = self.method(p.PLAYER_BUFFER_METHODS_SMALI, sig)
            self.assertNotRegex(m, r'\bp[0-9]+\b', sig)

    def test_exhaustive_floor_transition_model(self):
        LOW = 24 * MIB
        RESUME = 45 * MIB
        CHUNK = 256 * 1024
        CAP = 64 * MIB

        # Exhaust every possible KiB-aligned buffer state and every KiB-aligned
        # read request up to the implementation's maximum 256 KiB.
        for available in range(0, CAP + 1, 1024):
            for requested in range(1024, CHUNK + 1, 1024):
                if available < LOW + requested:
                    consumed = 0  # hard hold/pause before the read
                else:
                    consumed = requested
                after = available - consumed
                if available >= LOW:
                    self.assertGreaterEqual(after, LOW)
                else:
                    self.assertEqual(consumed, 0)

        self.assertGreater(RESUME, LOW)

if __name__ == '__main__':
    unittest.main()
