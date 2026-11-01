"""Regression guards for #1052 ISO ENOMEM and EOF misclassification.

The root-level regression is observable in source and both real-device
logcat failures at gen15/16. These guards ensure the speculative libbluray
callback path cannot slip back into the signed APK. The internal FFmpeg
allocator that returned ENOMEM needs a real device log to identify; this test
does not claim to identify the allocation merely from the AVERROR code.
"""
import unittest
from pathlib import Path

R=Path(__file__).resolve().parents[1]
ISO=(R/"iso/nova_transport.c").read_text()
AVOS=(R/"scripts/native_rebuffer_patch.py").read_text()
SMOKE=(R/"scripts/smoke_iso_parallel_994.py").read_text()
CI=(R/".github/workflows/nova-video-player-mod.yml").read_text()
OLD_PATCH=(R/"scripts/iso_hw_cbe_reliability_patch.py").read_text()
UI=(R/"scripts/startup_loading_994_patch.py").read_text()

class Iso1053(unittest.TestCase):
    def test_first_movie_lba_callback_is_record_only(self):
        start=ISO.index("static int upstream_read_blocks(")
        end=ISO.index("static void nova_iso_capture_track_languages(",start)
        callback=ISO[start:end]
        self.assertIn("s->iso_first_movie_lba=target;",callback)
        self.assertNotIn("nova_iso_start_pump(s",callback)
        self.assertIn("NOVA_1053_ISO_PUMP_GUARD_V1",callback)

    def test_post_validation_start_is_identical_to_1049(self):
        start=ISO.index("static int select_main_title(")
        end=ISO.index("/* NOVA_FILE_ORIGIN_FRESH_V1:",start)
        body=ISO[start:end]
        ts_check=body.index("verify[i*192+4]!=0x47")
        rewind=body.index("int64_t rewind=bd_seek(s->bd,0);")
        signature=body.index("if((m2ts||ts188) && rewind==0 && s->iso_first_movie_lba>=0)")
        start_pump=body.index("nova_iso_start_pump(s,s->iso_first_movie_lba);")
        self.assertLess(ts_check,rewind)
        self.assertLess(rewind,signature)
        self.assertLess(signature,start_pump)
        self.assertIn("NOVA_1053_ISO_PUMP_GUARD_V1",body)
        self.assertNotIn("NOVA_1052_ISO_EARLY_MOVIE_PUMP_V1",body)

    def test_error_is_not_eof_or_silent_success(self):
        start=AVOS.index("static int _nova_rebuffer_eof( STREAM *s )")
        end=AVOS.index("\n}\n",start)
        code=AVOS[start:end]
        self.assertIn("if(s->parser_error)return 0;",code)
        self.assertIn("NOVA_1053_DEMUX_ERROR_NOT_EOF_V1",AVOS)
        self.assertIn("stream_set_error(s,VE_FILE_ERROR);",AVOS)
        self.assertIn("int parsed_eof = _nova_rebuffer_eof( s );",AVOS)

    def test_keep_1052_integer_ui_and_hardware(self):
        self.assertNotIn('const-string v3, "<1%"',UI)
        self.assertIn("nova_startup_unique_integer_percent",ISO)
        self.assertIn("NOVA_1052_ISO_HW_CBE_V1",OLD_PATCH)
        self.assertIn("NOVA_1052_ISO_HW_ONLY_V1",OLD_PATCH)

    def test_iso_apk_4s_observation_and_real_fixture(self):
        self.assertIn("time.sleep(4.0)",SMOKE)
        self.assertIn("pump ran before verified TS+rewind",SMOKE)
        self.assertIn('FFMPEG: read failure: Out of memory',SMOKE)
        self.assertIn("Prepare real Blu-ray ISO media",CI)
        self.assertIn("fix/1053-iso-validated-pump-20261101",CI)

if __name__=="__main__":
    unittest.main()
