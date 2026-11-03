"""NOVA 1119: regression for >2GiB watched/resumed video size in three UIs."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fix_resumed_file_size_1119 as fix


def make_original_mapper():
    return f""".class public {fix.MAPPER}
.super Ljava/lang/Object;

.method public bind(Landroid/database/Cursor;)Ljava/lang/Object;
    .locals 45
    iget v0, v0, {fix.MAPPER}->mSizeColumn:I

    invoke-interface {{v1, v0}}, Landroid/database/Cursor;->getLong(I)J

    move-result-wide v41
    iget v2, v0, {fix.MAPPER}->mSizeColumn:I

    invoke-interface {{v1, v2}}, Landroid/database/Cursor;->getLong(I)J

    move-result-wide v37

    iget v0, v0, {fix.MAPPER}->mSizeColumn:I

    invoke-interface {{v1, v0}}, Landroid/database/Cursor;->getInt(I)I

    move-result v0

    int-to-long v0, v0

    move-wide/from16 v20, v0
    invoke-direct/range {{v4 .. v21}}, {fix.VIDEO}-><init>(JLjava/lang/String;Ljava/lang/String;Landroid/net/Uri;IIIIZZZZJJ)V
    return-object v4
.end method
"""


def make_card():
    return f""".class public L{fix.ROOT}/leanback/presenter/PosterImageCardPresenter;
.method private bindVideo()V
    instance-of v3, p2, {fix.NONINDEXED}

    if-eqz v3, {fix.CARD_SKIP}

    invoke-virtual {{p2}}, {fix.VIDEO}->getSize()J
    invoke-static {{v3, v0, v1}}, Landroid/text/format/Formatter;->formatFileSize(Landroid/content/Context;J)Ljava/lang/String;
    :nova_a18b0441c7_24
    return-void
.end method
"""


def make_binder():
    return f""".class public Lcom/example/Mock;
.method public bind()V
    invoke-virtual {{p2}}, {fix.VIDEO}->getSize()J
    invoke-static {{v3, v0, v1}}, Landroid/text/format/Formatter;->formatFileSize(Landroid/content/Context;J)Ljava/lang/String;
    return-void
.end method
"""


class TestNOVA1119(unittest.TestCase):
    def test_prove_32bit_overflow_on_real_compilation_sizes(self):
        for size in (2509221119, 2432999422, 2152230599):
            truncated_signed = ((size + (1 << 31)) % (1 << 32)) - (1 << 31)
            self.assertLess(truncated_signed, 0)
            self.assertGreater(size, (1 << 31)-1)
            # Original UI has if-lez/cmp-long > 0; incorrect negative hides size.
            self.assertFalse(truncated_signed > 0)
            self.assertTrue(size > 0)

    def test_only_generic_video_cursor_path_is_widened(self):
        old = make_original_mapper()
        updated = fix.repair_plain_video_cursor(old)
        self.assertIn("Cursor;->getLong(I)J", updated)
        self.assertEqual(updated.count("Cursor;->getLong(I)J"), 3)
        self.assertIn("move-result-wide v0", updated)
        self.assertNotIn("int-to-long v0, v0", updated)
        self.assertEqual(updated.count("move-wide/from16 v20, v0"), 1)
        self.assertIn("move-result-wide v41", updated)
        self.assertIn("move-result-wide v37", updated)
        self.assertIn(fix.TAG, updated)
        with self.assertRaises(RuntimeError):
            fix.repair_plain_video_cursor(updated)

    def test_tv_card_includes_indexed_video_and_preserves_scraped_text(self):
        updated = fix.repair_tv_card_type_guard(make_card())
        self.assertIn(f"instance-of v3, p2, {fix.MOVIE}", updated)
        self.assertIn(f"instance-of v3, p2, {fix.EPISODE}", updated)
        self.assertIn(f"if-nez v3, {fix.CARD_SKIP}", updated)
        self.assertNotIn(f"instance-of v3, p2, {fix.NONINDEXED}", updated)
        self.assertIn(f"{fix.VIDEO}->getSize()J", updated)
        with self.assertRaises(RuntimeError):
            fix.repair_tv_card_type_guard(updated)

    def test_file_changes_are_surgical_and_all_three_ui_binders_present(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            files = {
                f"{fix.ROOT}/browser/adapters/mappers/VideoCursorMapper.smali": make_original_mapper(),
                f"{fix.ROOT}/leanback/presenter/PosterImageCardPresenter.smali": make_card(),
                f"{fix.ROOT}/leanback/presenter/VideoListPresenter.smali": make_binder(),
                f"{fix.ROOT}/browser/presenter/VideoListPresenter.smali": make_binder(),
            }
            for sub, content in files.items():
                target=root/"smali"/sub
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            report=root/"report.json"
            out=fix.patch(root,report)
            self.assertEqual(out["status"],"PASS")
            self.assertEqual(set(out["three_size_binders"]),
                             {"phone_tablet_list","tv_poster_card","tv_horizontal_list"})
            self.assertEqual(json.loads(report.read_text()),out)
            for sub,content in files.items():
                p=(root/"smali"/sub).read_text()
                if "VideoCursorMapper" in sub or "PosterImageCardPresenter" in sub:
                    self.assertNotEqual(p,content)
                else:
                    self.assertEqual(p,content)
            with self.assertRaises(RuntimeError):
                fix.patch(root,report)

    def test_older_seek_and_403_logic_untouched(self):
        granular = (ROOT/"scripts"/"granular_build.py").read_text()
        self.assertIn("fix_resumed_file_size_1119.patch(candidate",granular)
        self.assertIn("g.apply(candidate, patch",granular)
        self.assertIn("native_transport_changed", (ROOT/"scripts"/"fix_resumed_file_size_1119.py").read_text())
        self.assertIn("NOVA_MKV_SPINNER_RELEASE_ONLY_V3",(ROOT/"scripts"/"mkv_251_release_seek_patch.py").read_text())


if __name__ == "__main__":
    unittest.main()
