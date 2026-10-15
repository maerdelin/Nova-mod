"""Resolver regressions and granular delivery invariants.
The retired exact-SHA overlay guard is no longer a production pipeline step.
"""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import check_upstream as u
ROOT = Path(__file__).resolve().parents[1]

class UpstreamTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.root = Path(t.name); self.apk = self.root/'official.apk'; self.meta = self.root/'upstream.json'
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as z:
            for n in ('AndroidManifest.xml','classes.dex','resources.arsc'):z.writestr(n, b'test fixture')
        self.payload = buffer.getvalue()
        self.release = {'id':700,'tag_name':'v6.7','draft':False,'prerelease':False,'published_at':'2026-10-15T00:00:00Z'}
        self.asset = {'id':701,'name':'nova-universal-release.apk','state':'uploaded','size':len(self.payload),
          'digest':'sha256:'+hashlib.sha256(self.payload).hexdigest(),
          'browser_download_url':'https://github.com/nova-video-player/aos-AVP/releases/download/v6.7/nova-universal-release.apk'}
    def fetch(self, url):
        if url == u.LATEST_URL:return self.release
        return [self.asset]
    def downloader(self,url,path):path.write_bytes(self.payload)
    def download(self):return u.download_latest(self.apk,self.meta,fetch_json=self.fetch,downloader=self.downloader)
    def workflow(self):return (ROOT/'.github/workflows/nova-video-player-mod.yml').read_text()
    def test_future_tags_have_no_version_format_gate(self):
        for tag in ('v6.7','v6.7.0','v7.0','7.2','official-stable'):
            self.release['tag_name']=tag
            self.assertEqual(u.resolve_latest(self.fetch)['tag'],tag)
    def test_draft_rejected(self):
        self.release['draft']=True
        with self.assertRaises(u.UpstreamError):u.resolve_latest(self.fetch)
    def test_prerelease_rejected(self):
        self.release['prerelease']=True
        with self.assertRaises(u.UpstreamError):u.resolve_latest(self.fetch)
    def test_missing_asset_not_replaced_with_old_version(self):
        with self.assertRaises(u.UpstreamError):u.select_asset([])
    def test_ambiguous_universal_rejected(self):
        with self.assertRaises(u.UpstreamError):u.select_asset([self.asset,self.asset.copy()])
    def test_debug_universal_rejected(self):
        self.asset['name']='nova-universal-debug.apk'
        with self.assertRaises(u.UpstreamError):u.select_asset([self.asset])
    def test_foreign_url_rejected(self):
        self.asset['browser_download_url']='https://example.com/nova.apk'
        with self.assertRaises(u.UpstreamError):u.select_asset([self.asset])
    def test_unfinished_asset_rejected(self):
        self.asset['state']='new'
        with self.assertRaises(u.UpstreamError):u.select_asset([self.asset])
    def test_missing_digest_rejected(self):
        self.asset.pop('digest')
        with self.assertRaises(u.UpstreamError):u.select_asset([self.asset])
    def test_valid_input_used_and_rechecked(self):
        self.download();self.assertEqual(self.apk.read_bytes(),self.payload)
        self.assertEqual(u.load_selection(self.meta,self.apk)['status'],'DOWNLOADED_AND_VERIFIED')
        u.assert_current(self.apk,self.meta,fetch_json=self.fetch)
    def test_corruption_rejected(self):
        self.download();self.apk.write_bytes(b'corrupt')
        with self.assertRaises(u.UpstreamError):u.load_selection(self.meta,self.apk)
    def test_download_digest_failure_leaves_no_stale_apk(self):
        self.apk.write_bytes(b'old');self.asset['digest']='sha256:'+'0'*64
        with self.assertRaises(u.UpstreamError):self.download()
        self.assertFalse(self.apk.exists())
    def test_network_failure_leaves_no_stale_apk(self):
        self.apk.write_bytes(b'old')
        def fail(url):raise u.UpstreamError('offline')
        with self.assertRaises(u.UpstreamError):u.download_latest(self.apk,self.meta,fetch_json=fail)
        self.assertFalse(self.apk.exists())
    def test_changed_latest_blocks_publication(self):
        self.download();self.release['tag_name']='v6.8'
        with self.assertRaises(u.UpstreamError):u.assert_current(self.apk,self.meta,fetch_json=self.fetch)
    def test_replaced_asset_blocks_publication(self):
        self.download();self.asset['id']=702
        with self.assertRaises(u.UpstreamError):u.assert_current(self.apk,self.meta,fetch_json=self.fetch)
    def test_foreign_provenance_rejected(self):
        self.download();d=json.loads(self.meta.read_text());d['repository']='wrong/repo';self.meta.write_text(json.dumps(d))
        with self.assertRaises(u.UpstreamError):u.load_selection(self.meta,self.apk)
    def test_single_workflow_name(self):
        paths=list((ROOT/'.github/workflows').glob('*.yml'))
        self.assertEqual(len(paths),1);self.assertTrue(self.workflow().startswith('name: Nova Video Player mod\n'))
    def test_no_legacy_whole_apk_compatibility_gate(self):
        content=self.workflow()
        self.assertIn('granular_build.py --apk inputs/official.apk',content)
        self.assertNotIn('check_upstream.py guard',content)
        self.assertNotIn('build.py build inputs/official.apk',content)
        self.assertNotIn('/releases/download/v6.5.5',content)
    def test_sign_and_install_before_deliver(self):
        c=self.workflow()
        self.assertLess(c.index('apksigner'),c.index('scripts/smoke_install.py'))
        self.assertLess(c.index('scripts/smoke_install.py'),c.index('name: Upload installable APK'))
        self.assertLess(c.index('assert-current'),c.index('gh release create'))
    def test_only_final_apk_delivered(self):
        c=self.workflow()
        self.assertIn('dist/Nova_Video_Player_mod_SIGNED.apk',c)
        self.assertNotIn('path: audit/',c);self.assertNotIn('path: work/',c)
        self.assertNotIn('continue-on-error',c)
    def test_ci_branch_cannot_publish(self):
        self.assertIn("if: github.ref == 'refs/heads/main' && github.event_name != 'schedule'",self.workflow())
    def test_signing_key_never_uploaded(self):
        c=self.workflow();self.assertIn("trap 'rm -f \"$STORE\"' EXIT",c)
        self.assertIn('SIGNING_MODE=temporary-test-key',c);self.assertNotIn('path: $RUNNER_TEMP',c)

if __name__=='__main__':unittest.main()
