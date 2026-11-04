#!/usr/bin/env python3
"""NOVA 1199 targeted OFF source-collection safety regression tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))

import global_logs_1199_patch as native
import global_logs_smali_1199_patch as smali
import global_logs_sampling_1197_patch as sampling
from startup_loading_diag_patch import TRACE_SMALI
from shared42_pool_audit_v2_patch import AUDIT


class SourceGates1199(unittest.TestCase):
    def test_java_trace_all_eight_producers_gate_before_collection(self):
        result=smali.patch_trace(TRACE_SMALI)
        self.assertEqual(result.count("NovaGlobalLogs;->enabled()Z"),9)
        for signature in smali.GUARDED:
            begin=result.index(".method public static "+("synchronized " if signature=="nextHttp()I" else "")+signature)
            end=result.index(".end method",begin)
            method=result[begin:end]
            self.assertIn("if-eqz v0, :nova_1199_off",method)
            self.assertLess(method.index("NovaGlobalLogs;->enabled()Z"),
                            min((method.index(token) for token in
                                 ("StringBuilder;-><init>","SystemClock;->elapsedRealtime()J",
                                  "->sSession:I","->sHttpId:I")
                                 if token in method),default=len(method)))
        self.assertIn(".method public static end()V",result)
        end=result.split(".method public static end()V",1)[1].split(".end method",1)[0]
        self.assertLess(end.index("NovaGlobalLogs;->enabled()Z"),end.index("UI_SPINNER_HIDE"))
        self.assertIn("if-eqz v0, :nova_1200_end_reset",end)
        self.assertIn(":nova_1200_end_reset",end)
        self.assertIn("->sActive:Z",end)
        with self.assertRaises(RuntimeError):
            smali.patch_trace(result)

    def test_literange_off_has_no_diagnostic_byte_counters_and_keeps_w2(self):
        s=(ROOT/"iso/nova_literange4.inc").read_text()
        a=s.index("    /* NOVA_60FPS_W2_IO_CPU_V1:")
        b=s.index("    /* W=2 only, never the obsolete",a)
        s=s[:a]+"    if(nova_global_log_enabled()){\n"+s[a:b]+"    }\n"+s[b:]
        s=sampling.patch_literange(s)
        out=native.literange_source(s)
        self.assertIn("if(nova_global_log_enabled()) p->owner->received_sample_bytes+=",out)
        self.assertIn("if(nova_global_log_enabled()) e->committed_sample_bytes+=",out)
        self.assertIn("if(nova_global_log_enabled()){\n        e->committed_sample_bytes=0;",out)
        self.assertIn("int64_t call_start=nova_global_log_enabled()?nova_iso_uptime_ms():0;",out)
        self.assertIn("CURLMcode rc=curl_multi_perform(e->multi,&running);",out)
        self.assertIn("s->multi_active_lanes=2;",out)
        self.assertIn("nova_lite_schedule(s);",out)
        self.assertIn("e->last_sample_ms=now;",out)
        self.assertIn("s->multi_committed_cursor+=take;",out)

    def test_warehouse_off_bails_before_counter_and_lock(self):
        out=native.transport_source(AUDIT)
        head=out[out.index("static void nova_wh_diag_v2"):out.index("static void nova_wh_diag_v2")+250]
        self.assertLess(head.index("if(!nova_global_log_enabled())return;"),
                        head.index("__atomic_add_fetch"))

    def test_legacy_subtitle_printf_uses_only_gated_logger(self):
        for tag in ("IDX","MPL","SUB"):
            input=f'DBG printf( "{tag}: not {tag}\\n" );'
            output=native.subtitle_output_source(input,tag)
            self.assertEqual(output,f'DBG serprintf( "{tag}: not {tag}\\n" );')

    def test_ffmpeg_log_generation_and_raw_seek_probes(self):
        src=(
            "int64_t nova_boot_seek_lock_begin=av_gettime_relative();\n"
            "int64_t nova_boot_seek_lock_ms=(av_gettime_relative()-nova_boot_seek_lock_begin)/1000;\n"
            "int64_t nova_boot_seek_io_begin=av_gettime_relative();\n"
            "int64_t nova_boot_seek_io_ms=(av_gettime_relative()-nova_boot_seek_io_begin)/1000;\n"
            "int64_t total=0, level=64*1024LL, start=av_gettime_relative();\n"
            'printf("FFMPEG: cannot find stream info\\r\\n");\n'
            'printf("FFMPEG: cannot find stream info\\r\\n");\n'
            "void av_log_cb(void* ptr, int level, const char* fmt, va_list vl)\n{\n"
            "\tav_log_set_callback(av_log_cb);\n"
            "\tav_log_set_level( AV_LOG_DEBUG );\n \t}\n"
            "if(nova_diag_on()) nova_1073_external(40,(int64_t)(fmt->pb?avio_tell(fmt->pb):-1),0);\n"
            "if(nova_diag_on()) nova_1073_external(41,(int64_t)(fmt->pb?avio_tell(fmt->pb):-1),result);\n"
        )
        out=native.parser_source(src)
        self.assertIn("av_log_set_level(enabled?(log_debug?AV_LOG_DEBUG:AV_LOG_INFO):AV_LOG_QUIET)",out)
        self.assertIn("pthread_mutex_lock(&nova_ffmpeg_log_gate_mutex)",out)
        self.assertLess(out.index("av_log_set_level(enabled?"),out.index("__atomic_store_n(&nova_ffmpeg_log_was_enabled"))
        self.assertIn("if(!nova_diag_on())return;",out)
        self.assertIn("nova_ffmpeg_log_sync();",out)
        self.assertIn("int64_t nova_boot_seek_lock_begin=nova_diag_on()?",out)
        self.assertIn("start=nova_diag_on()?av_gettime_relative():0;",out)
        self.assertEqual(out.count('serprintf("FFMPEG: cannot find stream info'),2)

    def test_system_sampler_off_stops_cpu_frequency_io(self):
        source="long freqs[8];\n        for(int i=0;i<8;i++){"
        output=native.replace(source,"long freqs[8];\n        for(int i=0;i<8;i++){",
                              "long freqs[8]={-1,-1,-1,-1,-1,-1,-1,-1};\n"
                              "        for(int i=0;i<8 && nova_diag_on();i++){","cpu cancellation")
        self.assertIn("for(int i=0;i<8 && nova_diag_on();i++)",output)

    def test_strict_source_anchor_drift_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError,"expected"):
            native.subtitle_output_source("no subtitle debug print", "SUB")
        with self.assertRaisesRegex(RuntimeError,"expected"):
            native.transport_source("static void nova_wh_diag_v2(){}")


if __name__=="__main__":
    unittest.main()
