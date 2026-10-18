import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from webdav_connect_retry_patch import apply, _patch_outer, _patch_inner

OUTER = '''.class public Lcom/archos/filecorelibrary/StreamOverHttp;
.super Ljava/lang/Object;
.field private final mUri:Landroid/net/Uri;
'''
INNER = '''.class Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;
.super Ljava/lang/Object;
.field final synthetic this$0:Lcom/archos/filecorelibrary/StreamOverHttp;
.method private isCancelled()Z
 .locals 1
 return v0
.end method
.method private takeInput()Ljava/io/InputStream;
 .locals 1
 return-object v0
.end method
.method private closeInput(Ljava/io/InputStream;)V
 .locals 0
 return-void
.end method
.method private openInputStream()V
 .locals 0
 return-void
.end method
.method public run()V
 .locals 0
 invoke-direct {p0}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->openInputStream()V
 return-void
.end method
'''

class TestWebdavConnectRetryPatch(unittest.TestCase):
    def test_bounded_webdav_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'smali_classes4/com/archos/filecorelibrary'
            folder.mkdir(parents=True)
            (folder / 'StreamOverHttp.smali').write_text(OUTER)
            (folder / 'StreamOverHttp$HttpSession.smali').write_text(INNER)
            result = apply(root, root / 'report.json')
            inner = (folder / 'StreamOverHttp$HttpSession.smali').read_text()
            outer = (folder / 'StreamOverHttp.smali').read_text()
            self.assertEqual(result['max_extra_retries'], 3)
            self.assertIn('const/4 v2, 0x3', inner)
            self.assertIn('->novaWebdavOrigin()Z', inner)
            self.assertIn('const-string v1, "webdav"', outer)
            self.assertIn('->isCancelled()Z', inner)
            self.assertEqual(inner.count('.method private openInputStream()V'), 1)
            self.assertIn('novaOpenInputStreamOnce()V', inner)
            self.assertTrue((root / 'report.json').exists())

    def test_fails_closed_on_missing_method(self):
        with self.assertRaises(RuntimeError):
            _patch_inner(INNER.replace('openInputStream()V', 'openStream()V'))
        with self.assertRaises(RuntimeError):
            _patch_outer(OUTER.replace('mUri:Landroid/net/Uri;', 'mUri:Ljava/lang/String;'))

    def test_no_double_patch(self):
        with self.assertRaises(RuntimeError):
            _patch_inner(_patch_inner(INNER))

if __name__ == '__main__':
    unittest.main()
