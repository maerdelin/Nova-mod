#!/usr/bin/env python3
"""Simulator-only patch for actual NOVA UI, saved account, and loopback DAV.

This script is deliberately NEVER called by tianyi-build.yml, only the separate
QA test workflow. The production APK contains the real Tianyi driver.
"""
from pathlib import Path
import sys
if len(sys.argv) != 2:
    raise SystemExit("usage: qa_mock_auth_patch.py TianyiCloud.java")
p=Path(sys.argv[1])
s=p.read_text(encoding="utf-8")

def replace_once(old, new, label):
    global s
    if s.count(old) != 1:
        raise SystemExit("QA patch anchor drift: " + label)
    s = s.replace(old, new, 1)

replace_once(
    """    public void beginLogin(QrListener listener, Callable<Boolean> alive) {
        workers.execute(()->{""",
    """    public void beginLogin(QrListener listener, Callable<Boolean> alive) {
        // QA MOCK ONLY: a successful auth must persist credentials first.
        workers.execute(()->{
            try {
                store.saveTokens("qa-access", "qa-refresh");
                listener.onAuthorized(rootUri());
                android.util.Log.i("NOVA_TIANYI_QA","AUTH_CALLBACK_OK");
            }catch(Exception e){
                android.util.Log.e("NOVA_TIANYI_QA","AUTH_CALLBACK_FAIL",e);
            }
        });
        if(System.nanoTime()!=Long.MIN_VALUE)return;
        workers.execute(()->{""",
    "auth callback",
)
replace_once(
    """    public void ensureSession() throws Exception {
        synchronized(sessionLock){""",
    """    public void ensureSession() throws Exception {
        // QA MOCK ONLY: require the persisted encrypted refresh token.
        if(System.nanoTime()!=Long.MIN_VALUE) {
            if(store.read().refreshToken.isEmpty())
                throw new java.io.IOException("Mock saved account missing");
            sessionKey="qa-session";
            sessionSecret="qa-secret";
            nextRefresh=System.currentTimeMillis()+15*60*1000L;
            android.util.Log.i("NOVA_TIANYI_QA","SAVED_SESSION_RESTORED");
            return;
        }
        synchronized(sessionLock){""",
    "restored session",
)
replace_once(
    """    private List<FileObj> list(String folderId) throws Exception {
        long diagStart=TianyiDiag.tick();""",
    """    private List<FileObj> list(String folderId) throws Exception {
        // QA MOCK ONLY: real DAV HTTP requests should return this directory.
        if(System.nanoTime()!=Long.MIN_VALUE) {
            ensureSession();
            java.util.ArrayList<FileObj> fixture=new java.util.ArrayList<>();
            if("-11".equals(folderId)) {
                FileObj folder=new FileObj();
                folder.id="qa-folder"; folder.name="QA Root Folder";
                folder.parent="-11"; folder.dir=true; folder.size=0L;
                folder.mtime=System.currentTimeMillis();
                fixture.add(folder);
            }
            android.util.Log.i("NOVA_TIANYI_QA","MOCK_ROOT_LIST_"+folderId);
            return fixture;
        }
        long diagStart=TianyiDiag.tick();""",
    "mock root listing",
)
replace_once(
    """                    TianyiDiag.event("DAV_RESTORE","OK",0);""",
    """                    TianyiDiag.event("DAV_RESTORE","OK",0);
                    android.util.Log.i("NOVA_TIANYI_QA","SAVED_DAV_BOUND");""",
    "restore listener",
)
p.write_text(s, encoding="utf-8")
print("NOVA_TIANYI_QA_BACKEND_MOCK=ENABLED_IN_TEST_DEX_ONLY")

# UI QA stage markers are emitted through android.util.Log only in QA DEX.
q=p.with_name("TianyiUi.java")
u=q.read_text(encoding="utf-8")
replacements={
    '            Uri uri=Uri.parse(path);':
    '            Uri uri=Uri.parse(path);\n            android.util.Log.i("NOVA_TIANYI_QA","TITLE_MAPPING scheme="+uri.getScheme()+" host="+uri.getHost()+" port="+uri.getPort()+" oldLen="+(oldName==null?-1:oldName.length()));',
    '            TianyiDiag.event("SHORTCUT_SAVE","OK",0);':
    '            TianyiDiag.event("SHORTCUT_SAVE","OK",0);\n            android.util.Log.i("NOVA_TIANYI_QA","SHORTCUT_SAVED");',
    '        dismissAuthorizedDialog(fragment);':
    '        dismissAuthorizedDialog(fragment);\n        android.util.Log.i("NOVA_TIANYI_QA","DIALOG_DISMISS_CALLED");',
    '        page.getClass().getMethod("novaTianyiRefreshShortcuts").invoke(page);':
    '        android.util.Log.i("NOVA_TIANYI_QA","NETWORK_REFRESH_PAGE="+page.getClass().getName());\n        page.getClass().getMethod("novaTianyiRefreshShortcuts").invoke(page);\n        android.util.Log.i("NOVA_TIANYI_QA","NETWORK_REFRESH_INVOKED");',
    '        if(page==null) {':
    '        if(page==null) {\n            android.util.Log.i("NOVA_TIANYI_QA","NETWORK_REFRESH_NO_PAGE");',
    '        activeNetworkPage=new WeakReference<>(page);':
    '        activeNetworkPage=new WeakReference<>(page);\n        android.util.Log.i("NOVA_TIANYI_QA","NETWORK_PAGE_REGISTERED="+page.getClass().getName());',
    '            catch(Exception ignored) { TianyiDiag.event("NETWORK_REFRESH_RETRY","FAIL",-1); }':
    '            catch(Exception ignored) { TianyiDiag.event("NETWORK_REFRESH_RETRY","FAIL",-1); android.util.Log.e("NOVA_TIANYI_QA","NETWORK_REFRESH_FAILED",ignored); }',
    '                owner.recreate();':
    '                android.util.Log.i("NOVA_TIANYI_QA","NETWORK_REFRESH_RECREATE");\n                owner.recreate();',
}
for old,new in replacements.items():
    if u.count(old)!=1: raise SystemExit("QA UI anchor drift: "+old)
    u=u.replace(old,new,1)
q.write_text(u,encoding="utf-8")
print("NOVA_TIANYI_QA_UI_MARKERS=ENABLED_IN_TEST_DEX_ONLY")
