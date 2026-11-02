"""1073 ISO first-cause blackbox: source guards and real AVOS patch smoke."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
TRANSPORT=(ROOT/"iso/nova_transport.c").read_text()
LITE=(ROOT/"iso/nova_literange4.inc").read_text()
BB=(ROOT/"iso/nova_iso_blackbox.inc").read_text()
AVOS=(ROOT/"scripts/iso_1073_avos_patch.py").read_text()
CI=(ROOT/".github/workflows/nova-video-player-mod.yml").read_text()

class Iso1073(unittest.TestCase):
    def test_fixed_preallocated_history_and_no_hot_path_allocation(self):
        self.assertIn("#define NOVA_BB_RING_LEN 8192",BB)
        self.assertIn("#define NOVA_BB_HISTORY_MS 120000",BB)
        self.assertIn("static nova_bb_entry g_bb_ring[NOVA_BB_RING_LEN]",BB)
        self.assertIn("pthread_mutex_trylock(&g_bb_lock)",BB)
        hot=BB[BB.index("static void nova_bb_event("):
               BB.index("static void nova_bb_fault(")]
        for forbidden in ("malloc(", "calloc(", "pthread_mutex_lock(", "curl_", "bd_read("):
            self.assertNotIn(forbidden,hot)
        self.assertIn("g_bb_freeze_pending",BB)
        self.assertIn("NOVA_1073_BB_HISTORY",BB)

    def test_observer_survives_blocked_io_thread(self):
        self.assertIn("pthread_create(&watcher,NULL,nova_bb_watchdog,NULL)",BB)
        self.assertIn("pthread_detach(watcher)",BB)
        self.assertIn("NOVA_1073_BB_PHASE_STUCK",BB)
        self.assertIn('"/proc/self/task/%d/wchan"',BB)
        self.assertIn('"/proc/self/task/%d/stack"',BB)
        self.assertIn("NOVA_1073_BB_STACK_ACCESS",BB)
        self.assertIn("NOVA_1073_BB_NATIVE_STACK_GUIDE",BB)
        self.assertIn("NOVA_BB_CURL",LITE)
        self.assertIn("NOVA_BB_POLL",LITE)
        self.assertIn("NOVA_BB_BD",TRANSPORT)

    def test_close_lifecycle_and_alloc_failures(self):
        for marker in ("NOVA_BB_CLOSE_BEGIN","NOVA_BB_CLOSE_DONE",
                       "NOVA_BB_PUMP_JOIN","NOVA_BB_PUMP_JOINED",
                       "NOVA_BB_CALLS_WAIT","NOVA_BB_CALLS_DRAINED",
                       "NOVA_BB_ALLOC_FAILURE","NOVA_BB_REPLAY_ALLOC"):
            self.assertIn(marker,TRANSPORT)
        self.assertIn("NOVA_BB_CBE_FAIL",BB)
        self.assertIn("NOVA_BB_FFMPEG_ENOMEM",BB)
        self.assertIn('"VmSize:"',BB)
        self.assertIn('"VmRSS:"',BB)
        self.assertIn('"Threads:"',BB)
        self.assertIn('"MemAvailable:"',BB)
        self.assertIn('"/proc/self/maps"',BB)
        self.assertIn('"/proc/self/fd"',BB)

    def test_iso_first_frame_fix_is_reachable(self):
        self.assertIn("if(s->mode==NOVA_MODE_BLURAY_ISO){",TRANSPORT)
        self.assertIn("NOVA_1073_ISO_FIRST_FRAME_READY",TRANSPORT)
        self.assertIn("startup_first_frame_ready,1,__ATOMIC_ACQ_REL",TRANSPORT)
        self.assertIn("NOVA_ISO_1064_REPLAY_RELEASE",LITE)

    def test_real_patcher_operates_on_postpatch_avos(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"native"
            src=root/"Source"
            src.mkdir(parents=True)
            (src/"stream_parser_ffmpeg.c").write_text(
                '#include <signal.h>\n'
                '        int64_t nova_boot_io_begin=av_gettime_relative();\n'
                '        int got=raw->shared_pages ?\n'
                '            avio_read(raw->source, raw->ring + write_off, want);\n'
                '        int64_t nova_boot_io_ms=(av_gettime_relative()-nova_boot_io_begin)/1000;\n'
                '    int result = av_read_frame(fmt, &packet);\n'
                '            if(result==AVERROR(ENOMEM) &&\n'
                '               strstr(s->src_query,"nova_iso=1")){\n')
            (src/"stream_video.c").write_text(
                '#include <signal.h>\n'
                '\t\tint alloc_errno=errno;\n'
                '\t\t\t\talloc_errno=errno;\n'
                '\t\t\t\tserprintf("NOVA_1052_ISO_HW_CBE_V1: retry\n')
            run=subprocess.run(["python3",str(ROOT/"scripts/iso_1073_avos_patch.py"),
                "--native",str(root)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            ff=(src/"stream_parser_ffmpeg.c").read_text()
            video=(src/"stream_video.c").read_text()
            self.assertIn("nova_1073_external(10,want,0)",ff)
            self.assertIn("nova_1073_external(11,want,got)",ff)
            self.assertIn("nova_1073_external(40,",ff)
            self.assertIn("nova_1073_external(41,",ff)
            self.assertIn("nova_1073_external(30,",ff)
            self.assertIn("nova_1073_external(s->cbe ? 21 : 20,",video)
            self.assertIn("nova_1073_bridge_once",video)
            self.assertIn("RTLD_NOW",ff)

    def test_1072_isolation_and_build_gates(self):
        self.assertIn("diag/1073-iso-first-cause-blackbox-20261102",CI)
        self.assertIn("test_1073_iso_blackbox.py",CI)
        self.assertIn("python3 scripts/iso_1073_avos_patch.py",CI)
        self.assertIn("NOVA_1073_BB_WATCHDOG_STARTED",CI)
        self.assertIn("nova-1073-iso-blackbox-",CI)

if __name__=="__main__":
    unittest.main()
