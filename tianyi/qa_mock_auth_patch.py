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
# Mock at the HTTP transport layer, not at apiGet: this tests the SAME
# production res_code/code/error parsing, signature/session retry,
# page-size fallback, JSON decoding and DAV XML path used by real accounts.
replace_once(
    """    private volatile boolean started=false;""",
    """    private volatile boolean started=false;
    private volatile boolean qaRejectedBulkSessionOnce=false;""",
    "mock retry state",
)
replace_once(
    """    private Reply request0(String method,String url,Map<String,String> params,
                           Map<String,String> form,Map<String,String> headers,
                           boolean redirect,int hops)throws Exception {
        if(hops>8)throw new IOException("Too many Tianyi login redirects");""",
    """    private Reply request0(String method,String url,Map<String,String> params,
                           Map<String,String> form,Map<String,String> headers,
                           boolean redirect,int hops)throws Exception {
        // QA MOCK ONLY: intercept 189Cloud HTTP response bodies. Production
        // apiGet and directory pagination remain unmodified and executed.
        if(System.nanoTime()!=Long.MIN_VALUE && url.startsWith(API+"/")) {
            String action=url.substring(API.length());
            if("/listFiles.action".equals(action)) {
                ensureSession();
                String folder=params.get("folderId");
                int page=Integer.parseInt(params.get("pageNum"));
                int size=Integer.parseInt(params.get("pageSize"));
                if(page<1 || size<1)throw new IOException("Invalid mock page");
                JSONArray folders=new JSONArray(),files=new JSONArray();
                int total=0;
                if("-11".equals(folder)) {
                    total=2;
                    if(page==1) {
                        folders.put(new JSONObject().put("id","qa-folder").put("name","QA Root Folder"));
                        folders.put(new JSONObject().put("id","qa-bulk").put("name","QA Bulk Movies"));
                    }
                } else if("qa-folder".equals(folder)) {
                    total=3;
                    if(page==1) {
                        folders.put(new JSONObject().put("id","qa-nested").put("name","QA Nested Folder"));
                        files.put(new JSONObject().put("id","qa-video").put("name","QA Video.mp4").put("size",1024));
                        files.put(new JSONObject().put("id","qa-mkv").put("name","QA Sample.mkv").put("size",2048));
                    }
                } else if("qa-nested".equals(folder)) {
                    total=1;
                    if(page==1)
                        files.put(new JSONObject().put("fileId","qa-nested-file")
                                .put("fileName","QA Nested.mkv").put("fileSize",4096));
                } else if("qa-bulk".equals(folder)) {
                    total=137;
                    if(page==1 && size>250)
                        throw new IOException("Oversize API response");
                    if(page==1 && !qaRejectedBulkSessionOnce) {
                        qaRejectedBulkSessionOnce=true;
                        android.util.Log.i("NOVA_TIANYI_QA","MOCK_INVALID_SESSION_REJECTED_ONCE");
                        return new Reply(new JSONObject().put("code","InvalidSessionKey").toString(),url);
                    }
                    // Provider-side cap: asks for 250 rows, returns only 40
                    // per page. The bridge MUST continue to all 137 rows.
                    int from=(page-1)*40,until=Math.min(from+40,total);
                    for(int index=from;index<until;index++) {
                        String title=String.format(Locale.US,"QA Movie %03d.mkv",index);
                        if(index==5)title="QA Movie 005 O\\\\'Brien.mkv";
                        if(index==6)title="电影 006.mkv";
                        files.put(new JSONObject().put("id","qa-film-"+index)
                                .put("name",title).put("size",1024L*1024L*(index+1)));
                    }
                }
                android.util.Log.i("NOVA_TIANYI_QA","MOCK_LIST_API_PAGE_"+page+"_COUNT_"+files.length());
                JSONObject response=new JSONObject().put("res_code",0)
                        .put("fileListAO",new JSONObject().put("count",total)
                        .put("folderList",folders).put("fileList",files));
                return new Reply(response.toString(),url);
            }
            if("/keepUserSession.action".equals(action))
                return new Reply(new JSONObject().put("res_code",0).toString(),url);
        }
        if(hops>8)throw new IOException("Too many Tianyi login redirects");""",
    "mock transport layer listFiles and real production parsing",
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
    '            if(isTianyiUri(path))':
    '            android.util.Log.i("NOVA_TIANYI_QA","TITLE_MAPPING ownPath="+TianyiCloud.isOwnShortcutLabel(path)+" ownLabel="+TianyiCloud.isOwnShortcutLabel(oldName));\n            if(isTianyiUri(path))',
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
