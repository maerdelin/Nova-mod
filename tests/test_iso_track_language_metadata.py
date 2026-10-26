"""ISO playlist PID-to-language bridge; isolated from Run704 seeking/RAW128."""
from pathlib import Path
import ast
import unittest

ROOT=Path(__file__).resolve().parents[1]
T=(ROOT/"iso/nova_transport.c").read_text(encoding="utf-8")
P=(ROOT/"scripts/iso_track_metadata_patch.py").read_text(encoding="utf-8")
W=(ROOT/".github/workflows/nova-video-player-mod.yml").read_text(encoding="utf-8")

class IsoTrackLanguageTests(unittest.TestCase):
    def test_exported_pid_lookup_is_iso_only(self):
        self.assertIn("NOVA_ISO_TRACK_LANG_V1", T)
        self.assertIn("int nova_transport_iso_track_language(", T)
        self.assertIn("s->mode == NOVA_MODE_BLURAY_ISO", T)
        self.assertIn("session_acquire(generation)", T)
        self.assertIn("session_release(s)", T)
        self.assertIn("entry->pid == (uint16_t)pid && entry->kind == kind", T)
        self.assertIn("char lang[4]", T)
        self.assertIn("!strcmp(lang, \"und\")", T)
        self.assertIn("NOVA_ISO_TRACK_CAPTURE_V1", T)
        self.assertIn("NOVA_ISO_TRACK_CONFLICT_V1", T)
        self.assertIn("NOVA_ISO_CODEC_CLPI_V2", T)
        self.assertIn("int nova_transport_iso_track_codec(", T)
        self.assertIn("dst->coding_type = stream->coding_type;", T)

    def test_bd_title_metadata_copied_before_free_without_extra_io(self):
        start=T.index("BLURAY_TITLE_INFO *ti = bd_get_title_info(s->bd, (uint32_t)main_title, 0);")
        end=T.index("bd_free_title_info(ti);",start)
        block=T[start:end]
        self.assertIn("ti->clips[0]",block)
        self.assertIn("clip->audio_streams",block)
        self.assertIn("clip->pg_streams",block)
        self.assertIn("clip->audio_stream_count",block)
        self.assertIn("clip->pg_stream_count",block)
        self.assertNotIn("bd_seek",block)
        self.assertNotIn("avio_read",block)

    def test_ffmpeg_hook_only_fills_missing_language_by_pid(self):
        ast.parse(P)
        self.assertIn('strstr(s->src_query, "&nova_iso=1&")',P)
        self.assertNotIn("s->src_query &&", P)
        self.assertIn('"nova_transport_iso_track_language"',P)
        self.assertIn("ff_p->raw.transport_generation, st->id, kind",P)
        self.assertIn('av_dict_set(&st->metadata, "language", lang, 0);',P)
        self.assertIn("!strcmp(prev->value, \"und\")",P)
        self.assertIn("action=preserve",P)
        self.assertIn("action=missing",P)
        self.assertIn("NOVA_ISO_TRACK_SUMMARY_V1",P)
        self.assertIn("NOVA_ISO_CODEC_AUDIT_V2",P)
        self.assertIn("NOVA_ISO_CODEC_LABEL_V2",P)
        self.assertIn("NOVA_ISO_TRUEHD_ATMOS_V2",P)
        self.assertIn("profile == AV_PROFILE_TRUEHD_ATMOS",P)
        self.assertIn("case 0x81: match = ff_id == AV_CODEC_ID_AC3",P)
        self.assertIn("WAVE_FORMAT_DTS_HD_MA",P)
        self.assertIn("WAVE_FORMAT_DTS_HD",P)
        self.assertIn('match == 1 && atmos_confirmed',P)
        self.assertIn("return src.replace(ANCHOR, REPLACEMENT, 1)",P)
        self.assertNotIn('av_dict_set(&st->metadata, "title"',P)

    def test_run704_seek_buffer_policy_preserved(self):
        self.assertIn("NOVA_ISO_INDEX_MAP_V3", (ROOT/"scripts/iso_index_seek_patch.py").read_text())
        self.assertIn("NOVA_MKV_RANGE_RETRY_V2",T)
        self.assertIn("NOVA_ISO_META_PAGE_BYTES (4 * 1024 * 1024)",T)
        self.assertIn("NOVA_ISO_TRACK_APPLIED_V1",P)
        self.assertIn("NOVA_MKV_BBC_CUE_SEEK_V1",P)
        self.assertIn("NOVA_ISO_INDEX_SEEK_V3",P)
        self.assertIn("python3 scripts/iso_track_metadata_patch.py --native",W)
        self.assertIn("NOVA_ISO_TRACK_APPLIED_V1",W)
        self.assertIn("NOVA_ISO_TRACK_CAPTURE_V1",W)
        self.assertIn("NOVA_ISO_CODEC_CLPI_V2",W)
        self.assertIn("NOVA_ISO_CODEC_LABEL_V2",W)
        self.assertIn("nova_transport_iso_track_codec",W)

if __name__ == "__main__":
    unittest.main()
