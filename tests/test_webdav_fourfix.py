"""Production-policy JVM tests, exact smali hooks and compiled C lifetime checks."""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import webdav_fourfix_patch as patch
import webdav_p012_patch as p012
import webdav_connect_retry_patch as legacy
import iso_patch

class FourFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='nova-fourfix-')
        cls.work=Path(cls.temp.name);cls.classes=cls.work/'classes';cls.classes.mkdir()
        sources=list((ROOT/'parallel_range4/src').rglob('*.java'))+[ROOT/'tests/java/android/util/Log.java',ROOT/'tests/java/com/archos/filecorelibrary/FourFixHarness.java']
        subprocess.run(['javac','-source','8','-target','8','-d',str(cls.classes)]+list(map(str,sources)),check=True,timeout=30)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def java(self,case):
        r=subprocess.run(['java','-Xmx384m','-cp',str(self.classes),'com.archos.filecorelibrary.FourFixHarness',case],capture_output=True,text=True,timeout=30)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('PASS ',r.stdout);print(r.stdout.strip())
    def test_raw_encoded_chinese_bracket_filenames(self):self.java('paths')
    def test_concurrent_sidecar_admission_and_cooldown(self):self.java('concurrent')
    def test_backend_open_same_offset_bounded_retry(self):self.java('retry')
    def test_direct_and_redirected_denial_boundaries(self):self.java('denied')
    def test_four_lanes_obey_bounded_refresh_budget(self):self.java('refresh')
    def test_all_four_expired_lanes_recover_with_64bit_offsets(self):self.java('alllanes')
    def test_iso_lifecycle_120_races(self):self.java('guard')
    def test_native_join_is_not_on_releasing_thread(self):self.java('nonblocking')
    def test_old_wrapper_becomes_single_invocation(self):
        src=legacy.INNER_HELPERS
        changed=patch.session_text(src)
        methods=[m.group() for m in patch.METHOD.finditer(changed) if ' openInputStream()V' in m.group().splitlines()[0]]
        self.assertEqual(len(methods),1);body=methods[0]
        self.assertEqual(body.count('->novaOpenInputStreamOnce()V'),1)
        self.assertNotIn('goto ',body);self.assertNotIn('.catch ',body)
        self.assertNotIn('readRequest()',body)
        with self.assertRaises(RuntimeError):patch.session_text(changed)
    def test_actual_iso_generator_accepts_owned_resolve(self):
        changed=patch.proxy_text(iso_patch.PROXY_SMALI)
        self.assertIn('resolveOwned(Landroid/net/Uri;Ljava/lang/Object;)',changed)
        self.assertIn('attachSource(',changed);self.assertIn('attachNative(',changed)
        self.assertIn('nativeCloseGeneration(J)V',changed)
        self.assertIn('getEncodedUri(',changed)
        with self.assertRaises(RuntimeError):patch.proxy_text(changed)
    def test_method_declaration_rename_ignores_metadata_occurrences(self):
        name = 'resolve(Landroid/net/Uri;)Landroid/net/Uri;'
        comment = '    # method metadata: ' + name + '\n'
        source = iso_patch.PROXY_SMALI.replace('    if-eqz p0, :return_original',
                  comment + '    if-eqz p0, :return_original', 1)
        changed = patch.proxy_text(source)
        self.assertIn(comment, changed)
        self.assertIn('.method public static declared-synchronized resolveOwned(', changed)
        self.assertNotIn('.method public static declared-synchronized ' + name, changed)
        with self.assertRaises(RuntimeError):
            patch.rename_declaration('.method public wrong()V\n.end method', name, 'new()V', 'guard')

    def test_full_c_generation_patch_preserves_read_and_title_logic(self):
        before=p012.iso_text((ROOT/'iso/nova_iso.c').read_text())
        after=patch.iso_text(before)
        for op in ('bd_seek(', 'bd_select_title(', 'fetch_range_playback(', 'CACHE_BYTES', 'nova_iso_source_size='):
            self.assertEqual(before.count(op),after.count(op),op)
        self.assertIn('nativeCloseGeneration',after)
        self.assertIn('&nova_iso_generation=',after)
        with self.assertRaises(RuntimeError):patch.iso_text(after)
    def test_compiled_native_old_generation_cannot_close_new(self):
        c=r'''
#include <stdint.h>
#include <inttypes.h>
#include <stdlib.h>
#include <assert.h>
#include <pthread.h>
#define JNIEXPORT
#define JNICALL
#define LOGI(...) ((void)0)
typedef void JNIEnv;
typedef void *jclass;
typedef int64_t jlong;
typedef struct {uint64_t generation;} iso_session;
static pthread_mutex_t g_lock=PTHREAD_MUTEX_INITIALIZER;
static iso_session *g_session;
static int destroyed;
static void session_destroy(iso_session *s){destroyed++;free(s);}
'''+patch.NATIVE_CLOSE+r'''
int main(void) {
  g_session=calloc(1,sizeof(*g_session));g_session->generation=2;
  Java_com_archos_mediacenter_video_player_BlurayIsoProxy_nativeCloseGeneration(NULL,NULL,1);
  assert(g_session && g_session->generation==2 && destroyed==0);
  Java_com_archos_mediacenter_video_player_BlurayIsoProxy_nativeCloseGeneration(NULL,NULL,2);
  assert(!g_session && destroyed==1);
  Java_com_archos_mediacenter_video_player_BlurayIsoProxy_nativeCloseGeneration(NULL,NULL,2);
  assert(destroyed==1);
  return 0;
}
'''
        f=self.work/'generation.c';f.write_text(c);exe=self.work/'generation'
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pthread',str(f),'-o',str(exe)],check=True,timeout=20)
        subprocess.run([str(exe)],check=True,timeout=10)
    def test_all_helpers_required_in_dex_gate(self):
        import webdav_parallel4_dex as dex
        self.assertEqual(dex.REQUIRED,{p.name for p in (ROOT/'parallel_range4/src').rglob('*.java')})
        self.assertIn('NovaWebdavOpenPolicy.java',dex.REQUIRED)
        self.assertIn('NovaIsoSessionGuard.java',dex.REQUIRED)

if __name__=='__main__':unittest.main()
