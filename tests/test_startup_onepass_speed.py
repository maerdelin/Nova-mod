#!/usr/bin/env python3
"""Source-only regression contracts for the one-build startup spinner fix."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import startup_onepass_speed_patch as speed

class StartupOnePassTests(unittest.TestCase):
    def fixture(self):
        return (
            "    unsigned nova_boot_consumer_calls;\n"
            "    if (!raw->direct_read || !raw->direct_seek ||\n"
            "        !raw->direct_size || !raw->direct_abort || !raw->direct_set_target_bps)\n"
            "        return AVERROR(ENOSYS);\n"
            "    ret = pthread_create(&raw->thread, NULL, nova_raw_thread, raw);\n"
            "        pthread_mutex_lock(&raw->source_mutex);\n"
            "        pthread_mutex_lock(&raw->mutex);\n"
            "        if( !__atomic_load_n( &raw->run, __ATOMIC_ACQUIRE ) ||\n"
            "            raw->eof || raw->used_bytes >= raw->capacity_bytes ) {\n"
            "        pthread_mutex_lock(&raw->mutex);\n"
            "        if( generation != raw->generation ) {\n"
            "    int64_t current = raw->consumer_pos;\n"
            "    int64_t size = raw->source_size;\n"
            "    pthread_mutex_unlock(&raw->mutex);\n"
            "    int64_t nova_boot_seek_lock_begin=av_gettime_relative();\n"
            "    pthread_mutex_lock(&raw->source_mutex);\n"
            "    int64_t nova_boot_seek_lock_ms=(av_gettime_relative()-nova_boot_seek_lock_begin)/1000;\n"
            "    pthread_mutex_unlock(&raw->source_mutex);\n"
            "    return result;\n}\n\nstatic void nova_raw_stats\n"
            '    serprintf("NOVA_STARTUP_TRACE probe_done t=%d streams=%d\\n", atime(), ff_p->fmt->nb_streams);\n'
        )

    def test_patch_scopes_and_idempotency(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/"Source"/"stream_parser_ffmpeg.c"
            p.parent.mkdir()
            p.write_text(self.fixture())
            speed.apply(Path(folder))
            s=p.read_text()
            for marker in (
                "NOVA_STARTUP_ONEPASS_V1", "startup_reloc_pending",
                "pthread_cond_wait(&raw->can_write,&raw->mutex)",
                "raw->startup_probe_hint(raw->transport_generation,1)",
                "raw->startup_probe_hint(raw->transport_generation,0)",
                "got==AVERROR(EINTR)",
                "startup_probe_active,0,__ATOMIC_RELEASE",
            ):
                self.assertIn(marker,s)
            with self.assertRaises(RuntimeError):
                speed.apply(Path(folder))

    def test_malformed_pinned_anchor_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/"Source"/"stream_parser_ffmpeg.c"
            p.parent.mkdir()
            p.write_text(self.fixture().replace(
                "    int64_t nova_boot_seek_lock_begin=av_gettime_relative();",
                "    int64_t changed_anchor=0;"))
            with self.assertRaises(RuntimeError):
                speed.apply(Path(folder))

    def test_transport_is_file_probe_only(self):
        c=(ROOT/"iso"/"nova_transport.c").read_text()
        self.assertIn("nova_transport_startup_probe_hint",c)
        self.assertIn("s->mode==NOVA_MODE_FILE",c)
        self.assertIn("startup_probe_complete,1,__ATOMIC_RELEASE",c)
        self.assertIn("ret = AVERROR(EINTR)",c)
        self.assertIn("startup_read_preempt",c)
        self.assertIn("if (s->mode == NOVA_MODE_BLURAY_ISO)",c)

    def test_curl_probe_split_redirect_security_and_fallback(self):
        c=(ROOT/"iso"/"nova_literange4.inc").read_text()
        for marker in (
            "return 4ULL*1024*1024", "probe_piece_switchover",
            "NOVA_STARTUP_CURL_CANCEL", "CURLINFO_EFFECTIVE_URL",
            "NOVA_STARTUP_REDIRECT_CACHE",
            "NOVA_STARTUP_REDIRECT_ORIGIN_RETRY",
            "p->origin_retry_once=1", "!p->used_probe_redirect",
            "startup_probe_complete", "free(e->probe_redirect_url)",
        ):
            self.assertIn(marker,c)
        self.assertIn("CURLOPT_SSL_VERIFYPEER,1L",c)
        self.assertIn("CURLOPT_SSL_VERIFYHOST,2L",c)
        self.assertIn("CURLOPT_HTTP_VERSION,CURL_HTTP_VERSION_1_1",c)

if __name__=="__main__":
    unittest.main()
