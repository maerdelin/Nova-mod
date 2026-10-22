"""Real Java idle policy and compiled ISO timeline contract, not a device playback claim."""
from pathlib import Path
import re, subprocess, sys, tempfile, unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import iso_seek_ui_patch as patch
import webdav_safety_patch as four

class SeekUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='seek-ui-');cls.work=Path(cls.tmp.name)
        cls.classes=cls.work/'classes';cls.classes.mkdir()
        sources=[ROOT/'playback_ui/src/com/archos/filecorelibrary/NovaControlbarAutoHide.java',ROOT/'tests/java/com/archos/filecorelibrary/SeekUiHarness.java']+list((ROOT/'tests/java/android').rglob('*.java'))
        subprocess.run(['javac','-source','8','-target','8','-d',str(cls.classes)]+list(map(str,sources)),check=True,timeout=30)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def java(self,name):
        r=subprocess.run(['java','-cp',str(self.classes),'com.archos/filecorelibrary/SeekUiHarness'.replace('/','.'),name],capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('PASS UI',r.stdout);print(r.stdout.strip())
    def test_idle_exact_deadline(self):self.java('steady')
    def test_late_playback_state_cannot_lose_hide(self):self.java('delayed')
    def test_key_hold_and_release(self):self.java('holding')
    def test_drag_and_release(self):self.java('dragging')
    def test_intentional_pause_is_preserved(self):self.java('paused')
    def test_menu_guard_then_close(self):self.java('menu')
    def test_new_input_restarts_deadline(self):self.java('rearm')
    def test_cancel_drops_stale_callback(self):self.java('cancel')
    def test_stop_does_not_retain_owner(self):self.java('stop')
    def test_existing_explicit_pause_timeout(self):self.java('explicit')
    def test_ten_thousand_arms_bounded_callback(self):self.java('bounded')
    def test_controller_owners_are_independent(self):self.java('owners')
    def test_explicit_zero_timeout(self):self.java('zero')
    def test_policy_cannot_mutate_playback(self):
        code=(ROOT/'playback_ui/src/com/archos/filecorelibrary/NovaControlbarAutoHide.java').read_text()
        for call in ('seekTo(','.start(','.pause(','.stop('):self.assertNotIn(call,code)
        self.assertIn('novaHideControls()',code)
    def test_compiled_native_duration_and_seek_unit_contract(self):
        prefix=r'''
#include <stdint.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <assert.h>
#define ETYPE_MPEG_TS 18
#define AVIO_SEEKABLE_NORMAL 1
#define AV_NOPTS_VALUE INT64_MIN
#define serprintf(...) ((void)0)
typedef struct {int seekable;} IO;
typedef struct {IO *pb; int64_t start_time, duration;} Format;
typedef struct {int duration, start_time, size_known, nova_iso_time_mode;Format *fmt;} FF;
typedef struct {int etype;uint64_t size;struct {char *url;}src;char *src_query;int duration,no_duration;int rebuffer_capacity_bytes;} Stream;
'''
        main=r'''
static void activate(Stream *s, FF *ff_p) {
ACTIVATE
}
int main(void) {
 char url[]="http://127.0.0.1:36383/main.m2ts";
 char q[]="?mpegts&nova_iso=1&nova_iso_duration_us=7023049355&nova_iso_clip_count=1&nova_iso_title_size=87096612864&nova_iso_generation=1";
 assert(nova_iso_timeline_us(url,q,87096612864ULL)==7023049355LL);
 IO io={1};Format fmt={&io,11650700,0};FF f={0,11650,1,0,&fmt};Stream s={18,87096612864ULL,{url},q,0,1,134217728};
 activate(&s,&f);
 assert(s.duration==7023049 && f.duration==7023049 && !s.no_duration && f.nova_iso_time_mode==1);
 assert(fmt.duration==7023049355LL && s.rebuffer_capacity_bytes==134217728);
 int64_t targetUs=((int64_t)5000+f.start_time)*1000000/1000;
 assert(targetUs==16650000LL);assert(targetUs-(int64_t)f.start_time*1000==5000000LL);
 int64_t backwardUs=((int64_t)15000+f.start_time)*1000000/1000;
 assert(backwardUs-(int64_t)f.start_time*1000==15000000LL);
 printf("ISO_TIMELINE durationMs=%d shortStepMs=5000 targetUs=%lld capacityUnchanged=%d\n",s.duration,(long long)targetUs,s.rebuffer_capacity_bytes);
 char variant[512];
 const char *bad[]={"?nova_iso=1&nova_iso_duration_us=7023049355&nova_iso_clip_count=2&nova_iso_title_size=87096612864&nova_iso_generation=1", "?nova_iso=1&nova_iso_duration_us=18446744073709551616&nova_iso_clip_count=1&nova_iso_title_size=87096612864&nova_iso_generation=1", "?nova_iso=1&nova_iso_duration_us=7023049355&nova_iso_clip_count=1&nova_iso_title_size=87096612864&nova_iso_generation=0", "?nova_iso=1&nova_iso_duration_us=7023049355&nova_iso_clip_count=1&nova_iso_title_size=87096612864"};
 for(unsigned i=0;i<sizeof(bad)/sizeof(*bad);i++)assert(nova_iso_timeline_us(url,bad[i],s.size)==0);
 snprintf(variant,sizeof(variant),"%s&nova_iso=1",q);assert(!nova_iso_timeline_us(url,variant,s.size));
 snprintf(variant,sizeof(variant),"%s&nova_iso_duration_us=10",q);assert(!nova_iso_timeline_us(url,variant,s.size));
 assert(!nova_iso_timeline_us("http://example.com:36383/main.m2ts",q,s.size));
 assert(!nova_iso_timeline_us("http://127.0.0.1:65536/main.m2ts",q,s.size));
 assert(!nova_iso_timeline_us("http://127.0.0.1:36383/other.m2ts",q,s.size));
 assert(!nova_iso_timeline_us(url,q,s.size+1));
 f.duration=0;f.nova_iso_time_mode=0;s.duration=0;s.no_duration=1;fmt.start_time=AV_NOPTS_VALUE;
 activate(&s,&f);assert(s.no_duration==1&&s.duration==0&&f.nova_iso_time_mode==0);
 fmt.start_time=11650700;io.seekable=0;activate(&s,&f);assert(s.no_duration==1);
 io.seekable=1;s.etype=99;activate(&s,&f);assert(s.no_duration==1);
 s.etype=18;s.src_query=(char*)bad[0];activate(&s,&f);assert(s.no_duration==1);
 puts("PASS C ISO single-clip metadata, units, bounds, unchanged buffer and explicit fallbacks");
 return 0;
}
'''.replace('ACTIVATE',patch.C_ACTIVATE)
        c=self.work/'iso.c';c.write_text(prefix+patch.C_HELPERS+main);exe=self.work/'iso'
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],check=True,timeout=20)
        r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10);self.assertEqual(r.returncode,0,r.stdout+r.stderr);print(r.stdout)
    def test_iso_metadata_preserves_payload_and_lifecycle(self):
        before=four.iso_text((ROOT/'iso/nova_iso.c').read_text())
        after=patch.iso_text(before)
        for token in ('bd_seek(', 'bd_read(', 'nativeCloseGeneration','fetch_range_playback(', 'CACHE_BYTES'):
            self.assertEqual(before.count(token),after.count(token))
        self.assertIn('nova_iso_clip_count',after);self.assertIn('nova_iso_title_size',after)
        with self.assertRaises(RuntimeError):patch.iso_text(after)
    def test_native_transform_guards_and_preserves_buffer_block(self):
        before='NOVA_RAW_FIXED128_POLICY:\n\tint\t\tstart_time;\nstatic int _open( STREAM *s, int buffer_size, int flags )\n{\n KEEP_BUFFER_ARITHMETIC\n\ts->parser_open = 1;\n}\n\t\tnew_pos = ((INT64)time + ff_p->start_time) * AV_TIME_BASE / 1000;'
        after=patch.native_text(before)
        self.assertEqual(after.count('KEEP_BUFFER_ARITHMETIC'),1)
        self.assertLess(after.index('KEEP_BUFFER_ARITHMETIC'),after.index('NOVA_ISO_TIMELINE_READY'))
        self.assertIn('NOVA_ISO_TIME_SEEK',after)
        with self.assertRaises(RuntimeError):patch.native_text(after)
        with self.assertRaises(RuntimeError):patch.native_text('wrong input')
    def test_controller_patch_is_transactional_on_missing_listener(self):
        # Actual APK assembly also runs this patch in the strict roundtrip gate.
        with tempfile.TemporaryDirectory() as tmp:
            r=Path(tmp);p=r/'smali/com/archos/mediacenter/video/player/PlayerController.smali';p.parent.mkdir(parents=True);p.write_text('unmatched class')
            with self.assertRaises(Exception):patch.apply(r)
            self.assertEqual(p.read_text(),'unmatched class')
if __name__=='__main__':unittest.main()
