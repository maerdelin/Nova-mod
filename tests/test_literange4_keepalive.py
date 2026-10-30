from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class KeepAliveRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inc=(ROOT/"iso/nova_literange4.inc").read_text()
        cls.source=(ROOT/"iso/nova_transport.c").read_text()
        cls.workflow=(ROOT/".github/workflows/nova-video-player-mod.yml").read_text()

    def test_shared_pool_two_lanes_kept_alive(self):
        for key in ("CURLMOPT_MAXCONNECTS,4L",
                    "CURLOPT_HTTP_VERSION,CURL_HTTP_VERSION_1_1",
                    "CURLOPT_TCP_KEEPALIVE,1L", "CURLOPT_FRESH_CONNECT,0L",
                    "CURLOPT_FORBID_REUSE,0L","curl_easy_reset(p->easy)"):
            self.assertIn(key,self.inc)
        self.assertNotIn("Connection: close",self.inc)

    def test_fixed_four_seconds_and_exact_ranges(self):
        self.assertIn("#define NOVA_LITE_SEGMENT_SECONDS 4",self.inc)
        self.assertIn("x*NOVA_LITE_SEGMENT_SECONDS",self.inc)
        self.assertIn("total==s->upstream_size",self.inc)
        self.assertIn("p->range_ok && p->encoding_ok",self.inc)

    def test_actual_connections_not_assumed(self):
        for key in ("CURLINFO_NUM_CONNECTS","CURLINFO_CONN_ID",
                    "CURLINFO_CONNECT_TIME_T","CURLINFO_APPCONNECT_TIME_T",
                    "CURLINFO_STARTTRANSFER_TIME_T","CURLINFO_TOTAL_TIME_T",
                    "NOVA_LITERANGE4_CONN slot=","NOVA_LITERANGE4_CONN_SUMMARY",
                    "newPer100=","reused="):
            self.assertIn(key,self.inc)
        # Startup-only verified redirect reuse holds the effective URL in memory,
        # never in logs. Preserve the ban on printing sensitive endpoints.
        self.assertIn("curl_easy_getinfo(p->easy,CURLINFO_EFFECTIVE_URL,&effective)",self.inc)
        self.assertIn("NOVA_STARTUP_REDIRECT_CACHE verified=1",self.inc)
        self.assertNotIn("LOGI(\"%s\",effective)",self.inc)
        self.assertNotIn("CURLINFO_PRIMARY_IP",self.inc)

    def test_transient_retry_and_terminal_range_fail(self):
        for key in ("nova_multi_recoverable_range_error",
                    "http==403","http==429","http==503",
                    "CURLE_OPERATION_TIMEDOUT","CURLE_RECV_ERROR",
                    "NOVA_MULTI_RANGE_BACKOFF","NOVA_MULTI_RANGE_TERMINAL",
                    "multi_http403_retry_ms","nova_multi_stop(s, \"lane-error\", 1)"):
            self.assertIn(key,self.source)
        self.assertIn("last_retry_after_sec*1000",self.source)
        self.assertIn("120000",self.source)

    def test_noop_only_for_unguarded_seek(self):
        self.assertIn("NOVA_LITERANGE4_SEEK_NOOP",self.source)
        self.assertIn("s->multi_committed_cursor == target",self.source)
        self.assertIn("!s->multi_seek_guard",self.source)
        self.assertIn('nova_multi_stop(s, "seek", 0)',self.source)
        self.assertIn("NOVA_MULTI_SEEK_GUARD_END",self.source)

    def test_signed_apk_keepalive_comparison_is_required(self):
        self.assertIn("smoke_literange4_keepalive.py --reports reports",self.workflow)
        self.assertIn("NOVA_LITERANGE4_CONN",self.workflow)

if __name__=="__main__":
    unittest.main()
