import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class PlaybackCompletionIsolationTests(unittest.TestCase):
    def test_patch_has_no_download_or_rebuffer_dependency(self):
        text=(ROOT/'scripts/playback_completion_patch.py').read_text()
        for forbidden in ('raw_prefetch','NOVA_RAW10X','NOVA_RAW_10X_POLICY',
                          'rebuffer_low','rebuffer_resume','NovaWebdavOpenPolicy',
                          'StreamOverHttp','source_size'):
            self.assertNotIn(forbidden,text,forbidden)
    def test_patch_uses_player_decoder_and_existing_stop_path(self):
        text=(ROOT/'scripts/playback_completion_patch.py').read_text()
        self.assertIn('sfdec_send_eos',text)
        self.assertIn('SFDEC_READ_EOS',text)
        self.assertIn('sink->drained = videosink_drained',text)
        self.assertIn('NOVA_PLAYBACK_COMPLETE',text)
        self.assertIn('s->stop( s );',text)
    def test_transport_patch_remains_separate(self):
        workflow=(ROOT/'.github/workflows/nova-video-player-mod.yml').read_text()
        self.assertLess(workflow.index('native_rebuffer_patch.py'),workflow.index('playback_completion_patch.py'))

if __name__=='__main__':unittest.main()
