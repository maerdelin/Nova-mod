"""Regression for malformed torrent status guard (964 baseline; no filtering)."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from torrent_crash_guard_patch import patch_torrent_observer, MARKER

FIXTURE = """.class public Lcom/archos/mediacenter/video/browser/TorrentObserverService;
.super Landroid/app/Service;
.method public exitProcess()V
    .locals 0
    return-void
.end method
.method private observeStdout()V
    .locals 6
:try_start_0
    const-string v0, "100"
    invoke-static {v0}, Ljava/lang/Long;->parseLong(Ljava/lang/String;)J
    move-result-wide v1
    const-string v0, "50"
    invoke-static {v0}, Ljava/lang/Long;->parseLong(Ljava/lang/String;)J
    move-result-wide v3
    sub-long/2addr v1, v3
:try_end_0
    .catch Ljava/io/InterruptedIOException; {:try_start_0 .. :try_end_0} :catch_interrupt
    .catch Ljava/io/IOException; {:try_start_0 .. :try_end_0} :catch_io
    return-void
:catch_interrupt
    move-exception v0
    return-void
:catch_io
    move-exception v0
    return-void
.end method
"""

class CrashGuardTests(unittest.TestCase):
    def test_guards_bad_decimal_and_short_fields(self):
        out = patch_torrent_observer(FIXTURE)
        self.assertEqual(out.count(MARKER), 1)
        for name in ("NumberFormatException", "ArrayIndexOutOfBoundsException"):
            self.assertIn(".catch Ljava/lang/" + name +
                "; {:try_start_0 .. :try_end_0} :nova_torrent_bad_stdout", out)
        self.assertIn("NOVA_TORRENT_GUARD", out)
        self.assertIn("->exitProcess()V", out)
        self.assertEqual(out.count("->parseLong(Ljava/lang/String;)J"), 2)

    def test_idempotence_is_rejected(self):
        with self.assertRaises(RuntimeError):
            patch_torrent_observer(patch_torrent_observer(FIXTURE))

    def test_fail_closed_on_changed_upstream(self):
        for s in (
            FIXTURE.replace("observeStdout()", "observeOther()"),
            FIXTURE.replace("exitProcess()", "somethingElse()"),
            FIXTURE.replace("Ljava/io/IOException;", "Ljava/io/EOFException;"),
            FIXTURE.replace("Long;->parseLong", "Integer;->parseInt"),
        ):
            with self.assertRaises(RuntimeError):
                patch_torrent_observer(s)

    def test_normal_parsing_and_other_methods_untouched(self):
        out = patch_torrent_observer(FIXTURE)
        self.assertTrue(out.startswith(FIXTURE.split(".method private observeStdout()")[0]))
        self.assertIn("sub-long/2addr v1, v3", out)
        self.assertNotIn("application/x-bittorrent", out)
        self.assertNotIn("FILTER", out)

if __name__ == "__main__":
    unittest.main()
