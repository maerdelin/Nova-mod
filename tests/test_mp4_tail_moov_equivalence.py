"""Protect both legitimate late-moov paths without weakening byte proof."""
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from smoke_mp4_tail_moov import verify_tail_access

SIZE=13084557
MOOV=13072814
LOG='''NOVA_RAW128_OPEN: phase=pre_probe
NOVA_RAW128_SEEK: target=13072814 result=13072814 generation=1
NOVA_STARTUP_TRACE probe_done t=123 streams=2
NOVA_STARTUP_TRACE first_frame_sink t=234 pts=0
'''

class LateMoovSourceProofTests(unittest.TestCase):
    def prove(self,receipts,log=LOG):
        return verify_tail_access(SIZE,MOOV,receipts,log,
                                  log.index('NOVA_RAW128_OPEN'),
                                  log.index('NOVA_STARTUP_TRACE probe_done'))

    def test_completed_0_start_body_is_valid_cached_seek(self):
        out=self.prove([{'start':0,'delivered':SIZE,'complete':True}])
        self.assertEqual(out['tail_access_path'],'complete-head-prefetch')
        self.assertEqual(out['exact_tail_seeks'],[MOOV])
        self.assertFalse(out['remote_tail_range'])

    def test_verified_http_tail_range_remains_valid(self):
        out=self.prove([{'start':MOOV,'delivered':SIZE-MOOV,'complete':True}])
        self.assertEqual(out['tail_access_path'],'remote-tail-range')
        self.assertTrue(out['remote_tail_range'])

    def test_partial_origin_without_tail_range_fails(self):
        with self.assertRaisesRegex(RuntimeError,'Neither remote'):
            self.prove([{'start':0,'delivered':SIZE-1,'complete':False}])

    def test_wrong_seek_result_fails_even_when_body_completed(self):
        bad=LOG.replace('result=13072814','result=-5')
        with self.assertRaisesRegex(RuntimeError,'No exact RAW'):
            self.prove([{'start':0,'delivered':SIZE,'complete':True}],bad)

    def test_seek_after_probe_is_not_proof(self):
        bad=LOG.replace('NOVA_RAW128_SEEK: target=13072814 result=13072814 generation=1\n','')
        bad+='NOVA_RAW128_SEEK: target=13072814 result=13072814 generation=1\n'
        with self.assertRaisesRegex(RuntimeError,'No exact RAW'):
            self.prove([{'start':0,'delivered':SIZE,'complete':True}],bad)

if __name__=='__main__':
    unittest.main()
