"""Fail-closed tests for the ISO-only CLPI-backed seek patch and 1.5X/3X thresholds."""
from __future__ import annotations
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class ISOIndexSeekV2Tests(unittest.TestCase):
    def test_source_patch_and_reapplication_guard(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            native=root/"native"
            (native/"Source").mkdir(parents=True)
            parser=native/"Source"/"stream_parser_ffmpeg.c"
            bridge=root/"transport.c"
            parser.write_text("""
NOVA_PGS_HISTORY_BYPASS_AB_V1
typedef struct NOVA_RAW_PREFETCH {
    nova_transport_abort_fn direct_abort;
} NOVA_RAW_PREFETCH;
        raw->transport_handle, "nova_transport_abort");
	int ret = avformat_seek_file( fmt, -1, seek_min, new_pos, seek_max, av_flags);
""")
            bridge.write_text("""__attribute__((visibility("default")))
int64_t nova_transport_size(uint64_t generation)
""")
            cmd=[sys.executable,str(ROOT/"scripts/iso_index_seek_patch.py"),
                 "--native",str(native),"--transport",str(bridge)]
            result=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+"\n"+result.stderr)
            patched=parser.read_text()
            t=bridge.read_text()
            self.assertIn("NOVA_ISO_INDEX_SEEK_V2",patched)
            self.assertIn("NOVA_ISO_INDEX_MAP_V2",t)
            self.assertIn("bd_seek_time(s->bd",t)
            self.assertIn("AVSEEK_FLAG_BYTE|AVSEEK_FLAG_BACKWARD",patched)
            self.assertIn("int64_t next=(int64_t)bd_tell(s->bd)",t)
            self.assertIn("restored=next;",t)
            self.assertNotIn("before-restored<=65536",t)
            self.assertIn("if(restored==before",t)
            self.assertIn("ret=avformat_seek_file(fmt,-1,seek_min,new_pos,seek_max,av_flags)",patched)
            self.assertIn("ff_p->nova_iso_time_mode && time>0",patched)
            self.assertIn("s->clip_count==1",t)
            # Refuse to silently apply the same patch twice.
            self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)

    def test_threshold_formula_and_scope(self):
        source=(ROOT/"scripts/native_rebuffer_patch.py").read_text()
        self.assertIn("requested_low = nova_x + nova_x / 2;",source)
        self.assertIn("requested_resume = 3 * nova_x;",source)
        self.assertIn("const int capacity = NOVA_RAW_FALLBACK_CAP_BYTES;",source)
        self.assertIn("int low = NOVA_RAW_FALLBACK_LOW_BYTES;",source)
        self.assertIn("int resume = NOVA_RAW_FALLBACK_RESUME_BYTES;",source)
        for x in [1,2,3,855933,12401537,2**20,2**27,2**31//5]:
            low=x+x//2
            resume=3*x
            self.assertEqual(low,3*x//2)
            self.assertLess(low,resume)
            self.assertLessEqual(resume,2**31-1)

if __name__=="__main__":
    unittest.main()
