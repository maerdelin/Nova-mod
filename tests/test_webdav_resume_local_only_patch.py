"""#742: local-only resume XML, passthrough uploads and fail-closed semantics."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import webdav_resume_local_only_patch as p

class ResumeLocalOnlyPatchTests(unittest.TestCase):
    @staticmethod
    def sample():
        return (".class public Lcom/thegrizzlylabs/sardineandroid/impl/OkHttpSardine;\n"
                ".super Ljava/lang/Object;\n"
                ".method public put(Ljava/lang/String;Ljava/io/File;Ljava/lang/String;)V\n"
                "    .locals 1\n    const/4 v0, 0x0\n    return-void\n.end method\n"
                ".method public put(Ljava/lang/String;[BLjava/lang/String;)V\n"
                "    .locals 1\n    return-void\n.end method\n"
                ".method public unrelated()V\n    .locals 0\n    return-void\n.end method\n")

    def test_original_file_put_byte_identical_except_rename(self):
        original = self.sample()
        new = p.patch_source(original)
        renamed = p.METHOD.search(original).group().replace(
            p.OLD_HEADER, p.RENAMED_HEADER, 1)
        self.assertIn(renamed, new)
        self.assertIn(p.WRAPPER, new)
        self.assertEqual(new.count(p.OLD_HEADER), 1)
        self.assertEqual(new.count(p.RENAMED_HEADER), 1)
        self.assertEqual(new.count(p.MARKER), 1)
        self.assertEqual(original.split(".method public unrelated()V")[1],
                         new.split(".method public unrelated()V")[1])
        self.assertIn(".method public put(Ljava/lang/String;[BLjava/lang/String;)V", new)

    def test_resume_paths_including_raw_encoded_chinese_and_signed(self):
        base = "http://127.0.0.1:5244/%E4%B8%AD%E6%96%87/[HDR]"
        cases = [base+"/.movie.mkv.0.archos.resume.xml",
                 base+"/.movie.mkv.44.archos.resume.xml",
                 base+"/.movie.mkv.88.archos.resume.xml",
                 base+"/.movie.mkv.archos.resume.xml",
                 base+"/%2Emovie.mkv.0.archos.resume.xml",
                 base+"/%2emovie.mkv.0.archos.resume.xml",
                 base+"/.movie.mkv%2E0%2Earchos%2Eresume%2Exml",
                 base+"/.movie.mkv.0.archos.resume.xml?token=abc%2F",
                 "https://example.org/影视/电影/.影片.mkv.0.archos.resume.xml",
                 "webdav://example.org/folder/.movie.mkv.0.archos.resume.xml",
                 "webdavs://example.org/.movie.mkv.88.archos.resume.xml"]
        for url in cases:
            with self.subTest(url=url):
                self.assertTrue(p.classify_url(url))

    def test_other_put_urls_and_local_files_not_blocked(self):
        cases = [None,"","http://example.org/movie.mkv",
                 "https://example.org/.nomedia",
                 "http://example.org/ordinary-upload.xml",
                 "http://example.org/visible.mkv.0.archos.resume.xml",
                 "http://example.org/.movie.mkv.0.archos.resume.xml.bak",
                 "file:///data/user/0/org.courville.nova/.movie.0.archos.resume.xml",
                 "http://example.org/movie%2F.hidden.mkv.0.archos.resume.xml"]
        for url in cases:
            with self.subTest(url=url):
                self.assertFalse(p.classify_url(url))

    def test_wrapper_short_circuits_before_original(self):
        source = p.WRAPPER
        self.assertLess(source.index("Ljava/util/regex/Pattern;->matches"),
                        source.index("if-eqz v0, :nova_resume_original_put",
                                     source.index("Ljava/util/regex/Pattern;->matches")))
        self.assertLess(source.index("return-void"),
                        source.index("->novaPutOriginalFile"))
        self.assertEqual(source.count("->novaPutOriginalFile"), 1)
        self.assertNotIn("XmlDb", source)
        self.assertNotIn("SQLite", source)
        self.assertNotIn("getInputStream", source)

    def test_fail_closed_when_original_method_changes_or_double_patch(self):
        original = self.sample()
        with self.assertRaisesRegex(RuntimeError,"class identity"):
            p.patch_source(original.replace("OkHttpSardine;","OtherSardine;"))
        with self.assertRaisesRegex(RuntimeError,"exactly one"):
            p.patch_source(original.replace(p.OLD_HEADER,".method public otherFilePut"+p.PROTO))
        with self.assertRaisesRegex(RuntimeError,"already patched"):
            p.patch_source(p.patch_source(original))

    def test_modifies_one_sardine_class_and_never_local_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "smali_classes2" / p.CLASS_PATH
            target.parent.mkdir(parents=True)
            target.write_text(self.sample())
            db = root / "smali/LocalProgressDatabase.smali"
            db.parent.mkdir(parents=True)
            db.write_text("LOCAL DATABASE UNCHANGED")
            player = root / "smali/PlayerActivity.smali"
            player.write_text("PLAYER UNCHANGED")
            report = root / "reports" / "resume-local.json"
            result = p.apply(root,report)
            self.assertEqual(result["status"],"PASS")
            self.assertFalse(result["modified_local_database"])
            self.assertEqual(db.read_text(),"LOCAL DATABASE UNCHANGED")
            self.assertEqual(player.read_text(),"PLAYER UNCHANGED")
            self.assertIn("->novaPutOriginalFile",target.read_text())
            self.assertEqual(json.loads(report.read_text())["status"],"PASS")

if __name__ == "__main__":
    unittest.main()
