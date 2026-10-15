import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import granular as g

class GranularTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.old=self.root/'old';self.new=self.root/'new'
        self.old.mkdir();(self.old/'smali').mkdir();(self.old/'res/values').mkdir(parents=True);(self.old/'res/layout').mkdir()
        (self.old/'res/values/public.xml').write_text('<resources><public type="id" name="target" id="0x7f010001"/><public type="id" name="other" id="0x7f010002"/></resources>')
        (self.old/'res/layout/item.xml').write_text('<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"><TextView android:id="@id/target" android:layout_width="10dp" android:layout_height="20dp"/></LinearLayout>')
        text='.class public LExample;\n.super Ljava/lang/Object;\n.field private final count:I\n'
        text+='\n.method public read()I\n.locals 2\nconst v0, 0x7f010001\n'
        text+='\n'.join('const/16 v1, '+hex(i) for i in range(40))+'\n'
        text+='if-eqz v0, :cond_0\nconst/4 v1, 0x1\n:cond_0\nreturn v1\n.end method\n'
        text+='\n.method public other()I\n.locals 1\nconst/4 v0, 0x2\nreturn v0\n.end method\n'
        (self.old/'smali/Example.smali').write_text(text)
        shutil.copytree(self.old,self.new)
        q=self.new/'smali/Example.smali';q.write_text(text.replace('const/16 v1, 0x14','const/16 v1, 0x7b').replace('.field private final count:I','.field public count:I'))
        q=self.new/'res/layout/item.xml';q.write_text(q.read_text().replace('10dp','15dp'))
        with contextlib.redirect_stdout(io.StringIO()):self.patch=g.extract(self.old,self.new,self.root/'patch.json')
    def snapshot(self):return {str(p.relative_to(self.old)):p.read_bytes() for p in self.old.rglob('*') if p.is_file()}
    def apply(self):return g.apply(self.old,self.patch)
    def verify(self):
        with contextlib.redirect_stdout(io.StringIO()):return g.verify(self.new,self.old)
    def test_exact_baseline_matches_target(self):self.apply();self.assertEqual(self.verify()['status'],'PASS')
    def test_no_whole_file_or_module_replacements(self):
        self.assertFalse(self.patch['whole_file_replacements']);self.assertEqual(len(self.patch['methods']),1)
        h=self.patch['methods'][0]['hunks'];self.assertEqual(len(h),1);self.assertEqual(len(h[0]['before']),1)
    def test_unrelated_method_update_preserved(self):
        p=self.old/'smali/Example.smali';p.write_text(p.read_text().replace('const/4 v0, 0x2','const/4 v0, 0x3'))
        self.apply();self.assertIn('const/4 v0, 0x3',p.read_text())
    def test_same_method_unrelated_instruction_preserved(self):
        p=self.old/'smali/Example.smali';p.write_text(p.read_text().replace('const/16 v1, 0x1\n','const/16 v1, 0x63\n'))
        self.apply();self.assertIn('const/16 v1, 0x63',p.read_text());self.assertIn('const/16 v1, 0x7b',p.read_text())
    def test_unrelated_new_class_preserved(self):
        p=self.old/'smali/New.smali';p.write_text('.class public LNew;\n.super Ljava/lang/Object;\n');before=p.read_bytes()
        self.apply();self.assertEqual(p.read_bytes(),before)
    def test_relocated_dex_class(self):
        p=self.old/'smali_classes3';p.mkdir();shutil.move(self.old/'smali/Example.smali',p/'Example.smali')
        self.apply();self.assertIn('const/16 v1, 0x7b',(p/'Example.smali').read_text())
    def test_resource_id_rebase(self):
        for p in (self.old/'res/values/public.xml',self.old/'smali/Example.smali'):
            p.write_text(p.read_text().replace('0x7f010001','0x7f220077'))
        self.apply();self.assertIn('0x7f220077',(self.old/'smali/Example.smali').read_text())
    def test_resource_symbol_in_patch_is_rebased(self):
        p=self.new/'smali/Example.smali';p.write_text(p.read_text().replace('0x7f010001','0x7f010002'))
        with contextlib.redirect_stdout(io.StringIO()):self.patch=g.extract(self.old,self.new,self.root/'patch2.json')
        for p in (self.old/'res/values/public.xml',self.old/'smali/Example.smali'):
            p.write_text(p.read_text().replace('0x7f010002','0x7f330055'))
        self.apply();self.assertIn('0x7f330055',(self.old/'smali/Example.smali').read_text())
    def test_label_rename_preserved(self):
        p=self.old/'smali/Example.smali';p.write_text(p.read_text().replace(':cond_0',':cond_45'))
        self.apply();self.assertIn(':cond_45',p.read_text());self.assertNotIn(':cond_0',p.read_text())
    def test_unrelated_xml_attribute_preserved(self):
        p=self.old/'res/layout/item.xml';p.write_text(p.read_text().replace('20dp','30dp'))
        self.apply();self.assertIn('30dp',p.read_text());self.assertIn('15dp',p.read_text())
    def test_id_target_survives_sibling_insertion(self):
        p=self.old/'res/layout/item.xml';p.write_text(p.read_text().replace('<TextView','<View android:id="@id/other"/><TextView'))
        self.apply();self.assertIn('@id/other',p.read_text());self.assertIn('15dp',p.read_text())
    def test_idempotence(self):
        self.apply();before=self.snapshot();result=self.apply();self.assertEqual(self.snapshot(),before)
        self.assertTrue(all(x.get('status','already-applied')=='already-applied' for x in result['operations']))
    def test_code_conflict_transactional(self):
        p=self.old/'smali/Example.smali';p.write_text(p.read_text().replace('const/16 v1, 0x14','const/16 v1, 0x66'));before=self.snapshot()
        with self.assertRaises(g.Conflict):self.apply()
        self.assertEqual(self.snapshot(),before)
    def test_xml_conflict_transactional(self):
        p=self.old/'res/layout/item.xml';p.write_text(p.read_text().replace('10dp','999dp'));before=self.snapshot()
        with self.assertRaises(g.Conflict):self.apply()
        self.assertEqual(self.snapshot(),before)
    def test_missing_class_conflict(self):
        (self.old/'smali/Example.smali').unlink()
        with self.assertRaises(g.Conflict):self.apply()
    def test_missing_method_conflict(self):
        p=self.old/'smali/Example.smali';p.write_text(p.read_text().replace('read()I','read2()I'))
        with self.assertRaises(g.Conflict):self.apply()
    def test_changed_register_allocation_conflict(self):
        p=self.old/'smali/Example.smali';p.write_text(p.read_text().replace('.locals 2','.locals 3'))
        with self.assertRaises(g.Conflict):self.apply()
    def test_patch_added_dependency_conflict(self):
        self.patch['dependencies']=[{'class':'LDeleted;','member':'f()V'}];before=self.snapshot()
        with self.assertRaises(g.Conflict):self.apply()
        self.assertEqual(self.snapshot(),before)
    def test_whole_file_patch_rejected(self):
        self.patch['whole_file_replacements']=True
        with self.assertRaises(g.Conflict):self.apply()
    def test_ambiguous_hunk_rejected(self):
        h={'before':['x'],'after':['y'],'left':['a'],'right':['b'],'after_left':['a'],'after_right':['b']}
        with self.assertRaises(g.Conflict):g.apply_hunks(['a','x','b','a','x','b'],[h])
    def test_switch_label_reference_not_duplicate_definition(self):
        ls=['.method public f()V','.locals 1','goto :case',':case','return-void',':data','.packed-switch 0x0',':case',':case','.end packed-switch','.end method']
        _,labels=g.shape_data(ls);self.assertEqual(len(labels),2);g.check_labels(ls)
    def test_string_literals_not_rewritten(self):
        self.assertEqual(g.tokens('const-string v0, "0x7f010001 # :cond_0"',{'0x7f010001':'id/a'}),['const-string v0, "0x7f010001 # :cond_0"'])
    def test_padding_nops_not_part_of_patch(self):self.assertEqual(g.tokens('nop\nreturn-void\nnop',{}),['return-void'])
    def test_unknown_branch_target_rejected(self):
        with self.assertRaises(g.Conflict):g.check_labels(['goto :missing','return-void'])
    def test_named_array_order_only(self):
        a=ET.fromstring('<resources><string-array name="protocol"><item>FTP</item><item>SMB</item></string-array><string name="x">keep</string></resources>')
        b=ET.fromstring('<resources><string-array name="protocol"><item>SMB</item><item>FTP</item></string-array><string name="x">keep</string></resources>')
        edits=g.xml_changes(a,b);self.assertEqual(len(edits),1);g.apply_xml(a,edits);self.assertEqual(g.logical_xml(a),g.logical_xml(b))
    def test_array_upstream_new_protocol_conflicts(self):
        a=ET.fromstring('<resources><string-array name="protocol"><item>FTP</item><item>SMB</item></string-array></resources>')
        b=ET.fromstring('<resources><string-array name="protocol"><item>SMB</item><item>FTP</item></string-array></resources>')
        edits=g.xml_changes(a,b);ET.SubElement(a[0],'item').text='NEW'
        with self.assertRaises(g.Conflict):g.apply_xml(a,edits)
if __name__=='__main__':unittest.main()
