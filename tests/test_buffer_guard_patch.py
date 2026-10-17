import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = (ROOT / "scripts" / "buffer_guard_patch.py").read_text()

class BufferGuardStaticChecks(unittest.TestCase):
    def test_runtime_path_and_thresholds(self):
        for token in (
            "NovaBufGuard",
            "HttpSession;->novaDelivered(I)V",
            "PLAYBACK_ACTIVE startup=main-pass low=3000ms resume=5000ms",
            "PAUSE ahead<3000ms",
            "RESUME ahead>=5000ms",
            "PLAYER_NATIVE_PAUSE",
            "PLAYER_NATIVE_RESUME",
            '"webdav_native_buffer_mib":128',
        ):
            self.assertIn(token, PATCH)

    def test_startup_is_not_gated(self):
        for forbidden in ("initialHold", "beforeNativeStart", "awaitBudget", "bufferStartHeldCurrent", "NovaRebufferInputStream"):
            self.assertNotIn(forbidden, PATCH)
        start = PATCH.index('m=method(text," start(I)V")')
        native = PATCH.index("IMediaPlayer;->start()V", start)
        activate = PATCH.index("NovaBufferGuard;->onPlaybackStarted()V", native)
        self.assertGreater(activate, native)

    def test_state_machine_directions(self):
        for token in (
            "if-gez v2, :done",
            "if-ltz v15, :arm_check",
            "if-ltz v13, :arm_now",
            "if-gez v13, :loop",
            "move v7, p1",
        ):
            self.assertIn(token, PATCH)

if __name__ == "__main__":
    unittest.main()
