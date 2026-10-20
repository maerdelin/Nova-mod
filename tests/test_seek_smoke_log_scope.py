from pathlib import Path
import sys, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from smoke_seek_playback import action_result

class SmokeLogScopeTests(unittest.TestCase):
    def test_old_hide_cannot_satisfy_new_seek(self):
        log='HIDE_READY\nHIDE_DONE\nMARK\navos_mp_video_seek current_pos=6104 to pos=11104\nNOVA_ISO_TIME_SEEK byteMode=0\nHIDE_READY\n'
        self.assertIsNone(action_result(log,'MARK',1))
        self.assertEqual(action_result(log+'HIDE_DONE\n','MARK',1)[:2],(6104,11104))
    def test_direction_and_marker_must_match(self):
        log='FORWARD\navos_mp_video_seek current_pos=6104 to pos=11104\nNOVA_ISO_TIME_SEEK byteMode=0\nHIDE_READY\nHIDE_DONE\nBACKWARD\n'
        self.assertIsNone(action_result(log,'BACKWARD',-1))
        self.assertIsNone(action_result(log,'FORWARD',-1))
        self.assertIsNone(action_result(log,'MISSING',1))
    def test_newer_seek_needs_its_own_hide(self):
        log='MARK\navos_mp_video_seek current_pos=1000 to pos=6000\nNOVA_ISO_TIME_SEEK byteMode=0\nHIDE_READY\nHIDE_DONE\navos_mp_video_seek current_pos=6500 to pos=11500\nNOVA_ISO_TIME_SEEK byteMode=0\nHIDE_READY\n'
        self.assertIsNone(action_result(log,'MARK',1))
        self.assertEqual(action_result(log+'HIDE_DONE\n','MARK',1)[:2],(6500,11500))
if __name__=='__main__':unittest.main()
