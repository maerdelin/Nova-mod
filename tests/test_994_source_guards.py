"""NOVA 994 five-goal source invariants before expensive final signed APK build."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
C = (ROOT / "iso/nova_transport.c").read_text()
LITE = (ROOT / "iso/nova_literange4.inc").read_text()
AVOS = (ROOT / "scripts/native_rebuffer_patch.py").read_text()
UI = (ROOT / "scripts/startup_loading_994_patch.py").read_text()
APPLY = (ROOT / "scripts/direct_transport_apply.py").read_text()

class FiveGoalGuards(unittest.TestCase):
    def test_01_iso_metadata_and_w2_own_separate_threads(self):
        start=C.index("static int select_main_title(")
        fn=C[start:C.index("/* NOVA_FILE_ORIGIN_FRESH_V1",start)]
        self.assertLess(fn.index("bd_select_title("),fn.index("nova_iso_start_pump("))
        self.assertLess(fn.index("nova_iso_start_pump("),fn.index("bd_get_title_info(s->bd, (uint32_t)main_title, 0);"))
        self.assertIn("pthread_create(&s->iso_pump_thread",C)
        self.assertIn("pthread_join(s->iso_pump_thread",C)
        self.assertIn("nova_iso_stop_pump(s);\n        /* ISO scan finished",C)
        self.assertIn("NOVA_STARTUP_BUFFER_PREARM_V1",AVOS)
        self.assertIn("NOVA_FIRST_RENDER_HOLD_V1",AVOS)
        self.assertIn("s->rebuffer_resume_bytes :",AVOS)
        self.assertIn("s->rebuffer_low_bytes)",AVOS)

    def test_02_mkv_real_byte_warmup_and_seek_integrity(self):
        self.assertIn("NOVA_MKV_TAIL_WARM_V1",C)
        self.assertIn("nova_file_java_open_at(&temp,temp.file_cursor)",C)
        self.assertIn("nova_file_java_close_active(&temp)",C)
        self.assertIn("count==s->mkv_tail_size",C)
        self.assertIn("mkv_tail_ready,__ATOMIC_ACQUIRE",C)
        self.assertIn("nova_mkv_seek_retry(s,target)",C)
        self.assertIn("nova_mkv_tail_join(s)",C)
        self.assertNotIn("AVIO_SEEKABLE_NORMAL = 0",C)

    def test_03_iso_lba_jump_reuses_verified_first_bytes(self):
        self.assertIn("NOVA_ISO_STARTUP_REPLAY_V1",C)
        self.assertIn("NOVA_ISO_STARTUP_REPLAY_V1",LITE)
        self.assertIn("memcpy(dst,s->iso_startup_replay",LITE)
        self.assertIn("if(done==bytes)return done",LITE)
        self.assertIn('nova_multi_stop(s,"iso-lba-jump",0)',LITE)
        self.assertIn("s->multi_committed_cursor!=live_target",LITE)

    def test_04_w2_pre_first_frame(self):
        self.assertIn("nova_multi_start(s,at,2)",C)
        self.assertIn("nova_iso_start_pump(s,s->iso_first_movie_lba)",C)
        self.assertIn("NOVA_ISO_PARALLEL_V1",C)
        self.assertIn("if(running==0)break;",C)
        self.assertIn("s->multi_active_lanes=lanes",LITE)

    def test_05_loading_overlay_until_threshold_and_k_m_speed(self):
        self.assertIn("onPrepared(Landroid/view/View;)Z",UI)
        self.assertIn("nativeStartupState()I",UI)
        self.assertIn("nativeStartupBytes()J",UI)
        self.assertIn('const-string v10, "M/S"',UI)
        self.assertIn('const-string v10, "K/S"',UI)
        self.assertIn('android:tag="nova_speed"',UI)
        self.assertIn('android:layout_width="52.0dp"',UI)
        self.assertIn("apply_994_startup_ui(root)",APPLY)
        self.assertIn("NOVA_STARTUP_UI_PHASE_V1",C)
        self.assertIn("nova_startup_overlay_milestone",AVOS)

if __name__ == "__main__":
    unittest.main()
