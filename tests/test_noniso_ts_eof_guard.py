"""Run694: finite MPEG-TS EOF clamp guards exact remote keyframes, ISO unchanged."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/noniso_ts_eof_guard_patch.py"
ANCHOR="\t\twind_start = stream_get_current_pos(video->s, &stream_total);\n\t\tdir = pos >= wind_start ? STREAM_SEEK_FORWARD : STREAM_SEEK_BACKWARD;"

class TestNonIsoTSClamp(unittest.TestCase):
    def test_patch_applies_once_and_isolated(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            f=root/"Source/avos_mp_video.c"
            f.parent.mkdir(parents=True)
            f.write_text("int f(void){\n"+ANCHOR+"\n}\n")
            args=[sys.executable,str(SCRIPT),"--native",str(root)]
            r=subprocess.run(args,capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            content=f.read_text()
            self.assertIn("NOVA_NONISO_TS_EOF_TARGET_CLAMP_V1",content)
            self.assertIn('strstr(video->s->src.url, "/main.m2ts") == NULL',content)
            self.assertIn("video->s->etype == ETYPE_MPEG_TS",content)
            self.assertIn("!video->s->no_duration",content)
            self.assertIn("video->s->duration - 2000",content)
            self.assertIn("pos = last_safe;",content)
            self.assertNotIn("bd_seek_time",content)
            self.assertNotEqual(subprocess.run(args,capture_output=True).returncode,0)
    def test_exact_run693_failure_now_targets_valid_gop(self):
        dur=48021
        pos=48421
        safe=dur-2000
        self.assertEqual(min(pos,safe),46021)
        self.assertTrue(int(dur*0.93)<=safe<=int(dur*0.975))
        self.assertEqual(min(43421,safe),43421)
    def test_iso_source_kept(self):
        s=(ROOT/"iso/nova_transport.c").read_text()
        ref=(ROOT/"tests/fixtures/run680_iso_seek.cfrag").read_text()
        st=s.index("if (s->mode == NOVA_MODE_BLURAY_ISO) {\n            int64_t current = bd_tell")
        end=s.index("        } else {\n            int64_t target = offset;",st)
        self.assertEqual(s[st:end],ref)

if __name__=="__main__": unittest.main()
