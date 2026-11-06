#!/usr/bin/env python3
"""QA-only, never included in release source or final APK.

Replace exactly one Java beginLogin method entry with a nonconstant
test-only branch that dispatches the same onAuthorized callback after
creating a local loopback DAV URI; no cloud tokens or network calls.
"""
from pathlib import Path
import sys
if len(sys.argv)!=2: raise SystemExit("usage: qa_mock_auth_patch.py TianyiCloud.java")
p=Path(sys.argv[1])
s=p.read_text(encoding="utf-8")
old="""    public void beginLogin(QrListener listener, Callable<Boolean> alive) {
        workers.execute(()->{"""
new="""    public void beginLogin(QrListener listener, Callable<Boolean> alive) {
        // SYNTHETIC AUTHORIZATION: QA APK ONLY. NEVER RELEASE.
        if(System.nanoTime()!=Long.MIN_VALUE) {
            workers.execute(()->{
                try {
                    listener.onAuthorized(rootUri());
                }catch(Exception e){
                    listener.onStatus("QA synthetic callback failed");
                }
            });
            return;
        }
        workers.execute(()->{"""
if s.count(old)!=1: raise SystemExit("Unexpected beginLogin anchor")
p.write_text(s.replace(old,new),encoding="utf-8")
print("NOVA_TIANYI_QA_SYNTHETIC_AUTH=ENABLED_IN_TEST_ONLY")

# Also instrument the test-only UI callback stages, not any release source.
q=p.with_name("TianyiUi.java")
if not q.exists(): raise SystemExit("No TianyiUi.java beside cloud driver")
ui=q.read_text(encoding="utf-8")
replacements={
    '            TianyiDiag.event("SHORTCUT_SAVE","OK",0);':
      '            TianyiDiag.event("SHORTCUT_SAVE","OK",0);\n            android.util.Log.i("NOVA_TIANYI_QA","SHORTCUT_SAVE_OK");',
    '            TianyiDiag.event("SHORTCUT_SAVE","FAIL",-1);':
      '            TianyiDiag.event("SHORTCUT_SAVE","FAIL",-1);\n            android.util.Log.i("NOVA_TIANYI_QA","SHORTCUT_SAVE_FAIL "+saveError.getClass().getSimpleName());',
    '            refreshScheduled=refreshNetworkPage();':
      '            refreshScheduled=refreshNetworkPage();\n            android.util.Log.i("NOVA_TIANYI_QA","REFRESH_RETURN_"+refreshScheduled);',
    '            TianyiDiag.event("NETWORK_REFRESH","FAIL",-1);':
      '            TianyiDiag.event("NETWORK_REFRESH","FAIL",-1);\n            android.util.Log.i("NOVA_TIANYI_QA","REFRESH_ERROR "+refreshError.getClass().getSimpleName());',
    '        dismissAuthorizedDialog(fragment);':
      '        dismissAuthorizedDialog(fragment);\n        android.util.Log.i("NOVA_TIANYI_QA","DISMISS_CALLED");'
}
for old,new in replacements.items():
    if ui.count(old)!=1:raise SystemExit("QA UI anchor mismatch: "+old)
    ui=ui.replace(old,new)
q.write_text(ui,encoding="utf-8")
print("NOVA_TIANYI_QA_UI_STAGE_LOGGING=ENABLED_TEST_ONLY")
