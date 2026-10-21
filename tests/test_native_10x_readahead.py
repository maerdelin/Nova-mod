from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class Native10XReadAheadTests(unittest.TestCase):
    def setUp(self): self.s=(ROOT/'scripts/native_rebuffer_patch.py').read_text()
    def test_no_extra_java_prefetch_wall(self):
        self.assertFalse((ROOT/'webdav_fixes/src/com/archos/filecorelibrary/NovaAheadInputStream.java').exists())
        self.assertFalse((ROOT/'scripts/readahead_patch.py').exists())
    def test_pause_does_not_stop_producer(self):
        self.assertIn('readahead_enabled',self.s)
        self.assertIn('NOVA_10X_READAHEAD',self.s)
        self.assertIn('__atomic_store_n(&video->s->readahead_enabled, 1',self.s)
        self.assertIn('!s->paused || __atomic_load_n( &s->readahead_enabled',self.s)
    def test_existing_dynamic_10x_is_normal_wall(self):
        self.assertIn('s->rebuffer_capacity_bytes = (int)(10 * nova_x);',self.s)
        self.assertIn('ff_p->buffer_size = s->rebuffer_capacity_bytes;',self.s)
        self.assertIn('FFmpeg dynamic 10X byte wall missing',self.s)
        self.assertIn('nova_fill_to_byte_wall',self.s)
        self.assertIn('NOVA_10X_PACKET_CAP_BYPASS',self.s)
        self.assertNotIn('"manual_pause_packet_cap": 8192',self.s)
        self.assertIn('"extra_prefetch_wall_bytes": 0',self.s)
if __name__=='__main__': unittest.main()
