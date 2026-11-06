"""Regression guard: Run393 exit-during-network-Seek cannot wait for CURL 15s."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fix_run393_exit_anr import patch_avos_mp, patch_lite, MARK, LITE_MARK


class Run393ExitAnr(unittest.TestCase):
    def test_gen_scoped_abort_is_before_async_wait(self):
        upstream = (
            "#include <inttypes.h>\n"
            "static int avos_mp_close(avos_mp_t *mp);\n"
            "static int avos_mp_destroy(avos_mp_t *mp)\n"
            "{\n\tMPLOG();\n"
            "\tpthread_mutex_lock(&mp->async.mtx);\n"
            "\tasync_cmd_add(mp, ASYNC_CMD_WAIT, 0);\n}\n"
        )
        result = patch_avos_mp(upstream)
        self.assertIn(MARK, result)
        self.assertIn('sscanf(url + 16, "%" SCNu64, &generation)', result)
        self.assertIn('dlsym(h, "nova_transport_abort")', result)
        self.assertIn('strncmp(url, "novatransport://", 16)', result)
        self.assertLess(result.index("\tnova_393_abort_before_destroy(mp);"),
                        result.index("async_cmd_add(mp, ASYNC_CMD_WAIT, 0);"))
        self.assertIn("MPLOG(", result)
        self.assertNotIn("__android_log_print", result)
        with self.assertRaises(RuntimeError):
            patch_avos_mp(result)

    def test_curl_abort_only_when_session_stopping(self):
        upstream = (
            "static int nova_lite_launch(nova_lite_slot *p)\n"
            "{\n    nova_session *s=p->owner->session;\n"
            "    NOVA_CURL_SET(CURLOPT_CONNECTTIMEOUT_MS,10000L);\n"
            "    NOVA_CURL_SET(CURLOPT_LOW_SPEED_TIME,15L);\n}\n"
        )
        result = patch_lite(upstream)
        self.assertIn(LITE_MARK, result)
        self.assertIn("CURLOPT_NOPROGRESS,0L", result)
        self.assertIn("CURLOPT_XFERINFOFUNCTION,nova_393_shutdown_progress", result)
        self.assertIn("CURLOPT_XFERINFODATA,s", result)
        self.assertIn("__atomic_load_n(&s->stopping,__ATOMIC_ACQUIRE)", result)
        self.assertIn("CURLOPT_LOW_SPEED_TIME,15L", result)
        with self.assertRaises(RuntimeError):
            patch_lite(result)


if __name__ == "__main__":
    unittest.main()
