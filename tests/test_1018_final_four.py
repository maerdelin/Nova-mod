"""NOVA #1018 four changes must remain one atomic build; no temporary APK."""
from pathlib import Path
import unittest
R=Path(__file__).resolve().parents[1]
T=(R/"iso/nova_transport.c").read_text()
N=(R/"scripts/native_rebuffer_patch.py").read_text()
U=(R/"scripts/startup_loading_994_patch.py").read_text()
M=(R/"scripts/startup_staged_decode_patch.py").read_text()
S=(R/"scripts/smoke_994_ui_runtime.py").read_text()
G=(R/"scripts/verify_994_delivery_gate.py").read_text()

class FinalFourSourceGuards(unittest.TestCase):
    def test_iso_exact_stepped_growth_and_nonpower_alignment(self):
        self.assertIn("#define NOVA_ISO_META_PAGE_BYTES (8 * 1024 * 1024)",T)
        self.assertIn("s->iso_meta_window_bytes*=2;",T)
        self.assertIn("s->iso_meta_window_bytes+=1024*1024;",T)
        self.assertIn("(pos / (int64_t)page_bytes) * (int64_t)page_bytes",T)
        self.assertIn("s->iso_meta_window_bytes>NOVA_ISO_META_PAGE_BYTES",T)
    def test_actual_resident_200ms_not_cumulative_downloaded(self):
        self.assertIn("last_percent_report_ms>=100",N)
        self.assertIn("pst->buffer_used +",N)
        self.assertIn("(int64_t)pst->buffer2_used",N)
        self.assertIn("(int64_t)s->rebuffer_resume_bytes",N)
        self.assertIn("const-wide/16 v1, 0xc8",U)
        self.assertIn("abs((z-a)-200)>180",S)
        self.assertIn('ui.get("refresh_interval_ms") == 200',G)
        self.assertNotIn("nativeStartupBytes()J",U)
    def test_mkv_container_not_suffix_only(self):
        self.assertIn("nova_is_actual_mkv_header",T)
        self.assertIn('head[0]!=0x1a || head[1]!=0x45',T)
        self.assertIn('!memcmp(head+i+3,"matroska",8)',T)
        self.assertIn("NOVA_MKV_REAL_CONTAINER_V1",T)
        self.assertIn("NOVA_STAGED_MKV_BY_CONTENT_V1",M)
        self.assertIn("NOVA_STAGED_MKV_WRONG_SUFFIX_V1",M)
    def test_mkv_30mb_scan_preserved_and_redundant_range_removed(self):
        self.assertIn("NOVA_MKV_HEAD_REWIND_V1: seek_hit",T)
        self.assertIn("NOVA_MKV_HEAD_REWIND_V1: replay",T)
        self.assertIn("nova_mkv_head_rewind_store(s,at,dst,got)",T)
        self.assertIn("NOVA_MKV_HEADER_SCAN_V1",M)
        self.assertIn("NOVA_MKV_TAIL_WARM_V1",T)
        self.assertIn("startup_mkv_canonical",T)
        self.assertIn("nova_mkv_single_get_read(s, dst, size)",T)

if __name__=="__main__":unittest.main()
