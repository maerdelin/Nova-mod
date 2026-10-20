from pathlib import Path
import sys, unittest, tempfile, zipfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import main_transport_audit as audit
import webdav_midstream_resume_patch as main
import webdav_connect_retry_patch as connect
import webdav_safety_patch as safety

class MainTransportTests(unittest.TestCase):
    def test_main_source_files_are_byte_identical(self):audit.verify_source_baseline()
    def test_main_copy_is_not_replaced(self):
        s=(ROOT/'scripts/iso_finalize.py').read_text()
        self.assertIn('main_transport_audit.capture(decoded)',s)
        self.assertIn('main_transport_audit.verify(assembled, transport',s)
        self.assertNotIn('copyRecovering(',s)
    def fixture(self,root):
        folder=root/'smali/com/archos/filecorelibrary';folder.mkdir(parents=True)
        texts={audit.FILES[0]:'.class public Lcom/archos/filecorelibrary/StreamOverHttp;\n.super Ljava/lang/Object;\n'+main.OUTER_METHODS,
               audit.FILES[1]:'.class public Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;\n.super Ljava/lang/Object;\n'+main.SESSION_METHODS+connect.INNER_HELPERS}
        for name,content in texts.items():(folder/name).write_text(content)
        (folder/audit.FILES[1]).write_text(safety.session_text(texts[audit.FILES[1]]))
        return folder,texts
    def test_only_parse_once_difference_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,before=self.fixture(root);audit.verify(root,before)
    def test_copy_instruction_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,before=self.fixture(root);p=folder/audit.FILES[0]
            p.write_text(p.read_text().replace('const/4 v5, 0x0','const/4 v5, 0x1',1))
            with self.assertRaises(RuntimeError):audit.verify(root,before)
    def test_session_residue_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,before=self.fixture(root);p=folder/audit.FILES[1]
            p.write_text(p.read_text()+'\n.field private extra:I\n')
            with self.assertRaises(RuntimeError):audit.verify(root,before)
    def test_native_publisher_token_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.apk'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('classes.dex',b'dex\nnone');z.writestr('lib/x86/libavos.so',b'\x7fELF'+audit.BANNED[-2])
            with self.assertRaises(RuntimeError):audit.verify_apk_absence(path)
    def test_replacement_helper_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.apk'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('classes.dex',b'dex\n'+audit.BANNED[1]);z.writestr('lib/x86/libavos.so',b'\x7fELF')
            with self.assertRaises(RuntimeError):audit.verify_apk_absence(path)
    def test_error_classifier_is_not_a_downloader(self):
        s=(ROOT/'webdav_fixes/src/com/archos/filecorelibrary/NovaWebdavErrors.java').read_text()
        for term in ['InputStream','OutputStream','Executor','openRange','copyRecovering','new Thread']:
            self.assertNotIn(term,s)
if __name__=='__main__':unittest.main()
