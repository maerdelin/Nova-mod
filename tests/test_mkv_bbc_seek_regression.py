"""BBC MKV isolated GET and bounded Seek source regressions against Run687."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
def src(path):return (ROOT/path).read_text()

class BbcMkvRegression(unittest.TestCase):
    def test_only_mkv_uses_live_one_get_and_206_validation(self):
        n=src("iso/nova_transport.c")
        java=src("scripts/direct_transport_apply.py")
        self.assertIn('strncasecmp(end-4,".mkv",4)==0',n)
        self.assertIn('const int mkv=(!jiso && origin && nova_is_mkv_origin_url(origin));',n)
        self.assertIn('session_create_file(env,origin,original_auth',n)
        self.assertIn('session_create(url,headers ? headers : "",jiso ? 1 : 0)',n)
        self.assertIn('const-string v13, ".mkv"',java)
        self.assertIn(':nova_legacy_redirect',java)
        self.assertIn('goto :nova_mkv_single_get',java)
        self.assertIn('DirectRangeHttp.smali").write_text(DIRECT_RANGE_HTTP)',java)
        self.assertIn('status!=206 && !(status==200 && target==0)',n)
        self.assertIn('first!=target || last<first',n)
        self.assertIn('total<=0 || last>=total',n)
        self.assertIn('sameOrigin(Ljava/net/URL;Ljava/net/URL;)',java)
        self.assertIn('NOVA_MKV_RANGE_RETRY_V2',n)
        self.assertIn('if(nova_weak_terminal_error(rc))return rc;',n)

    def test_run680_iso_seek_fragment_is_unchanged(self):
        n=src("iso/nova_transport.c")
        ref=src("tests/fixtures/run680_iso_seek.cfrag")
        start=n.index("if (s->mode == NOVA_MODE_BLURAY_ISO) {\n            int64_t current = bd_tell")
        end=n.index("        } else {\n            int64_t target = offset;",start)
        self.assertEqual(n[start:end],ref)
        self.assertIn("nova_file_seek_retry(s,target)",n)
        self.assertIn("nova_upstream_read_some_retry(s, dst, size)",n)
        self.assertIn("NOVA_NONISO_SEEK_HEAL_V1",n)

    def test_mkv_seek_cues_and_bounded_failures(self):
        p=src("scripts/mkv_bbc_cue_seek_patch.py")
        raw=src("scripts/native_rebuffer_patch.py")
        self.assertIn('av_seek_frame(fmt,stream,video_ts,AVSEEK_FLAG_BACKWARD)',p)
        self.assertIn('ret < 0 && !nova_mkv_seek',p)
        self.assertIn('NOVA_MKV_BBC_SEEK_STOP_V1',p)
        self.assertIn('NOVA_MKV_BBC_SEEK_GUARD_V1',raw)
        self.assertIn('NOVA_MKV_RANGE_SEEK_FAIL_V1',raw)
        self.assertIn('pthread_cond_timedwait',raw)
        self.assertIn('mkv_seek_bytes > (64ULL * 1024 * 1024)',raw)
        self.assertIn('av_gettime_relative() - raw->mkv_seek_started_us > 12000000',raw)

if __name__=="__main__":
    unittest.main()
