"""Run380 ISO title duration -> AVOS X handoff boundary and scope tests.

The parser snippet is extracted from the exact C patch and compiled with the
host C compiler: malformed/oversized metadata must never bypass fallback.
No real WebDAV or disc bytes are needed for these deterministic checks.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ts_bitrate_patch


class TestIsoTitleDuration(unittest.TestCase):
    def test_iso_title_exports_only_valid_duration_without_touching_seek(self):
        c = (ROOT / "iso" / "nova_iso.c").read_text()
        self.assertIn("uint64_t title_duration_us;", c)
        self.assertIn("ti->duration >= 10ULL * 90000", c)
        self.assertIn("ti->duration <= 24ULL * 3600 * 90000", c)
        self.assertIn("s->title_duration_us = (ti->duration * 100) / 9;", c)
        self.assertIn("&nova_iso=1&nova_iso_duration_us=%", c)
        self.assertIn('main.m2ts?mpegts&nova_iso=1", g_session->port', c)
        self.assertEqual(c.count("bd_select_title(s->bd, (uint32_t)main_title)"), 1)
        self.assertEqual(c.count("s->title_size = bd_get_title_size(s->bd)"), 1)
        self.assertEqual(c.count("bd_read(s->bd,"), 1)
        self.assertEqual(c.count("fetch_range_playback(in,"), 1)

    def test_ts_bitrate_patch_preserves_generic_arithmetic_and_source(self):
        sample = (
            "/* NOVA_DYNAMIC_BUFFER: */\n"
            "/* NOVA_DYNAMIC_BUFFER: */\n"
            + ts_bitrate_patch.ANCHOR + "\n"
        )
        updated = ts_bitrate_patch.transform(sample)
        self.assertIn('strstr(s->src_query, "&nova_iso=1&")', updated)
        self.assertNotIn("s->src_query &&", updated)
        self.assertIn('"iso-title-metadata" : "duration-derived"', updated)
        self.assertIn("nova_ts_source = nova_iso_metadata_valid ?", updated)
        self.assertIn("whole * AV_TIME_BASE +", updated)
        self.assertIn("nova_ts_demux_bps / 8", updated)
        self.assertIn("nova_max_x", updated)
        self.assertEqual(updated.count(ts_bitrate_patch.ANCHOR), 1)
        self.assertLess(updated.index("nova_iso_duration_arg"), updated.index("nova_ts_source = nova_iso_metadata_valid ?"))
        with self.assertRaises(RuntimeError):
            ts_bitrate_patch.transform(updated)

    def test_real_title_arithmetic_decimal_units(self):
        size = 87096612864
        duration_ticks = 7023 * 90000
        duration_us = (duration_ticks * 100) // 9
        self.assertEqual(duration_us, 7023000000)
        x = (size * 1000000) // duration_us
        self.assertEqual(x, 12401625)
        self.assertEqual((x * 2, x * 5, x * 10),
                         (24803250, 62008125, 124016250))

    def test_real_compiled_c_parser_accepts_only_iso_legal_values(self):
        code = ts_bitrate_patch.TS_CODE
        start = code.index("        // Only the locally generated Blu-ray ISO proxy")
        end = code.index("        if (ff_p->size_known", start)
        parse = code[start:end]
        program = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define AV_TIME_BASE 1000000LL
typedef struct { const char *src_query; } TestStream;
static int64_t parse_iso(const char *query, int *valid) {
    TestStream storage = {query};
    TestStream *s = &storage;
    int64_t nova_ts_duration_us = -1;
""" + parse + r"""
    *valid = nova_iso_metadata_valid;
    return nova_ts_duration_us;
}
typedef struct {
    const char *query;
    int valid;
    int64_t duration;
} Case;
int main(void) {
    const Case cases[] = {
        {"?mpegts&nova_iso=1&nova_iso_duration_us=7023000000", 1, 7023000000LL},
        {"?mpegts&nova_iso=1&nova_iso_duration_us=7023000000&other=1", 1, 7023000000LL},
        {"?mpegts&nova_iso=1&nova_iso_duration_us=10000000", 1, 10000000LL},
        {"?mpegts&nova_iso=1&nova_iso_duration_us=86400000000", 1, 86400000000LL},
        {"?mpegts&nova_iso=1", 0, -1LL},
        {"?mpegts", 0, -1LL},
        {"", 0, -1LL},  // src_query is an always-present fixed array in real AVOS
        {"?mpegts&nova_iso=11&nova_iso_duration_us=7023000000", 0, -1LL},
        {"?mpegts&not_nova_iso=1&nova_iso_duration_us=7023000000", 0, -1LL},
        {"?mpegts&nova_iso=1&nova_iso_duration_us=0", 0, -1LL},
        {"?mpegts&nova_iso=1&nova_iso_duration_us=9999999", 0, -1LL},
        {"?mpegts&nova_iso=1&nova_iso_duration_us=86400000001", 0, -1LL},
        {"?mpegts&nova_iso=1&nova_iso_duration_us=99999999999999999999999", 0, -1LL},
        {"?mpegts&nova_iso=1&nova_iso_duration_us=-7023000000", 0, -1LL},
        {"?mpegts&nova_iso=1&nova_iso_duration_us=+7023000000", 0, -1LL},
        {"?mpegts&nova_iso=1&nova_iso_duration_us=7023000000junk", 0, -1LL},
        {"?mpegts&nova_iso=1&nova_iso_duration_us=", 0, -1LL},
    };
    for (size_t i = 0; i < sizeof(cases)/sizeof(cases[0]); i++) {
        int valid = -1;
        int64_t actual = parse_iso(cases[i].query, &valid);
        if (valid != cases[i].valid || actual != cases[i].duration) {
            fprintf(stderr, "parser case %zu failed: valid=%d duration=%lld\n",
                    i, valid, (long long)actual);
            return 1;
        }
    }
    return 0;
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            src, exe = Path(tmp) / "iso_test.c", Path(tmp) / "iso_test"
            src.write_text(program)
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            str(src), "-o", str(exe)], check=True, capture_output=True)
            subprocess.run([str(exe)], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
