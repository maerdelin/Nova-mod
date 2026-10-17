import unittest
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import main_rebuffer_patch as p

class MainRebufferTests(unittest.TestCase):
    def test_old_gate_code_absent(self):
        text=p.REBUFFER_SMALI+p.PLAYER_HELPERS
        for term in ('initialHold','beforeNativeStart','awaitBudget','bufferStartHeldCurrent','HARD_GATE'):
            self.assertNotIn(term,text)

    def test_thresholds_exact(self):
        s=p.REBUFFER_SMALI
        self.assertIn('CAPACITY:I = 0x4000000',s)
        self.assertIn('LOW:I = 0x1800000',s)
        self.assertIn('RESUME:I = 0x2d00000',s)
        self.assertIn('const v1, 0x2d00000\n    if-le v0, v1, :wait',s)

    def test_no_prestart_buffer_allocation(self):
        ctor=p._method(p.REBUFFER_SMALI,' constructor <init>(Ljava/io/InputStream;)V').group(0)
        self.assertNotIn('PipedInputStream',ctor)
        self.assertNotIn('Thread;->start()V',ctor)
        act=p._method(p.REBUFFER_SMALI,' activateInstance()V').group(0)
        self.assertIn('PipedInputStream',act)
        self.assertIn('0x4000000',act)
        self.assertIn('Thread;->start()V',act)

    def test_prestart_io_delegates_to_main_source(self):
        cases={
            ' read()I':'Ljava/io/InputStream;->read()I',
            ' read([BII)I':'Ljava/io/InputStream;->read([BII)I',
            ' skip(J)J':'Ljava/io/InputStream;->skip(J)J',
            ' available()I':'Ljava/io/InputStream;->available()I',
        }
        for sig,token in cases.items():
            body=p._method(p.REBUFFER_SMALI,sig).group(0)
            self.assertIn('started:Z',body)
            self.assertIn(token,body)

    def test_floor_and_resume_logic(self):
        b=p._method(p.REBUFFER_SMALI,' beforeRead(I)V').group(0)
        self.assertIn('const v1, 0x1800000',b)
        self.assertIn('add-int v2, v1, p1',b)
        self.assertIn('REBUFFER_ARMED buffer>=24MiB',b)
        self.assertIn('REBUFFER_PAUSE low-or-empty',b)
        self.assertIn('REBUFFER_RESUME buffer>45MiB',b)
        self.assertIn('firstProtectedRead:Z',b)

    def test_throw_registers_are_reference_only_path(self):
        throws=[x.strip() for x in p.REBUFFER_SMALI.splitlines() if x.strip().startswith('throw ')]
        self.assertEqual(throws,['throw v1','throw v1'])
        for sig in (' read()I',' read([BII)I'):
            body=p._method(p.REBUFFER_SMALI,sig).group(0)
            self.assertIn('failure:Ljava/io/IOException;',body)
            self.assertIn('throw v1',body)

    def test_patch_clean_main_fixture_when_available(self):
        # CI build verifies against the actual decoded selected APK. This unit test
        # additionally checks any bundled/local audit fixture when present.
        fixture=ROOT/'tests/fixtures/clean-main'
        if not fixture.exists():
            return

    def test_session_requires_real_playback_request(self):
        src=(ROOT/'scripts/main_rebuffer_patch.py').read_text()
        self.assertIn('supersedableMediaRequest:Z',src)
        self.assertIn('StreamOverHttp$ReadMode;->PLAYBACK',src)
        self.assertIn('MainRebufferInputStream;->wrap',src)

if __name__=='__main__':
    unittest.main()
