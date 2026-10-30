"""Regress shared 128 MiB producer/consumer/pause/resume state machine.

Source assertions intentionally guard the exact production invariants.  The
native page-view C harness runs separately (test_shared42_page_view_native).
"""
import pathlib
import unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class Backpressure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=(ROOT/"iso/nova_literange4.inc").read_text()
        cls.p=(ROOT/"scripts/shared42_native_patch.py").read_text()
    def test_exact_paused_callback_replay(self):
        s=self.c
        self.assertIn("p->pause_need_pages=extra;",s)
        self.assertIn("nova_lite_can_stage(p,required)",s)
        self.assertIn("curl_easy_pause(p->easy,CURLPAUSE_CONT)",s)
        self.assertIn("p->paused=0;\n    p->pause_need_pages=0;",s)
        self.assertIn("if(head->paused)return rc;",s)
    def test_empty_page_wake_and_delivery_wake(self):
        s=self.c
        waiting=s[s.index("shared42_await_more:"):s.index("int running=0;",s.index("shared42_await_more:"))]
        self.assertIn("nova_lite_resume_paused(s)",waiting)
        delivery=s[s.index("current->delivered+=take"):s.index("return take;",s.index("current->delivered+=take"))]
        self.assertIn("nova_lite_resume_paused(s)",delivery)
    def test_page_pool_budget(self):
        self.assertIn("raw->page_queued >= 1376",self.p)
        self.assertIn("raw->capacity_bytes=86 * 1024 * 1024",self.p)
        self.assertIn("NOVA_SHARED42_MKV_PAGE_VIEW_V1", (ROOT/"iso/nova_transport.c").read_text())
    def test_error_escapes_wait(self):
        self.assertIn("if(nova_lite_resume_paused(s)<0)return NOVA_MULTI_FALLBACK;",self.c)
        self.assertIn("NOVA_SHARED42_RESUME_ERROR",self.c)
if __name__=="__main__":
    unittest.main()
