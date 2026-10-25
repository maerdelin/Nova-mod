"""Run681 non-ISO source-level regressions and Run680 ISO invariants."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class NonISOSeekTests(unittest.TestCase):
    def test_only_regular_files_bypass_sticky_avio(self):
        code = (ROOT/"scripts/direct_transport_native_patch.py").read_text()
        self.assertIn('if (strstr(url, "/stream?") != NULL)', code)
        self.assertIn('raw->source->direct = 1;', code)
        self.assertIn('raw->source->error = 0;', code)
        self.assertIn('raw->source->eof_reached = 0;', code)
        self.assertNotIn('strstr(url, "/main.m2ts") != NULL', code)

    def test_cursor_is_transactional_bounded(self):
        code=(ROOT/"iso/nova_transport.c").read_text()
        self.assertIn('NOVA_NONISO_SEEK_HEAL_V1', code)
        self.assertIn('const int64_t at=s->file_cursor;',code)
        self.assertIn('s->file_cursor=at+got;',code)
        self.assertIn('s->file_cursor=target;',code)
        self.assertIn('NOVA_FILE_SEEK_RECOVERED',code)
        self.assertIn('attempt<=3',code)
        self.assertIn('return s->stopping ? AVERROR_EXIT : AVERROR(EAGAIN);',code)

    def test_iso_source_and_1p5x3x_baseline_preserved(self):
        transport=(ROOT/"iso/nova_transport.c").read_text()
        self.assertIn('ret = bd_read(s->bd, dst, size);',transport)
        self.assertIn('ret = bd_seek(s->bd, (uint64_t)target);',transport)
        self.assertIn('bd_read(s->bd, discard, ask);',transport)
        index=(ROOT/"scripts/iso_index_seek_patch.py").read_text()
        self.assertIn('NOVA_ISO_INDEX_SEEK_V3',index)
        policy=(ROOT/"scripts/native_rebuffer_patch.py").read_text()
        self.assertIn('requested_low = nova_x + nova_x / 2;',policy)
        self.assertIn('requested_resume = 3 * nova_x;',policy)

if __name__ == "__main__":
    unittest.main()
