"""Run688: preserve Run680 ISO index and verify the non-ISO one-GET design."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]

class SingleGetSeekTests(unittest.TestCase):
    def test_file_not_probed_before_data_range(self):
        s=(ROOT/"scripts/direct_transport_apply.py").read_text()
        helper=s.split("DIRECT_RANGE_HTTP = r'''",1)[1].split("\n'''",1)[0]
        self.assertIn("DirectRangeHttp;",helper)
        self.assertIn('const-string v9, "bytes="',helper)
        self.assertIn('const-string v5, "GET"',helper)
        self.assertIn('->getResponseCode()I',helper)
        self.assertIn('->getInputStream()Ljava/io/InputStream;',helper)
        self.assertNotIn("bytes=0-0",helper)
        self.assertIn("if-eqz v0, :nova_file_single_get",s)
        self.assertIn("move-object v2, v14",s)
        self.assertIn("goto :native_iso_ready",s)
        self.assertIn('DirectRangeHttp.smali").write_text(DIRECT_RANGE_HTTP)',s)
        self.assertIn("NOVA_SINGLE_GET_ANDROID_PASS",helper)

    def test_auth_is_never_forwarded_across_origin(self):
        s=(ROOT/"scripts/direct_transport_apply.py").read_text()
        helper=s.split("DIRECT_RANGE_HTTP = r'''",1)[1].split("\n'''",1)[0]
        cond=helper.index("sameOrigin(Ljava/net/URL;Ljava/net/URL;)")
        auth=helper.index('const-string v5, "Authorization"',cond)
        self.assertIn("if-eqz v5, :response",helper[cond:auth])
        self.assertIn("setInstanceFollowRedirects(Z)V",helper)
        self.assertIn('->getHeaderField(Ljava/lang/String;)',helper)
        self.assertIn("move-object v1, v8",helper)
        self.assertIn('.method public static sameOrigin',s)
        self.assertIn("NOVA_NONISO_SINGLE_GET_V1",s)

    def test_native_has_one_live_stream_cursor(self):
        s=(ROOT/"iso/nova_transport.c").read_text()
        self.assertIn("NOVA_NONISO_SINGLE_GET_V1",s)
        self.assertIn("static nova_session *session_create_file",s)
        self.assertIn("static int nova_file_java_open_at",s)
        self.assertIn("static int nova_file_java_read",s)
        self.assertIn("Content-Range",s)
        self.assertIn("first!=target",s)
        self.assertIn("file_size!=s->upstream_size",s)
        self.assertIn("s->file_cursor=at+got;",s)
        self.assertIn("return nova_file_java_open_at(s,target);",s)
        self.assertIn("file_http_mode",s)
        self.assertIn("GetByteArrayRegion",s)
        self.assertIn("NewGlobalRef",s)
        self.assertIn("DeleteGlobalRef",s)
        self.assertIn('session_create(url,headers ? headers : "",1)',s)
        self.assertIn("session_create_file(env,canonical ? canonical : url,",s)
        self.assertIn("NOVA_NONISO_BAD_RANGE_V1",s)

    def test_no_lossy_bitrate_to_byte_mapping(self):
        s=(ROOT/"iso/nova_transport.c").read_text()
        self.assertNotIn("targetMs * s->output_size",s)
        self.assertNotIn("targetMs * s->upstream_size",s)
        codec=(ROOT/"scripts/iso_index_seek_patch.py").read_text()
        self.assertIn("NOVA_ISO_INDEX_SEEK_V3",codec)

    def test_iso_source_byte_equivalent(self):
        s=(ROOT/"iso/nova_transport.c").read_text()
        ref=(ROOT/"tests/fixtures/run680_iso_seek.cfrag").read_text()
        st=s.index("if (s->mode == NOVA_MODE_BLURAY_ISO) {\n            int64_t current = bd_tell")
        end=s.index("        } else {\n            int64_t target = offset;",st)
        self.assertEqual(s[st:end],ref)

if __name__=="__main__":
    unittest.main()
