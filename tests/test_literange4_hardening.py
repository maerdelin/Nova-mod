from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]

class LiteRange4HardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inc=(ROOT/"iso/nova_literange4.inc").read_text()
        cls.c=(ROOT/"iso/nova_transport.c").read_text()
        cls.workflow=(ROOT/".github/workflows/nova-video-player-mod.yml").read_text()

    def test_fixed_four_second_two_slot_http1_pool_invariants(self):
        for token in ("#define NOVA_LITE_SEGMENT_SECONDS 4",
                      "x*NOVA_LITE_SEGMENT_SECONDS",
                      "#define NOVA_LITE_SLOTS 2",
                      "CURLMOPT_MAXCONNECTS,4L",
                      "CURLOPT_HTTP_VERSION,CURL_HTTP_VERSION_1_1",
                      "CURLOPT_TCP_KEEPALIVE,1L",
                      "CURLOPT_FORBID_REUSE,0L",
                      "CURLOPT_SSL_VERIFYPEER,1L",
                      "CURLOPT_SSL_VERIFYHOST,2L",
                      "total==s->upstream_size"):
            self.assertIn(token,self.inc)

    def test_redirect_and_real_connection_reuse_are_distinct(self):
        self.assertIn("CURLINFO_NUM_CONNECTS,&new_connections",self.inc)
        self.assertIn("CURLINFO_REDIRECT_COUNT,&redirects",self.inc)
        self.assertIn("int reused=valid206 && new_connections==0;",self.inc)
        self.assertIn("p->filled==p->length",self.inc)
        self.assertNotRegex(self.inc,r"reused\s*=.*redirects\s*==\s*0")
        self.assertIn("NOVA_LITERANGE4_CONN_SUMMARY",self.inc)

    def test_failure_history_never_clears_just_after_eight_segments(self):
        self.assertIn("#define NOVA_MULTI_BACKOFF_RESET_MS 120000",self.c)
        self.assertIn("multi_backoff_last_failure_ms",self.c)
        self.assertIn("now-s->multi_backoff_last_failure_ms>=NOVA_MULTI_BACKOFF_RESET_MS",self.inc)
        self.assertIn("NOVA_MULTI_RANGE_HISTORY_CLEAR",self.inc)
        self.assertIn("multi_backoff_recovered_logged=1;",self.inc)
        self.assertIn("!s->multi_backoff_recovered_logged",self.inc)
        self.assertIn("NOVA_MULTI_HTTP403_RECOVERED validRanges=%u",self.inc)
        success=self.inc[self.inc.index("if(s->multi_http403_failures){"):
                         self.inc.index("/* A piece may already be fully consumed")]
        self.assertNotIn("if(s->multi_active_lanes==2 && e->successful_ranges>=8){",success)
        self.assertEqual(success.count("s->multi_http403_failures=0;"),1)
        self.assertIn("now-s->multi_backoff_last_failure_ms>=NOVA_MULTI_BACKOFF_RESET_MS",success)

    def test_single_verified_data_before_native_retry(self):
        self.assertIn("#define NOVA_MULTI_SINGLE_PROBE_BYTES (64 * 1024)",self.c)
        self.assertIn("nova_multi_record_verified_single(s,ret);",self.c)
        self.assertIn("s->multi_range_single_bytes>=NOVA_MULTI_SINGLE_PROBE_BYTES",self.c)
        self.assertIn("nova_iso_uptime_ms() >= s->multi_http403_retry_ms",self.c)
        self.assertIn("s->multi_range_single_bytes=0;",self.c)
        self.assertIn("NOVA_MULTI_SINGLE_VERIFIED bytes=",self.c)

    def test_second_denial_needs_two_valid_206s_before_w2(self):
        self.assertIn("required_valid=s->multi_http403_failures>1?2:1",self.inc)
        self.assertIn("e->successful_ranges>=required_valid",self.inc)
        self.assertIn("if(s->multi_http403_failures)lanes=1;",self.inc)
        self.assertIn("NOVA_MULTI_PAIR_REARM verified=",self.inc)
        self.assertIn("s->multi_backoff_last_failure_ms=now;",self.c)
        self.assertIn("n == 1 ? 4000 : n == 2 ? 15000 : 60000",self.c)
        self.assertIn("server_ms<=120000",self.c)

    def test_idempotent_seek_never_masks_a_logical_seek_or_old_epoch(self):
        for token in ("s->multi_active && s->multi_run",
                      "s->lite->generation==s->multi_generation",
                      "s->file_cursor==target",
                      "s->multi_committed_cursor == target",
                      "!s->multi_seek_guard",
                      "NOVA_LITERANGE4_SEEK_NOOP",
                      'nova_multi_stop(s,"lowlevel-byte-seek",0)',
                      "NOVA_MULTI_SEEK_RESUME_POLICY"):
            self.assertIn(token,self.c)
        self.assertIn('nova_multi_stop(s, "seek", 0)',self.c)
        self.assertIn("if(s->file_cursor!=target)",self.c)

    def test_signed_apk_repeated_403_test_is_mandatory(self):
        self.assertIn("smoke_literange4_http403_repeat.py --reports reports",self.workflow)
        self.assertIn("smoke_literange4_http429.py --reports reports",self.workflow)
        self.assertIn("smoke_literange4_keepalive.py --reports reports",self.workflow)

if __name__=="__main__":
    unittest.main()
