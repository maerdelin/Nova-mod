import inspect
import unittest
from scripts import webdav_hard_buffer_patch as p

class BufferingUiInvariantTests(unittest.TestCase):
    def method(self, text, signature):
        start = text.index(signature)
        end = text.index('.end method', start) + len('.end method')
        return text[start:end]

    def test_native_progress_ui_uses_main_thread_handler(self):
        ui = p.PLAYER_ACTIVITY_BUFFER_UI_SMALI
        self.assertIn('mHandler:Landroid/os/Handler;', ui)
        self.assertIn('const/4 v2, 0x1', ui)
        self.assertIn('sendEmptyMessage(I)Z', ui)
        self.assertIn('const/4 v2, 0x7', ui)
        self.assertNotIn('setVisibility(I)V', ui)

    def test_handler_message_7_hides_progress_and_does_not_invert_branch(self):
        src = inspect.getsource(p.patch_player_activity_handler_text)
        self.assertIn('if-eq v1, v2, :nova_buffer_hide_progress', src)
        self.assertNotIn('if-ne v1, v2, :nova_buffer_hide_progress', src)
        self.assertIn('const/16 p1, 0x8', src)
        self.assertIn('View;->setVisibility(I)V', src)

    def test_activity_reference_is_lifecycle_bounded(self):
        src = inspect.getsource(p.patch_player_activity_text)
        self.assertIn('sNetworkBufferActivity', src)
        self.assertIn('onCreate(Landroid/os/Bundle;)V', src)
        self.assertIn('sput-object p0', src)
        self.assertIn('onDestroy()V', src)
        self.assertIn('sput-object v0', src)

    def test_hard_pause_shows_and_resume_hides(self):
        pause = self.method(p.PLAYER_BUFFER_METHODS_SMALI, '.method public static bufferPauseCurrent()Z')
        resume = self.method(p.PLAYER_BUFFER_METHODS_SMALI, '.method public static bufferResumeCurrent()V')
        held = self.method(p.PLAYER_BUFFER_METHODS_SMALI, '.method public static bufferStartHeldCurrent()V')
        cancel = self.method(p.PLAYER_BUFFER_METHODS_SMALI, '.method public static cancelBufferPause()V')
        self.assertIn('const/4 v3, 0x1', pause)
        self.assertIn('setNetworkBufferingUi(Z)V', pause)
        self.assertIn('const/4 v3, 0x0', resume)
        self.assertIn('setNetworkBufferingUi(Z)V', resume)
        self.assertIn('const/4 v1, 0x0', held)
        self.assertIn('setNetworkBufferingUi(Z)V', held)
        self.assertIn('const/4 v0, 0x0', cancel)
        self.assertIn('setNetworkBufferingUi(Z)V', cancel)

    def test_initial_hold_and_fail_closed_show_loading(self):
        before = self.method(p.READ_AHEAD_SMALI, '.method public static beforeNativeStart(Landroid/net/Uri;)Z')
        for marker in (
            'INITIAL_HOLD prepared=1 wait_for_24MiB_floor',
            'INITIAL_HOLD webdav_without_guarded_media_stream fail_closed',
            'INITIAL_HOLD network_failure fail_closed',
        ):
            pos = before.index(marker)
            tail = before[pos:pos+700]
            self.assertIn('setNetworkBufferingUi(Z)V', tail, marker)

    def test_guarded_wait_and_watchdog_show_loading(self):
        await_m = self.method(p.READ_AHEAD_SMALI, '.method private awaitBudget(I)V')
        monitor = self.method(p.READ_AHEAD_SMALI, '.method public monitorLoop()V')
        self.assertIn('setNetworkBufferingUi(Z)V', await_m)
        self.assertIn('NETWORK_FAILURE_HARD_PAUSE fail_closed', monitor)
        self.assertIn('WATCHDOG_HARD_PAUSE buffer<24MiB', monitor)
        self.assertGreaterEqual(monitor.count('setNetworkBufferingUi(Z)V'), 2)

if __name__ == '__main__':
    unittest.main()
