import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from webdav_midstream_resume_patch import (
    apply, patch_outer, patch_session, patch_activity, patch_listener
)

OUTER = """.class public Lcom/archos/filecorelibrary/StreamOverHttp;
.field private final mUri:Landroid/net/Uri;
.method public novaWebdavOrigin()Z
    .locals 1
    return v0
.end method
.method static bufferResponseInput(Ljava/io/InputStream;JI)Ljava/io/InputStream;
    .locals 1
    return-object v0
.end method
.method private copyStream(Ljava/io/InputStream;Ljava/io/OutputStream;[BJLcom/archos/filecorelibrary/StreamOverHttp$HttpSession;)V
    .locals 1
    return-void
.end method
"""
SESSION = """.class Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;
.field private supersedableMediaRequest:Z
.field private requestedStart:J
.field private upstreamBufferSize:I
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
.method private readOptions()Lcom/archos/filecorelibrary/ReadOptions;
    .locals 1
    return-object v0
.end method
.method private publishInput(Ljava/io/InputStream;)V
    .locals 0
    return-void
.end method
"""
ACTIVITY = """.class public Lcom/archos/mediacenter/video/player/PlayerActivity;
.field private mUri:Landroid/net/Uri;
"""
LISTENER = """.class public Lcom/archos/mediacenter/video/player/PlayerActivity$PlayerListener;
.field final synthetic this$0:Lcom/archos/mediacenter/video/player/PlayerActivity;
.method public onError(IILjava/lang/String;)Z
    .locals 1
    const/4 v0, 0x0
    return v0
.end method
"""


class MidstreamPatchTests(unittest.TestCase):
    def test_recover_at_exact_delivered_offset_and_original_nonwebdav(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = {
                "com/archos/filecorelibrary/StreamOverHttp.smali": OUTER,
                "com/archos/filecorelibrary/StreamOverHttp$HttpSession.smali": SESSION,
                "com/archos/mediacenter/video/player/PlayerActivity.smali": ACTIVITY,
                "com/archos/mediacenter/video/player/PlayerActivity$PlayerListener.smali": LISTENER,
            }
            for name, content in entries.items():
                f = root / "smali_classes4" / name
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(content)
            report = root / "report.json"
            result = apply(root, report)
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(report.is_file())
            outer = (root / "smali_classes4/com/archos/filecorelibrary/StreamOverHttp.smali").read_text()
            inner = (root / "smali_classes4/com/archos/filecorelibrary/StreamOverHttp$HttpSession.smali").read_text()
            listener = (root / "smali_classes4/com/archos/mediacenter/video/player/PlayerActivity$PlayerListener.smali").read_text()
            self.assertIn("novaCopyStreamOriginal(", outer)
            self.assertIn("novaCopyStreamRecovering(", outer)
            self.assertIn("->novaRequestedStart()J", outer)
            self.assertIn("add-long/2addr v3, v7", outer)
            self.assertIn("sub-long/2addr p4, v7", outer)
            self.assertIn('const-wide/16 v7, 0x1f4', outer)
            self.assertIn("const/4 v0, 0x3", outer)
            self.assertIn("NOVA_WEBDAV_MIDSTREAM", outer)
            self.assertIn("->publishInput(Ljava/io/InputStream;)V", inner)
            self.assertIn("->novaFinishWebdavFileError(I)Z", listener)
            self.assertIn("move/from16 v1, p1", listener)
            self.assertEqual(listener.count(".method public onError"), 1)

    def test_fail_closed_when_anchor_changes(self):
        with self.assertRaises(RuntimeError):
            patch_outer(OUTER.replace("copyStream(", "streamBytes("))
        with self.assertRaises(RuntimeError):
            patch_session(SESSION.replace("requestedStart:J", "requestedOffset:J"))
        with self.assertRaises(RuntimeError):
            patch_activity(ACTIVITY.replace("mUri:Landroid/net/Uri;", "mUri:Ljava/lang/String;"))
        with self.assertRaises(RuntimeError):
            patch_listener(LISTENER.replace("onError(IILjava/lang/String;)Z", "onError(II)Z"))

    def test_no_duplicate_mutations(self):
        for patch, sample in [(patch_outer, OUTER), (patch_session, SESSION),
                              (patch_activity, ACTIVITY), (patch_listener, LISTENER)]:
            with self.assertRaises(RuntimeError):
                patch(patch(sample))


if __name__ == "__main__":
    unittest.main()
