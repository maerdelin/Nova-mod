import unittest
from scripts import webdav_hardgate_patch as h

class HardGatePolicyTest(unittest.TestCase):
    def test_gate_is_synchronized_and_stream_scoped(self):
        s=h.WEB_DAV_BUFFER_GATE_SMALI
        self.assertIn('.method public static declared-synchronized onLow(Ljava/lang/Object;)V',s)
        self.assertIn('.method public static declared-synchronized onReady(Ljava/lang/Object;)V',s)
        self.assertIn('sSource:Ljava/lang/Object;',s)
        self.assertIn('sPlayWanted:Z',s)

    def test_decoder_pause_resume_are_direct(self):
        s=h.PLAYER_BUFFER_METHODS
        self.assertIn('IMediaPlayer;->pause()V',s)
        self.assertIn('IMediaPlayer;->start()V',s)
        self.assertIn('mTargetState:I',s)
        self.assertIn('mFocusSuspended:Z',s)

    def test_read_return_is_post_consume_gated(self):
        self.assertIn('POST_READ_LOW remaining<24MiB pause_completed_before_return',h.AFTER_CONSUME_SMALI)
        self.assertIn('WebDavBufferGate;->onLow',h.AFTER_CONSUME_SMALI)

if __name__=='__main__':
    unittest.main()
