#!/usr/bin/env python3
"""Regression: Logs OFF may silence telemetry but NEVER stop first-frame render state."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent

def load():
    spec=importlib.util.spec_from_file_location("global_logs_native_patch",
        ROOT/"scripts/global_logs_native_patch.py")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class FirstFrameNotDiagnostics(unittest.TestCase):
    def test_off_on_off_renderer_and_lifecycle(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            fixture={
                "Include/stream.h":"\tvolatile int\trebuffer_frame_seen;\n",
                "Source/codec_sfdec2.c":(
                    "                    if (s) {\n"
                    "                        if(nova_diag_on()) __atomic_fetch_add(&s->nova_diag_render_submitted, 1, __ATOMIC_RELAXED);\n"
                    "                    }\n"),
                "Source/stream_video.c":(
                    "int a=__atomic_load_n(&s->nova_diag_render_submitted,\n"
                    "    __ATOMIC_ACQUIRE)>0 && s->rebuffer_frame_seen;\n"
                    "int b=__atomic_load_n(&s->nova_diag_render_submitted,__ATOMIC_ACQUIRE)>0;\n"
                    "int log=__atomic_load_n(&s->nova_diag_render_submitted,__ATOMIC_RELAXED);\n"
                    "\t__atomic_store_n( &s->rebuffer_frame_seen, 0, __ATOMIC_RELEASE );\n"),
                "Source/avos_mp_video.c":(
                    "\t__atomic_store_n(&video->s->rebuffer_frame_seen, 0, __ATOMIC_RELEASE);\n"*2),
                "Source/stream.c":"        __atomic_store_n( &s->rebuffer_frame_seen, 0, __ATOMIC_RELEASE );\n",
            }
            for name,body in fixture.items():
                path=root/name
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(body)
            load().decouple_startup_render(root)
            codec=(root/"Source/codec_sfdec2.c").read_text()
            video=(root/"Source/stream_video.c").read_text()
            self.assertEqual(video.count("__atomic_load_n(&s->startup_render_submitted"),2)
            self.assertEqual(video.count("nova_diag_render_submitted"),1)
            self.assertIn("__atomic_store_n(&s->startup_render_submitted, 1, __ATOMIC_RELEASE);",codec)
            self.assertIn("if(nova_diag_on()) __atomic_fetch_add(&s->nova_diag_render_submitted",codec)
            self.assertEqual((root/"Source/avos_mp_video.c").read_text().count(
                "startup_render_submitted, 0"),2)

            # Compile the REAL updated render-event statements in a minimal
            # C playback state machine, including an ON->OFF->ON transition.
            c="""
typedef struct {volatile int startup_render_submitted;
                volatile int nova_diag_render_submitted;
                volatile int rebuffer_frame_seen;} STREAM;
static int logging;
static int nova_diag_on(void){return logging;}
static void rendered(STREAM *s){
"""+codec+"""
}
int main(void){
    STREAM s={0};s.rebuffer_frame_seen=1;
    rendered(&s);
    if(!s.startup_render_submitted||s.nova_diag_render_submitted) return 1;
    logging=1;s.startup_render_submitted=0;rendered(&s);
    if(!s.startup_render_submitted||s.nova_diag_render_submitted!=1) return 2;
    logging=0;s.startup_render_submitted=0;rendered(&s);
    if(!s.startup_render_submitted||s.nova_diag_render_submitted!=1) return 3;
    return 0;
}
"""
            src=root/"runtime.c"
            exe=root/"runtime"
            src.write_text(c)
            subprocess.run(["cc","-std=gnu11","-Wall","-Wextra","-Werror",
                            str(src),"-o",str(exe)],check=True,capture_output=True,text=True)
            subprocess.run([str(exe)],check=True)

    def test_real_native_gate_retains_off_silence(self):
        source=(ROOT/"scripts/global_logs_native_patch.py").read_text()
        native=(ROOT/"scripts/native_rebuffer_patch.py").read_text()
        self.assertIn("decouple_startup_render(root)",source)
        self.assertIn('int nova_first_render=',native)
        self.assertIn('nova_diag_render_submitted',native)
        self.assertIn("if(nova_diag_on())",source)

if __name__=="__main__":
    unittest.main(verbosity=2)
