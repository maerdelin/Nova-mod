"""Evidence requirements for seek test, including the Run583 failure log."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from smoke_mp4_raw_seek_race import seek_action_result

PREFIX = 'M0\n10-22 15:37:36.080 D avos_player: avos_mp_video_seek current_pos=5366 to pos=10366 direction=0\n'
RAW = '10-22 15:37:36.094 D avos_player: NOVA_RAW128_SEEK: target=4959941 result=4959941 generation=1\n'
START = '10-22 15:37:36.362 D avos_player: avos_mp_start:\n'
READ1 = '10-22 15:37:36.5 D avos_player: NOVA_RAW128: produced=35703238 consumed=27412218 eof=0\n'
READ2 = '10-22 15:37:37.1 D avos_player: NOVA_RAW128: produced=51038662 consumed=42878714 eof=0\n'

class SeekRaceEvidenceTests(unittest.TestCase):
    def test_run583_seek_progresses_without_optional_ui_timer(self):
        event = seek_action_result(PREFIX + RAW + START + READ1 + READ2, 'M0', 1)
        self.assertEqual((event['from'], event['to'], event['raw_generation']), (5366,10366,1))
        self.assertGreater(event['post_seek_consumed_delta'], 0)
    def test_old_or_missing_scope_cannot_pass(self):
        self.assertIsNone(seek_action_result(PREFIX + RAW + START + READ1 + READ2, 'M1', 1))
        self.assertIsNone(seek_action_result(PREFIX + RAW + START + READ1 + READ2 + '\nM1', 'M1', 1))
    def test_seek_requires_native_seek_and_restart(self):
        self.assertIsNone(seek_action_result(PREFIX + START + READ1 + READ2, 'M0', 1))
        self.assertIsNone(seek_action_result(PREFIX + RAW + READ1 + READ2, 'M0', 1))
        self.assertIsNone(seek_action_result(PREFIX + RAW.replace('result=4959941','result=-1') + START + READ1 + READ2, 'M0', 1))
    def test_seek_requires_real_consumption(self):
        self.assertIsNone(seek_action_result(PREFIX + RAW + START + READ1, 'M0', 1))
        self.assertIsNone(seek_action_result(PREFIX + RAW + START + READ1 + READ1, 'M0', 1))
    def test_seek_direction(self):
        self.assertIsNone(seek_action_result(PREFIX + RAW + START + READ1 + READ2, 'M0', -1))
        backward = PREFIX.replace('current_pos=5366 to pos=10366','current_pos=10366 to pos=5366')
        self.assertEqual(seek_action_result(backward + RAW + START + READ1 + READ2,'M0',-1)['to'],5366)

if __name__ == '__main__':
    unittest.main()
