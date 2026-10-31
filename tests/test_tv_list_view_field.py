"""Regression for actual 6.6.2 TV WebDAV list-mode field mismatch."""
import copy
import json
import sys
import tempfile
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import granular as g


class TvListViewFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        patch=json.loads((ROOT/'patches/v982-granular.json').read_text())
        found=[m for m in patch['methods']
               if (m['class'],m['method'])==(g.TV_LIST_CLASS,g.TV_LIST_METHOD)]
        assert len(found)==1, 'historical patch method identity changed'
        cls.rule=found[0]

    def test_real_hunk_migrates_exactly_one_injected_field(self):
        old=copy.deepcopy(self.rule['hunks'])
        new=g.port_v66_tv_list_view(self.rule,old)
        self.assertEqual(sum(x.count(g.TV_VIEW_OLD) for h in old for x in h['after']),1)
        self.assertEqual(sum(x.count(g.TV_VIEW_NEW) for h in new for x in h['after']),1)
        self.assertNotIn(g.TV_VIEW_OLD,str(new))
        self.assertEqual(self.rule['hunks'],old)
        for a,b in zip(old,new):
            for key in ('before','after','left','right','after_left','after_right'):
                self.assertEqual([s.replace(g.TV_VIEW_OLD,g.TV_VIEW_NEW) for s in a[key]],b[key])

    def test_unrelated_presenter_left_untouched(self):
        rule=dict(self.rule,**{'class':'LUnrelated;'})
        self.assertIs(g.port_v66_tv_list_view(rule,self.rule['hunks']),self.rule['hunks'])

    def test_deleted_or_duplicate_field_fails_closed(self):
        for replacement in ('Lqx0;->missing:Landroid/view/View;',g.TV_VIEW_OLD+g.TV_VIEW_OLD):
            broken=copy.deepcopy(self.rule['hunks'])
            for h in broken:
                h['after']=[s.replace(g.TV_VIEW_OLD,replacement) for s in h['after']]
            with self.assertRaisesRegex(g.Conflict,'legacy field count'):
                g.port_v66_tv_list_view(self.rule,broken)

    def create_fake_decoded(self,root,ref,declared=True):
        cls=root/('smali/'+g.TV_LIST_CLASS[1:-1]+'.smali')
        cls.parent.mkdir(parents=True,exist_ok=True)
        cls.write_text('.class public '+g.TV_LIST_CLASS+'\n.super Ljava/lang/Object;\n'
                       '.method public '+g.TV_LIST_METHOD+'\n.locals 4\n'
                       'iget-object v3, p1, '+ref+'\nreturn-void\n.end method\n')
        holder=root/'smali/px0.smali'
        holder.write_text('.class public Lpx0;\n.super Ljava/lang/Object;\n'+
                          ('.field public view:Landroid/view/View;\n' if declared else ''))

    def test_binary_roundtrip_audit_rejects_original_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.create_fake_decoded(root,g.TV_VIEW_NEW)
            self.assertEqual(g.audit_tv_list_view(root)['status'],'PASS')
            self.create_fake_decoded(root,g.TV_VIEW_OLD)
            with self.assertRaisesRegex(g.Conflict,'stale/ambiguous'):
                g.audit_tv_list_view(root)
            self.create_fake_decoded(root,g.TV_VIEW_NEW,declared=False)
            with self.assertRaisesRegex(g.Conflict,'target px0.view'):
                g.audit_tv_list_view(root)

if __name__=='__main__':
    unittest.main()
