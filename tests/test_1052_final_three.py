"""#1049 final three regression gates; C source compiled locally on CI host."""
import unittest
import tempfile
import subprocess
from pathlib import Path
R=Path(__file__).resolve().parents[1]
N=(R/"scripts/native_rebuffer_patch.py").read_text()
C=(R/"iso/nova_transport.c").read_text()
U=(R/"scripts/startup_loading_994_patch.py").read_text()
P=(R/"scripts/iso_hw_cbe_reliability_patch.py").read_text()
W=(R/".github/workflows/nova-video-player-mod.yml").read_text()
class FinalThree(unittest.TestCase):
    def test_integer_only_monotone_and_locked_x(self):
        self.assertIn("nova_startup_fixed_denominator(s,resume)",C)
        self.assertIn("nova_startup_fixed_denominator(s,resume_bytes)",C)
        self.assertIn("__atomic_compare_exchange_n(&s->startup_buffer_percent",C)
        self.assertNotIn('const-string v3, "<1%"',U)
        self.assertNotIn("->nativeStartupResidentBytes()J",U)
        self.assertIn('android:text="0%"',U)
        self.assertNotIn("s->startup_buffer_percent,percent,__ATOMIC_RELEASE",C)
    def test_unique_prefix_host_compiler(self):
        a=N.index("static int64_t nova_raw_unique_prefix_next(")
        b=N.index("\n}\n",a)+2
        code="#include <stdint.h>\n#include <limits.h>\n"+N[a:b]+r"""
#include <assert.h>
int main(void) {
 const int64_t k=65536;
 assert(nova_raw_unique_prefix_next(0,0,k,k)==k);
 assert(nova_raw_unique_prefix_next(k,0,k,k)==k);
 assert(nova_raw_unique_prefix_next(k,0,2*k,2*k)==2*k);
 assert(nova_raw_unique_prefix_next(2*k,10000000,k,k)==2*k);
 assert(nova_raw_unique_prefix_next(2*k,0,4*k,4*k)==4*k);
 assert(nova_raw_unique_prefix_next(4*k,INT64_MAX-2,9,9)==4*k);
 assert(nova_raw_unique_prefix_next(4*k,0,0,0)==4*k);
 return 0;
}
"""
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/"prefix.c"
            out=Path(td)/"prefix"
            src.write_text(code)
            subprocess.run(["cc","-std=c11","-Wall","-Wextra","-Werror",str(src),"-o",str(out)],check=True)
            subprocess.run([str(out)],check=True)
    def test_format_handoff_and_separate_runtime_gate(self):
        self.assertIn("int64_t resident_early=raw->startup_contiguous_bytes",N)
        self.assertIn("unique_prefix=ff_p->raw.startup_contiguous_bytes",N)
        self.assertIn("raw->startup_contiguous_bytes=nova_raw_unique_prefix_next",N)
        self.assertIn("metric=unique_contiguous_prefix",C)
        self.assertIn("AVOS reports live RAW+packet buffering",C)
    def test_iso_early_verified_pump_and_tail_range(self):
        self.assertIn("NOVA_1052_ISO_EARLY_MOVIE_PUMP_V1",C)
        self.assertIn("if((m2ts||ts188) && rewind==0",C)
        self.assertIn("nova_iso_stop_pump(s);",C)
        self.assertIn("NOVA_1052_ISO_META_FETCH_V1",C)
        self.assertIn("if(tail_anchor && page_bytes>64*1024)",C)
        self.assertIn("if (!tail_anchor && !s->iso_meta_degraded",C)
    def test_cbe_hardware_only_retry_and_errno(self):
        self.assertIn("NOVA_1052_ISO_HW_ONLY_V1",P)
        self.assertIn("prio<STREAM_CPU_DSP3",P)
        self.assertIn("NOVA_1052_ISO_HW_CBE_V1",P)
        self.assertIn("get_default_stream_max_iframe_size()",P)
        self.assertIn("4*1024*1024,3*1024*1024",P)
        self.assertIn("errno",P)
        self.assertIn("iso_hw_cbe_reliability_patch.py --native",W)
if __name__=="__main__":
    unittest.main()
