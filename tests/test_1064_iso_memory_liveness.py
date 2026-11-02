"""NOVA 1064 ISO-specific liveness, memory policy and source regression gates."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
TRANSPORT=(ROOT/"iso/nova_transport.c").read_text()
LITE=(ROOT/"iso/nova_literange4.inc").read_text()
DIAG=(ROOT/"scripts/av_diag_patch.py").read_text()
CI=(ROOT/".github/workflows/nova-video-player-mod.yml").read_text()

class Iso1064(unittest.TestCase):
    def test_real_native_policy_and_stall_threshold(self):
        a=TRANSPORT.index("static int nova_iso_1064_replay_cap(")
        cap=TRANSPORT[a:TRANSPORT.index("\n}\n",a)+3]
        a=LITE.index("static int nova_iso_1064_stalled(")
        stall=LITE[a:LITE.index("\n}\n",a)+3]
        source=(
            "#include <stdint.h>\n#include <assert.h>\n"
            "#define NOVA_ISO_STARTUP_REPLAY_BYTES (24*1024*1024)\n"
            "#define NOVA_ISO_1064_REPLAY_32BIT_BYTES (8*1024*1024)\n"
            "#define NOVA_ISO_1064_LARGE_TITLE_BYTES (16ULL*1024*1024*1024)\n"
            "#define NOVA_ISO_1064_NO_PROGRESS_MS 8000\n"
            + cap + "\n" + stall + "\n"
            + "int main(void){\n"
            + " assert(nova_iso_1064_replay_cap(87096612864ULL,1,32)==8*1024*1024);\n"
            + " assert(nova_iso_1064_replay_cap(87096612864ULL,1,64)==24*1024*1024);\n"
            + " assert(nova_iso_1064_replay_cap(87096612864ULL,2,32)==24*1024*1024);\n"
            + " assert(nova_iso_1064_replay_cap(1024ULL,1,32)==24*1024*1024);\n"
            + " assert(!nova_iso_1064_stalled(7999,0));\n"
            + " assert(nova_iso_1064_stalled(8000,0));\n"
            + " assert(!nova_iso_1064_stalled(1,2));\n"
            + " return 0;\n}\n")
        with tempfile.TemporaryDirectory() as temp:
            src=Path(temp)/"test.c"
            exe=Path(temp)/"test"
            src.write_text(source)
            run=subprocess.run(["cc","-std=c11","-Wall","-Wextra","-Werror",
                                str(src),"-o",str(exe)],text=True,capture_output=True)
            self.assertEqual(run.returncode,0,run.stderr)
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            self.assertEqual(run.returncode,0,run.stderr)

    def test_iso_only_replay_reclamation(self):
        self.assertIn("NOVA_ISO_1064_REPLAY_POLICY",TRANSPORT)
        self.assertIn("NOVA_ISO_1064_REPLAY_RELEASE",LITE)
        self.assertIn("__atomic_load_n(&s->startup_first_frame_ready,__ATOMIC_ACQUIRE)",LITE)
        self.assertIn("target>=s->iso_startup_replay_start+s->iso_startup_replay_size",LITE)
        self.assertIn("NOVA_ISO_STARTUP_REPLAY_V1: hit",LITE)

    def test_exact_cursor_retry_and_fallback(self):
        self.assertIn("NOVA_ISO_1064_HEAD_STALL",LITE)
        self.assertIn("NOVA_ISO_1064_PERFORM_RETURN",LITE)
        self.assertIn("iso_stall_rebases<1",LITE)
        self.assertIn('nova_multi_stop(s,"iso-head-stall",0)',LITE)
        self.assertIn("nova_multi_start(s,rebase_at,2);",LITE)
        self.assertIn("NOVA_ISO_1064_EXACT_REBASE",LITE)
        self.assertIn("CURLOPT_FRESH_CONNECT,iso_fresh?1L:0L",LITE)
        self.assertIn('nova_multi_stop(s,"iso-range-fallback",1)',LITE)
        self.assertIn("nova_upstream_read_exact_retry(s,dst+done",LITE)

    def test_demux_enomem_snapshot_and_unmodified_other_files(self):
        self.assertIn('result==AVERROR(ENOMEM) &&',DIAG)
        self.assertIn('strstr(s->src_query,"nova_iso=1")',DIAG)
        self.assertIn("NOVA_1064_ISO_DEMUX_ENOMEM",DIAG)
        self.assertIn("getrlimit(RLIMIT_AS",DIAG)
        self.assertIn('s->mode==NOVA_MODE_FILE && s->multi_active',TRANSPORT)
        self.assertIn("NOVA_SHARED42_MKV_PAGE_VIEW_V1",LITE)

    def test_ci_pins_1063_compatible_official_source(self):
        self.assertIn("fix/1064-iso-memory-liveness-20261102",CI)
        self.assertIn("NOVA_1054_EXACT_1053_BASELINE:",CI)
        self.assertIn("test_1064_iso_memory_liveness.py",CI)
        self.assertIn("nova-1064-iso-",CI)

if __name__=="__main__":
    unittest.main()
