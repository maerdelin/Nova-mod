"""NOVA 1074 regression: destroy owner, bounded async FIFO, full patch smoke."""
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
PATCH=(ROOT/"scripts/subtitle_1074_async_exit_patch.py").read_text()
CI=(ROOT/".github/workflows/nova-video-player-mod.yml").read_text()
class Test1074(unittest.TestCase):
    def test_lifetime(self):
        self.assertIn("NOVA_1074_QCAP 32",PATCH)
        self.assertIn("pthread_once(&nova1074_once",PATCH)
        self.assertIn("pthread_detach(t)",PATCH)
        self.assertIn("pthread_cond_wait(&nova1074_cond",PATCH)
        self.assertIn("nova1074_retire_engine(eng,fn)",PATCH)
        self.assertIn("nova1074_retire_engine(eng,destroy)",PATCH)
        self.assertIn("if(nova1074_count < NOVA_1074_QCAP)",PATCH)
        self.assertIn("fallback=sync",PATCH)
        self.assertIn("job.fn(job.eng)",PATCH)
        self.assertIn("NOVA_1074_EGL_JOIN_END",PATCH)
        self.assertNotIn("pthread_cancel(",PATCH)
    def test_real_postpatch_sources(self):
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/"Source";src.mkdir()
            (src/"sub_engine_registry.c").write_text(
                "static REG_ENTRY *s_current = NULL;\n"
                "if (destroy) destroy(eng);\n"
                "if (fn) fn(eng);\n"
                "if (fn) fn(eng);\n")
            (src/"sub_render_gl.c").write_text(
                "#include <time.h>\n    pthread_join(r->thread, NULL);\n"
                "    // The engine is already destroyed\n")
            r=subprocess.run(["python3",str(ROOT/"scripts/subtitle_1074_async_exit_patch.py"),
                             "--native",str(Path(td))],text=True,capture_output=True)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            reg=(src/"sub_engine_registry.c").read_text()
            egl=(src/"sub_render_gl.c").read_text()
            self.assertEqual(reg.count("nova1074_retire_engine(eng,fn)"),2)
            self.assertEqual(reg.count("nova1074_retire_engine(eng,destroy)"),1)
            self.assertIn("NOVA_1074_EGL_DESTROY_BEGIN",reg)
            self.assertIn("NOVA_1074_EGL_JOIN_BEGIN",egl)
            self.assertIn("NOVA_1074_EGL_JOIN_END",egl)
            self.assertIn("uint64_t id=nova_global_log_enabled()?++nova1074_seq:0;",reg)
            self.assertIn("int64_t now=nova_global_log_enabled()?nova1074_mono_ms():0;",reg)
            self.assertEqual(reg.count("int64_t start=nova_global_log_enabled()?nova1074_mono_ms():0;"),2)
            self.assertIn("if(nova_diag_on())clock_gettime(CLOCK_MONOTONIC,&nova1074_t0);",egl)
            self.assertIn("&& nova_diag_on())clock_gettime(CLOCK_MONOTONIC,&nova1074_t1);",egl)
            self.assertIn("pthread_join(r->thread, NULL);",egl)
            self.assertIn("job.fn(job.eng)",reg)
    def test_build_delivery(self):
        self.assertIn("fix/1074-subtitle-egl-ui-exit-20261102",CI)
        self.assertIn("python3 scripts/subtitle_1074_async_exit_patch.py",CI)
        self.assertIn("test_1074_subtitle_async_exit.py",CI)
        self.assertIn("nova-1074-subtitle-egl-exit-",CI)
if __name__=="__main__":unittest.main()
