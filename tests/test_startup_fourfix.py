"""Regression contracts for NOVA #961's four startup-spinner fixes.

Every assertion points to executable logic. APK assembly and Android 11/14
smoke checks run separately in GitHub Actions.
"""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class FourStartupFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.transport=(ROOT/"iso/nova_transport.c").read_text()
        cls.curl=(ROOT/"iso/nova_literange4.inc").read_text()
        cls.patch=(ROOT/"scripts/startup_onepass_speed_patch.py").read_text()
        cls.smali=(ROOT/"scripts/direct_transport_apply.py").read_text()

    def test_redirect_cached_url_auth_order_and_disable(self):
        curl=self.curl
        begin=curl.index("static int nova_lite_launch(")
        end=curl.index("static uint64_t nova_lite_piece_quantum",begin)
        launcher=curl[begin:end]
        self.assertLess(
            launcher.index("p->used_probe_redirect ="),
            launcher.index("if(s->origin_auth && *s->origin_auth"))
        self.assertIn("!p->used_probe_redirect", launcher)
        self.assertIn("!e->probe_redirect_disabled",launcher)
        self.assertIn('p->origin_retry_once=1;',curl)
        self.assertIn('e->probe_redirect_disabled=1;',curl)
        self.assertIn('NOVA_STARTUP_REDIRECT_INCOMPATIBLE',curl)
        self.assertIn('!e->probe_redirect_disabled && s->mode==NOVA_MODE_FILE',curl)
        self.assertIn('CURLOPT_UNRESTRICTED_AUTH,0L',curl)
        self.assertIn('CURLOPT_SSL_VERIFYHOST,2L',curl)
        self.assertIn('CURLOPT_SSL_VERIFYPEER,1L',curl)

    def test_one_bounded_timeout_recovery_is_dalvik_safe(self):
        body=self.smali.split("REDIRECT_RESOLVER = r'''",1)[1].split("'''",1)[0]
        body=body.split('.method public static resolve(',1)[1].split('.end method',1)[0]
        self.assertIn(".locals 11",body)
        self.assertIn("const/16 v5, 0xbb8",body)
        self.assertIn("const/16 v5, 0x2710",body)
        self.assertIn("const/4 v10, 0x0",body)
        self.assertIn("const/4 v10, 0x1",body)
        self.assertIn("if-nez v10, :fail",body)
        self.assertIn("goto :loop",body)
        self.assertIn("Ljava/net/SocketTimeoutException;",body)
        self.assertIn(":try_start_resolver_http",body)
        self.assertIn(":try_end_resolver_http",body)
        self.assertIn(":catch_resolver_stalled",body)
        self.assertNotIn("/*",body) # Smali supports # comments, not C-style
        # Preserve original fast-path and credential boundary.
        self.assertIn("sameOrigin(Ljava/net/URL;Ljava/net/URL;)Z",body)
        self.assertIn(":drop_auth",body)
        self.assertIn('const-string v6, "bytes=0-0"',body)
        # Existing UI diagnostic instrumentation owns v9 (it is not our retry state).
        self.assertNotIn("const/4 v9, 0x1",body)

    def test_iso_seek_priority_does_not_cancel_iso_native_download(self):
        self.assertIn("raw->startup_reloc_pending++",self.patch)
        self.assertIn("raw->direct_transport,",self.patch)
        self.assertNotIn("raw->direct_transport && raw->source && raw->source->direct,",self.patch)
        self.assertIn("pthread_cond_wait(&raw->can_write,&raw->mutex)",self.patch)
        start=self.transport.index("int nova_transport_startup_probe_hint(")
        end=self.transport.index("int nova_transport_set_target_bps(",start)
        body=self.transport[start:end]
        self.assertIn("s->mode==NOVA_MODE_FILE",body) # ISO priority, NO ISO I/O cancel
        self.assertIn("startup_probe_complete",body)
        self.assertIn("startup_read_preempt",body)
        self.assertIn("startup_probe_active,0,__ATOMIC_RELEASE",self.patch)

    def test_probe_first_verified_range_gets_bandwidth_priority(self):
        self.assertIn("startup_first206_complete",self.curl)
        self.assertIn("NOVA_STARTUP_FIRST206_READY",self.curl)
        self.assertIn("(s->mode!=NOVA_MODE_FILE || e->startup_first206_complete)",self.curl)
        self.assertIn("s->startup_probe_complete",self.curl)
        self.assertIn("if(valid206 && s->mode==NOVA_MODE_FILE",self.curl)
        self.assertIn("#define NOVA_LITE_SEGMENT_SECONDS 4",self.curl)
        self.assertIn("x*NOVA_LITE_SEGMENT_SECONDS",self.curl)
        self.assertIn('NOVA_LITERANGE4_PAIR_ENABLE',self.curl)
        self.assertIn('NOVA_LITERANGE4_STOP reason=',self.curl)

    def test_existing_cursor_and_iso_seek_guards_preserved(self):
        self.assertIn("NOVA_STARTUP_ZERO_NO_REQUEST_V1",self.smali)
        self.assertIn("NOVA_RESUME_ZERO_NO_REQUEST_V1",self.smali)
        self.assertIn("int native_current=s->multi_active && s->multi_run",self.transport)
        self.assertIn("cursor_agrees=s->file_cursor==target",self.transport)
        self.assertIn("if (native_current && !s->multi_seek_guard &&",self.transport)
        self.assertIn('ret = bd_seek(s->bd, (uint64_t)target);',self.transport)
        self.assertIn("nova_multi_recoverable_range_error",self.transport)

    def test_deep_startup_java_bounded_connection_retry(self):
        range_body=self.smali.split("DIRECT_RANGE_HTTP = r'''",1)[1].split("'''",1)[0]
        range_body=range_body.split(".method public static open(",1)[1].split(".end method",1)[0]
        resolver=self.smali.split("REDIRECT_RESOLVER = r'''",1)[1].split("'''",1)[0]
        resolver=resolver.split(".method public static resolve(",1)[1].split(".end method",1)[0]
        for body in (range_body,resolver):
            self.assertIn("const/16 v5, 0xbb8",body)
            self.assertIn("const/16 v5, 0x2710",body)
            self.assertIn("setConnectTimeout(I)V",body)
            self.assertIn("setReadTimeout(I)V",body)
            self.assertIn("Ljava/net/SocketTimeoutException;",body)
            self.assertIn("goto :",body)
            self.assertNotIn("/*",body)
        self.assertIn(":retry_stalled",range_body)
        self.assertIn("if-nez v10, :fail",range_body)
        self.assertIn("const/4 v10, 0x0",range_body)
        self.assertIn("const/4 v10, 0x1",range_body)
        self.assertIn(":catch_resolver_stalled",resolver)
        self.assertIn("if-nez v10, :fail",resolver)

    def test_deep_startup_early_second_range_is_guarded(self):
        self.assertIn("NOVA_STARTUP_DEEP_V1",self.curl)
        self.assertIn("e->slots[0].delivered>=512*1024",self.curl)
        self.assertIn("e->slots[0].state==NOVA_MULTI_SLOT_ACTIVE",self.curl)
        self.assertIn("!s->multi_seek_guard",self.curl)
        self.assertIn("e->successful_ranges>=required_valid",self.curl)
        self.assertIn("NOVA_LITERANGE4_PAIR_ENABLE",self.curl)

if __name__=="__main__":
    unittest.main()
