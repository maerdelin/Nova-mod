import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYER_PATCH = (ROOT / "scripts" / "buffer_guard_patch.py").read_text()
PREFETCH_PATCH = (ROOT / "scripts" / "prefetch_guard_patch.py").read_text()


class BufferGuardStaticChecks(unittest.TestCase):
    def test_native_buffer_and_runtime_thresholds(self):
        for token in (
            '"webdav_native_buffer_mib":128',
            "PLAYER_NATIVE_PAUSE",
            "PLAYER_NATIVE_RESUME",
            "const-wide/32 v2, 0x1800000",
            "const-wide/32 v2, 0x2d00000",
        ):
            self.assertIn(token, PLAYER_PATCH + PREFETCH_PATCH)

    def test_parser_reads_are_never_startup_gated(self):
        # Run327 failed because InputStream.read() waited for 45 MiB before FFmpeg
        # could even parse the MKV header. That design must never return.
        self.assertNotIn("awaitPrimed", PREFETCH_PATCH)
        read_start = PREFETCH_PATCH.index(".method public read([BII)I")
        read_end = PREFETCH_PATCH.index(".end method", read_start)
        read_method = PREFETCH_PATCH[read_start:read_end]
        self.assertNotIn("primeTarget", read_method)
        self.assertNotIn("SystemClock;->sleep", read_method)

    def test_native_start_gate_is_before_imediaplayer_start(self):
        start = PLAYER_PATCH.index('m=method(text," start(I)V")')
        gate = PLAYER_PATCH.index("NovaBufferGuard;->shouldDeferStart()Z", start)
        native_placeholder = PLAYER_PATCH.index("{native_block}", gate)
        activated = PLAYER_PATCH.index("NovaBufferGuard;->onPlaybackStarted()V", native_placeholder)
        self.assertLess(gate, native_placeholder)
        self.assertGreater(activated, native_placeholder)

    def test_deferred_start_has_single_native_resume_entry(self):
        for token in (
            "novaStartAfterPrime()V",
            "PLAYER_NATIVE_START_AFTER_PRIME",
            "startDeferred:Z",
            "playbackStarted:Z",
            "START_DEFERRED prefetchBytes=",
            "PREFETCH_PRIMED bytes=",
        ):
            self.assertIn(token, PLAYER_PATCH + PREFETCH_PATCH)

    def test_range_replacement_keeps_pending_start_request(self):
        start = PREFETCH_PATCH.index(".method public static onPrefetchStart(J)I")
        end = PREFETCH_PATCH.index(".end method", start)
        block = PREFETCH_PATCH[start:end]
        # A new HTTP range may reset byte counters, but must not clear the
        # already requested native start.
        self.assertNotIn("startDeferred:Z", block)

    def test_producer_uses_explicit_generation(self):
        self.assertIn("NovaPrefetchProducer;->setGeneration(I)V", PREFETCH_PATCH)
        self.assertNotIn(
            "invoke-static {}, Lcom/archos/filecorelibrary/NovaBufferGuard;->currentGeneration()I",
            PREFETCH_PATCH,
        )

    def test_manual_pause_does_not_destroy_buffer_session(self):
        self.assertIn(
            'for sig in (" stopPlayback()V"," onCompletion(Lcom/archos/medialib/IMediaPlayer;)V")',
            PLAYER_PATCH,
        )
        self.assertNotIn(
            'for sig in (" pause(I)V"," stopPlayback()V"," onCompletion',
            PLAYER_PATCH,
        )


if __name__ == "__main__":
    unittest.main()
