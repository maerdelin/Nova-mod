"""Canonical WebDAV origin refresher: preserve ISO, auth boundaries and exact bytes."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class CanonicalWebdavFreshnessTests(unittest.TestCase):
    def test_original_origin_retained_into_jni(self):
        src=(ROOT/"scripts/direct_transport_apply.py").read_text()
        self.assertIn("move-object v14, v2",src)
        self.assertIn("move-object v15, v3",src)
        self.assertIn(".locals 16",src)
        self.assertIn("ZLjava/lang/String;Ljava/lang/String;",src)
        self.assertIn("DirectRedirectResolver;->resolve",src)
        self.assertIn("sameOrigin(Ljava/net/URL;Ljava/net/URL;)",src)
        self.assertIn(":drop_auth",src)

    def test_authenticated_mkv_direct_range_can_call_origin_guard(self):
        # DirectRangeHttp is a distinct Dalvik class. An invoke-static to a
        # private helper in DirectRedirectResolver raises IllegalAccessError
        # when a WebDAV Authorization header is nonempty.
        source=(ROOT/"scripts/direct_transport_apply.py").read_text()
        http=source.split("DIRECT_RANGE_HTTP = r'''",1)[1].split("'''",1)[0]
        resolver=source.split("REDIRECT_RESOLVER = r'''",1)[1].split("'''",1)[0]
        sig="sameOrigin(Ljava/net/URL;Ljava/net/URL;)Z"
        self.assertIn("DirectRedirectResolver;->"+sig,http)
        self.assertIn(".method public static "+sig,resolver)
        self.assertNotIn(".method private static "+sig,resolver)
        self.assertIn("if-nez v5, :response",http)
        self.assertIn('const-string v5, "Authorization"',http)

    def test_fresh_connection_happens_before_stale_seek(self):
        src=(ROOT/"iso/nova_transport.c").read_text()
        idx=src.index("static int nova_file_seek_retry(nova_session *s, int64_t target)")
        body=src[idx:src.index("static int nova_upstream_read_some_retry",idx)]
        self.assertIn("s->requires_origin_refresh",body)
        self.assertIn("nova_file_open_fresh_at(s,target)",body)
        self.assertLess(body.index("nova_file_open_fresh_at(s,target)"),
                        body.index("avio_seek(s->upstream,target,SEEK_SET)"))
        self.assertIn('av_dict_set(&opts,"offset",at,0);',src)
        self.assertIn("NOVA_FILE_ORIGIN_REFRESH_V1",src)
        self.assertIn("NOVA_FILE_FRESH_RANGE_V1",src)
        self.assertIn("DeleteGlobalRef",src)
        self.assertIn("AttachCurrentThread",src)
        self.assertIn('if(s->mode!=NOVA_MODE_FILE || !s->requires_origin_refresh)',src)
        self.assertNotIn("NOVA_HTTP_RANGE_ROOT_DIAG_V1",src)

    def test_run680_iso_seek_is_byte_identical(self):
        src=(ROOT/"iso/nova_transport.c").read_text()
        ref=(ROOT/"tests/fixtures/run680_iso_seek.cfrag").read_text()
        st=src.index("if (s->mode == NOVA_MODE_BLURAY_ISO) {\n            int64_t current = bd_tell")
        en=src.index("        } else {\n            int64_t target = offset;",st)
        self.assertEqual(src[st:en],ref)

if __name__=="__main__":unittest.main()
