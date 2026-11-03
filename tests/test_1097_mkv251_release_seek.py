"""NOVA 1097: spinner-triggered WebDAV MKV release-only DPAD fallback.

Do not classify by file length, a single HTTP403, or MKV container alone.
All ordinary MKV seeks retain their live frame preview until the ACTUAL
loading UI tries to show while DPAD seeking is still held down.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def source(path):
    return (ROOT / path).read_text()

class SpinnerOnlyFallback(unittest.TestCase):
    def test_native_predicate_is_format_only_not_403_or_size(self):
        src = source("iso/nova_transport.c")
        player = source("scripts/mkv_251_release_seek_patch.py")
        self.assertIn("Java_com_archos_mediacenter_video_player_DirectTransportProxy_nativeIsWebdavMkv",src)
        self.assertIn("s->mode==NOVA_MODE_FILE",src)
        self.assertIn("s->file_http_mode",src)
        self.assertNotIn("2509221119",src)
        self.assertNotIn("nativeIsMkv403Recovered",player)
        self.assertNotIn("nativeIsSpecialMkv251",player)
        self.assertIn("nativeIsWebdavMkv()Z",player)

    def test_only_real_activity_loading_show_triggers_hold(self):
        player = source("scripts/mkv_251_release_seek_patch.py")
        self.assertIn("def patch_activity_spinner_handler",player)
        self.assertIn('"handleMessage(Landroid/os/Message;)V", hook',player)
        self.assertIn("nova251OnSeekSpinner()Z",player)
        self.assertIn("const/4 v1, 0x1",player)
        self.assertIn("nova251_activity_original",player)
        self.assertIn("nova251_activity_suppressed",player)
        self.assertIn("const/16 v1, 0x8",player)
        self.assertIn("mSeekKeyDirection:I",player)
        self.assertIn("mIsStopped:Z",player)
        # A real UI event sets the flag; a 403 never enables UI-only mode.
        hook = player.split(".method public nova251OnSeekSpinner()Z",1)[1].split(".end method",1)[0]
        self.assertIn("iput-boolean v0, p0, {PC}->mNova251Hold:Z",hook)
        self.assertNotIn("403",hook)
        self.assertNotIn("2509221119",hook)

    def test_original_seek_retained_until_spinner_event(self):
        player = source("scripts/mkv_251_release_seek_patch.py")
        self.assertIn('iget-boolean v0, p0, {PC}->mNova251Hold:Z',player)
        self.assertIn('if-eqz v0, :nova251_original_seek',player)
        self.assertIn('src = edit_method(src, "onSeek(IZ)V", modify_on_seek)',player)
        self.assertIn("invoke-direct {{p0, p1}}, {PC}->nova251BeginHold(I)V",player)

    def test_no_native_seek_while_fallback_key_is_held(self):
        player = source("scripts/mkv_251_release_seek_patch.py")
        hold = player.split(".method private nova251BeginHold(I)V",1)[1].split(".end method",1)[0]
        tick = player.split(".method public nova251HoldTick()V",1)[1].split(".end method",1)[0]
        self.assertNotIn("->seekTo(I)V",hold+tick)
        self.assertNotIn("->pause(I)V",hold+tick)
        self.assertIn("nova251ArmTick",hold)
        self.assertIn("nova251ArmTick",tick)

    def test_keyup_commits_final_target_once(self):
        player = source("scripts/mkv_251_release_seek_patch.py")
        commit = player.split(".method private nova251Commit()V",1)[1].split(".end method",1)[0]
        self.assertIn("nativeIsWebdavMkv()Z",commit)
        self.assertIn("if-ltz v0, :nova251_commit_clear",commit)
        self.assertEqual(commit.count("->seekTo(I)V"),1)
        self.assertIn("    invoke-direct {{p0}}, {PC}->nova251Commit()V",player)
        self.assertIn("nova251Cancel",player)

    def test_recovered_remote_index_still_packet_validated(self):
        index = source("scripts/startup_bbc_seek_fix_patch.py")
        self.assertIn("NOVA_MKV_403_RECOVERED_INDEX_V1",index)
        self.assertIn("ff_p->raw.mkv_single_get",index)
        self.assertNotIn("2509221119",index)
        self.assertIn("ff_p->raw.mkv_seek_deadline_us > av_gettime_relative()",index)
        self.assertIn("if(nova_mkv_seek && ret >= 0 && nova_mkv_seek_guard_failed(&ff_p->raw))",index)

if __name__ == "__main__":
    unittest.main()
