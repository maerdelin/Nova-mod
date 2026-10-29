from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class LiteRange4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.transport=(ROOT/"iso/nova_transport.c").read_text()
        cls.lite=(ROOT/"iso/nova_literange4.inc").read_text()
        cls.build=(ROOT/"scripts/build_transport_native.sh").read_text()

    def test_single_thread_owner(self):
        self.assertIn("#define NOVA_MULTI_MAX_LANES 4",self.transport)
        self.assertIn('#include "nova_literange4.inc"',self.transport)
        self.assertNotIn("pthread_create(",self.lite)
        self.assertNotIn("CallIntMethod(",self.lite)
        self.assertNotIn("GetByteArrayRegion(",self.lite)
        self.assertIn("curl_multi_perform(",self.lite)
        self.assertIn("curl_multi_poll(",self.lite)
        self.assertIn("CURLMOPT_MAX_TOTAL_CONNECTIONS,4L",self.lite)
        self.assertNotIn("NOVA_MULTI_ESCALATE from=",self.lite)
        self.assertNotIn("while(e->running<s->multi_active_lanes)",self.lite)

    def test_exact_bounded_range_and_tls(self):
        for token in ('NOVA_LITE_RANGE_BYTES (32 * 1024 * 1024)',
                      'NOVA_LITE_SLOTS 2','CURLOPT_RANGE',
                      'CURLOPT_SSL_VERIFYPEER,1L','CURLOPT_SSL_VERIFYHOST,2L',
                      'CURLINFO_RESPONSE_CODE','p->range_ok',
                      'total==s->upstream_size'):
            self.assertIn(token,self.lite)

    def test_four_second_long_ranges_and_streaming_delivery(self):
        for token in ('NOVA_LITE_SEGMENT_SECONDS 4',
                      'nova_lite_piece_length(s,p->start)',
                      'NOVA_LITERANGE4_PIECE',
                      'current->state==NOVA_MULTI_SLOT_ACTIVE',
                      'CURL_WRITEFUNC_PAUSE',
                      'curl_easy_pause(current->easy,CURLPAUSE_CONT)',
                      'wireBps=', 'NOVA_LITERANGE4_PAIR_HOLD',
                      'NOVA_LITERANGE4_REBASE',
                      'NOVA_LITERANGE4_PAIR_ENABLE',
                      'NOVA_LITERANGE4_RATE_READY',
                      'used>=s->multi_active_lanes'):

            self.assertIn(token,self.lite)

    def test_data_warehouse_budget_and_shutdown(self):
        raw=(ROOT/"scripts/native_rebuffer_patch.py").read_text()
        self.assertIn("NOVA_RAW_FALLBACK_CAP_BYTES   (128 * 1024 * 1024)",raw)
        self.assertIn("NOVA_LITE_RANGE_BYTES (32 * 1024 * 1024)",self.lite)
        self.assertIn("NOVA_LITE_SLOTS 2",self.lite)
        self.assertIn("got == AVERROR_EXIT",raw)
        self.assertIn("s->lite->piece_origin=start",self.lite)

    def test_seek_stops_old_event_loop(self):
        self.assertIn('nova_multi_stop(s, "seek", 0)',self.transport)
        self.assertIn('s->multi_generation++',self.lite)
        self.assertIn('curl_multi_remove_handle(',self.lite)
        self.assertIn('NOVA_MULTI_SEEK_GUARD_BEGIN',self.transport)

    def test_http403_recovery_is_bounded_and_seek_safe(self):
        for token in ("multi_http403_failures", "multi_http403_retry_ms",
                      "NOVA_MULTI_HTTP403_COOLDOWN",
                      "NOVA_MULTI_HTTP403_RETRY",
                      'http403 ? "http403-cooldown" : "range-backoff"',
                      'nova_iso_uptime_ms() >= s->multi_http403_retry_ms',
                      's->file_cursor < s->upstream_size',
                      'nova_multi_stop(s, "lane-error", 1)'):
            self.assertIn(token, self.transport)
        for token in ("e->successful_ranges>=1",
                      "NOVA_MULTI_HTTP403_RECOVERED",
                      "CURLINFO_REDIRECT_COUNT",
                      "!s->multi_http403_failures"):
            self.assertIn(token, self.lite)
        self.assertIn("n == 1 ? 4000 : n == 2 ? 15000 : 60000", self.transport)

    def test_static_dependencies_linked(self):
        for token in ('curl-8_16_0','openssl-3.5.4',
                      'libcurl.a','libssl.a','libcrypto.a'):
            self.assertIn(token,self.build)

if __name__=="__main__":
    unittest.main()
