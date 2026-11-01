"""1035 regression: all container formats must wait for a real X, then lock once."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
N=(ROOT/"scripts/native_rebuffer_patch.py").read_text()
T=(ROOT/"iso/nova_transport.c").read_text()
U=(ROOT/"scripts/startup_loading_994_patch.py").read_text()
class XLock(unittest.TestCase):
 def test_no_provisional_percent_in_any_format(self):
  self.assertIn("startup_resume_fixed_bytes",N)
  self.assertIn("int64_t resume_early=__atomic_load_n(",N)
  self.assertIn("if(report_early && resume_early>0)",N)
  self.assertIn("if(startup_phase<3 && startup_resume>0)",N)
  self.assertIn("if(nova_x>0 && resume>0)",N)
  self.assertIn("source=ffmpeg-probe",N)
  self.assertIn("source=iso-title-metadata",N)
  self.assertIn("if(locked_early>0)",N)
  self.assertIn('android:text="0%"',U)
  self.assertIn("nativeStartupPercent()I",U)
 def test_lock_is_immutable_across_probe_and_producer(self):
  self.assertIn("__atomic_compare_exchange_n(",N)
  self.assertIn("startup_resume_fixed_bytes,&expected,resume,0",N)
  self.assertIn("startup_resume_fixed_bytes,&no_x,iso_early_resume,0",N)
  self.assertIn("nova_startup_fixed_denominator(s,resume)",T)
  self.assertIn("nova_startup_fixed_denominator(s,resume_bytes)",T)
  self.assertNotIn("__atomic_store_n(&s->startup_resume_bytes,resume_bytes",T)
 def test_first_frame_uses_same_threshold(self):
  self.assertIn("int ready=(resident>=effective_resume ||",N)
  self.assertIn("resident >= effective_resume ) {",N)
  self.assertIn("int effective_resume=startup_phase<3 && startup_resume>0 ?",N)
  self.assertIn("pst->buffer_used +",N)
  self.assertIn("(int64_t)pst->buffer2_used",N)
 def test_ui_is_armed_at_spinner(self):
  self.assertIn("armEarly(Landroid/view/View;I)V",U)
  self.assertIn("if-eqz p0, :early_done",U)
  self.assertNotIn("if-nez p0, :early_done",U)
  self.assertIn("nativeStartupResidentBytes()J",U)
  self.assertIn('const-string v3, "<1%"',U)
if __name__=="__main__":
 unittest.main()
