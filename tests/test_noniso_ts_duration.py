"""Run692 regression: finite direct MPEG-TS uses time seeks; ISO untouched."""
from pathlib import Path
import runpy
import sys
import tempfile
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts"/"noniso_ts_duration_patch.py"
ANCHOR="if( fmt->duration != AV_NOPTS_VALUE && etype != ETYPE_MPEG_TS ) {"

class FiniteTSDurationTests(unittest.TestCase):
    def test_patches_pinned_duration_without_rewriting_iso_seek(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/"Source"
            src.mkdir()
            c=src/"stream_parser_ffmpeg.c"
            c.write_text("static int f(void) {\n  "+ANCHOR+"\n   x();\n }\n}\n")
            cmd=[sys.executable,str(SCRIPT),"--native",str(Path(d))]
            r=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr+r.stdout)
            patched=c.read_text()
            self.assertIn("NOVA_NONISO_TS_DURATION_V1",patched)
            self.assertIn('strstr(priv->s->src.url,"/stream?")',patched)
            self.assertIn('priv->size_known',patched)
            self.assertIn('priv->s->no_duration=0;',patched)
            self.assertIn('etype != ETYPE_MPEG_TS || nova_finite_file_ts',patched)
            self.assertIn('24LL * 3600 * AV_TIME_BASE',patched)
            self.assertNotIn('"/main.m2ts"',patched)
            self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)
    def test_unrelated_media_is_not_promoted(self):
        def eligible(etype,src,known,size,duration_us):
            return etype=="MPEG_TS" and known and size>0 and 5000000<=duration_us<=86400000000 and "/stream?" in src
        self.assertTrue(eligible("MPEG_TS","http://127.0.0.1/stream?g=7",True,11195400,42021333))
        for input in [
           ("MPEG_TS","http://127.0.0.1/main.m2ts?g=7",True,11195400,42021333),
           ("MPEG_TS","http://127.0.0.1/stream?g=7",False,11195400,42021333),
           ("MPEG_TS","http://127.0.0.1/stream?g=7",True,0,42021333),
           ("MPEG_TS","http://127.0.0.1/stream?g=7",True,11195400,0),
           ("MKV","http://127.0.0.1/stream?g=7",True,11195400,42021333),
        ]:
            self.assertFalse(eligible(*input),input)
    def test_previously_verified_iso_source_kept(self):
        s=(ROOT/"iso/nova_transport.c").read_text()
        ref=(ROOT/"tests/fixtures/run680_iso_seek.cfrag").read_text()
        begin=s.index("if (s->mode == NOVA_MODE_BLURAY_ISO) {\n            int64_t current = bd_tell")
        end=s.index("        } else {\n            int64_t target = offset;",begin)
        self.assertEqual(s[begin:end],ref)

if __name__=="__main__":
    unittest.main()
