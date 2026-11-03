"""NOVA 1097: exact-MKV hold-only seek regression guards.

Ordinary Matroska must retain existing mid-hold frame preview and seekTo calls.
The special 2,509,221,119-byte video moves only its UI target until key-up.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path):
    return (ROOT/path).read_text()


class Special251Only(unittest.TestCase):
    def test_special_identity_is_exact_byte_size_and_live_webdav_mkv(self):
        src = text("iso/nova_transport.c")
        self.assertIn("s->file_http_mode &&", src)
        self.assertIn("s->mode==NOVA_MODE_FILE && s->upstream_size==2509221119LL", src)
        self.assertIn("Java_com_archos_mediacenter_video_player_DirectTransportProxy_nativeIsSpecialMkv251", src)

    def test_all_other_mkv_preserve_original_seek_and_three_retries(self):
        native = text("iso/nova_transport.c")
        patch = text("scripts/mkv_251_release_seek_patch.py")
        self.assertIn("max_attempts=special251?6u:3u", native)
        self.assertIn("!(special251 && rc==AVERROR_HTTP_FORBIDDEN)", native)
        self.assertIn("if-eqz v0, :nova251_original_seek", patch)
        self.assertIn('src = edit_method(src, "onSeek(IZ)V", modify_on_seek)', patch)
        self.assertIn("invoke-direct {{p0, p1}}, {PC}->nova251BeginHold(I)V", patch)

    def test_hold_never_issues_seek_or_pause(self):
        patch = text("scripts/mkv_251_release_seek_patch.py")
        hold = patch.split(".method private nova251BeginHold(I)V",1)[1].split(".end method",1)[0]
        tick = patch.split(".method public nova251HoldTick()V",1)[1].split(".end method",1)[0]
        self.assertNotIn("->seekTo(I)V", hold + tick)
        self.assertNotIn("->pause(I)V", hold + tick)
        self.assertIn("nova251ArmTick", hold)
        self.assertIn("nova251ArmTick", tick)

    def test_keyup_submits_nonnegative_target_exactly_once(self):
        patch = text("scripts/mkv_251_release_seek_patch.py")
        commit = patch.split(".method private nova251Commit()V",1)[1].split(".end method",1)[0]
        self.assertIn("if-ltz v0, :nova251_commit_clear", commit)
        self.assertNotIn("if-gez v0, :nova251_commit_clear", commit)
        self.assertEqual(commit.count("->seekTo(I)V"), 1)
        self.assertIn("nativeIsSpecialMkv251()Z", commit)
        self.assertIn("    invoke-direct {{p0}}, {PC}->nova251Commit()V", patch)
        self.assertIn('once(method, original,',patch)

    def test_special_recovered_index_still_needs_packet_verification(self):
        patch = text("scripts/startup_bbc_seek_fix_patch.py")
        self.assertIn("NOVA_MKV_251_RECOVERED_INDEX_V1", patch)
        self.assertIn("ff_p->raw.source_size == 2509221119LL",patch)
        self.assertIn("ff_p->raw.mkv_seek_deadline_us > av_gettime_relative()", patch)
        self.assertIn("if(nova_mkv_seek && ret >= 0 && nova_mkv_seek_guard_failed(&ff_p->raw))",patch)


if __name__=="__main__":
    unittest.main()
