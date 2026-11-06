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
