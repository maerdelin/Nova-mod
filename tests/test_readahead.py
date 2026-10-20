from pathlib import Path
import re,sys,subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import readahead_patch as patch

class AheadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.out=Path(cls.tmp.name)
        subprocess.run(['javac','-source','8','-target','8','-d',str(cls.out),str(ROOT/'tests/java/android/util/Log.java'),str(ROOT/'webdav_fixes/src/com/archos/filecorelibrary/NovaAheadInputStream.java'),str(ROOT/'tests/java/com/archos/filecorelibrary/AheadHarness.java')],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def harness(self,mode):
        r=subprocess.run(['java','-Xmx256m','-cp',str(self.out),'com.archos.filecorelibrary.AheadHarness',mode],capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);print(r.stdout)
    def test_pause_full_refill_exact_bytes(self):self.harness('pause')
    def test_error_drains_before_recovery(self):self.harness('failure')
    def test_early_eof_is_not_false_success(self):self.harness('early')
    def test_cancel_full_queue(self):self.harness('cancel-full')
    def test_cancel_blocked_source_and_consumer(self):self.harness('cancel-wait')
    def test_extent_and_tiny_metadata(self):self.harness('extent')
    def test_total_memory_admission(self):self.harness('budget')
    def test_stream_contract(self):self.harness('validation')
    def test_no_http_requests_or_player_dependency_in_fifo(self):
        s=(ROOT/'webdav_fixes/src/com/archos/filecorelibrary/NovaAheadInputStream.java').read_text()
        for token in ['java.net','openRange(','openConnection(','isPlaying(','Executor','copyRecovering(']:self.assertNotIn(token,s)
        self.assertEqual(s.count('source.read('),1)
    def fixture(self):
        return '''.class public Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;
.super Ljava/lang/Object;
.method private publishInput(Ljava/io/InputStream;)V
    .locals 2
    if-eqz p1, :no
    iput-object p1, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->is:Ljava/io/InputStream;
    :no
    return-void
.end method
.method public novaResumeUpstreamAt(J)Ljava/io/InputStream;
    .locals 4
    invoke-direct {p0, v0}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->publishInput(Ljava/io/InputStream;)V
    return-object v0
.end method
'''
    def test_resumed_offset_and_owned_return(self):
        s=patch.session_text(self.fixture())
        self.assertIn('invoke-direct {p0, v0, p1, p2}',s)
        self.assertIn('iget-object v0, p0, '+patch.SESSION+'->is:Ljava/io/InputStream;',s)
        self.assertIn('novaMediaResumeEligible()Z',s)
        self.assertIn('requestedEnd:J',s)
    def test_duplicate_patch_rejected(self):
        with self.assertRaises(RuntimeError):patch.session_text(patch.session_text(self.fixture()))
    def test_missing_publication_rejected(self):
        with self.assertRaises(RuntimeError):patch.session_text(self.fixture().replace('publishInput','otherInput'))
if __name__=='__main__':unittest.main()
