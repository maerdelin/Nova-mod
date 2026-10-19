#!/usr/bin/env python3
"""Seamlessly resume interrupted WebDAV HTTP media bodies at the exact delivered byte.

Run368 adds retries to opening the source. This separate patch handles failures
after the HTTP headers have been sent, while keeping the already-open localhost
HTTP response and AVOS decoder untouched. WebDAV file errors exit PlayerActivity
instead of leaving a loading spinner after all recovery attempts fail.

No changes to native buffering, decoding, HDMI, normal EOF, or non-WebDAV paths.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

OUTER = "Lcom/archos/filecorelibrary/StreamOverHttp;"
SESSION = "Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;"
ACTIVITY = "Lcom/archos/mediacenter/video/player/PlayerActivity;"
LISTENER = "Lcom/archos/mediacenter/video/player/PlayerActivity$PlayerListener;"
COPY_PROTO = "(Ljava/io/InputStream;Ljava/io/OutputStream;[BJLcom/archos/filecorelibrary/StreamOverHttp$HttpSession;)V"

OUTER_METHODS = r'''
.method public novaGetOriginUri()Landroid/net/Uri;
    .locals 1
    iget-object v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp;->mUri:Landroid/net/Uri;
    return-object v0
.end method

.method private copyStream(Ljava/io/InputStream;Ljava/io/OutputStream;[BJLcom/archos/filecorelibrary/StreamOverHttp$HttpSession;)V
    .locals 3
    if-eqz p6, :nova_copy_legacy
    invoke-virtual {p6}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->novaMediaResumeEligible()Z
    move-result v0
    if-eqz v0, :nova_copy_legacy
    const-wide/16 v0, 0x0
    cmp-long v2, p4, v0
    if-lez v2, :nova_copy_legacy
    invoke-direct/range {p0 .. p6}, Lcom/archos/filecorelibrary/StreamOverHttp;->novaCopyStreamRecovering(Ljava/io/InputStream;Ljava/io/OutputStream;[BJLcom/archos/filecorelibrary/StreamOverHttp$HttpSession;)V
    return-void
    :nova_copy_legacy
    invoke-direct/range {p0 .. p6}, Lcom/archos/filecorelibrary/StreamOverHttp;->novaCopyStreamOriginal(Ljava/io/InputStream;Ljava/io/OutputStream;[BJLcom/archos/filecorelibrary/StreamOverHttp$HttpSession;)V
    return-void
.end method

.method private novaCopyStreamRecovering(Ljava/io/InputStream;Ljava/io/OutputStream;[BJLcom/archos/filecorelibrary/StreamOverHttp$HttpSession;)V
    .locals 9
    move-object v2, p1
    invoke-virtual {p6}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->novaRequestedStart()J
    move-result-wide v3
    const/4 v5, 0x0

    :nova_copy_loop
    const-wide/16 v7, 0x0
    cmp-long v0, p4, v7
    if-eqz v0, :nova_copy_done
    invoke-virtual {p6}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->novaMediaResumeEligible()Z
    move-result v0
    if-eqz v0, :nova_copy_done
    array-length v0, p3
    int-to-long v7, v0
    cmp-long v1, p4, v7
    if-gez v1, :nova_read
    long-to-int v0, p4
    :nova_read
    const/4 v1, 0x0
    :nova_read_try_start
    invoke-virtual {v2, p3, v1, v0}, Ljava/io/InputStream;->read([BII)I
    move-result v0
    :nova_read_try_end
    .catch Ljava/io/IOException; {:nova_read_try_start .. :nova_read_try_end} :nova_read_failed
    if-lez v0, :nova_premature_end
    invoke-virtual {p6}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->novaMediaResumeEligible()Z
    move-result v1
    if-eqz v1, :nova_copy_done
    const/4 v1, 0x0
    invoke-virtual {p2, p3, v1, v0}, Ljava/io/OutputStream;->write([BII)V
    int-to-long v7, v0
    add-long/2addr v3, v7
    sub-long/2addr p4, v7
    const/4 v5, 0x0
    goto :nova_copy_loop

    :nova_read_failed
    move-exception v6
    goto :nova_copy_retry

    :nova_premature_end
    new-instance v6, Ljava/io/EOFException;
    const-string v0, "WebDAV upstream ended before Content-Length"
    invoke-direct {v6, v0}, Ljava/io/EOFException;-><init>(Ljava/lang/String;)V

    :nova_copy_retry
    invoke-virtual {p6}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->novaMediaResumeEligible()Z
    move-result v0
    if-eqz v0, :nova_copy_done
    const/4 v0, 0x3
    if-ge v5, v0, :nova_copy_exhausted
    add-int/lit8 v5, v5, 0x1
    const/4 v0, 0x1
    if-le v5, v0, :nova_reopen_now
    const-wide/16 v7, 0x1f4
    :nova_sleep_try_start
    invoke-static {v7, v8}, Ljava/lang/Thread;->sleep(J)V
    :nova_sleep_try_end
    .catch Ljava/lang/InterruptedException; {:nova_sleep_try_start .. :nova_sleep_try_end} :nova_copy_interrupted

    :nova_reopen_now
    const-string v0, "NOVA_WEBDAV_MIDSTREAM"
    new-instance v1, Ljava/lang/StringBuilder;
    invoke-direct {v1}, Ljava/lang/StringBuilder;-><init>()V
    const-string v7, "resume byte="
    invoke-virtual {v1, v7}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v1
    invoke-virtual {v1, v3, v4}, Ljava/lang/StringBuilder;->append(J)Ljava/lang/StringBuilder;
    move-result-object v1
    const-string v7, " attempt="
    invoke-virtual {v1, v7}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v1
    invoke-virtual {v1, v5}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    move-result-object v1
    const-string v7, "/3"
    invoke-virtual {v1, v7}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v1
    invoke-virtual {v1}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v1
    invoke-static {v0, v1, v6}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I

    :nova_reopen_try_start
    invoke-virtual {p6, v3, v4}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->novaResumeUpstreamAt(J)Ljava/io/InputStream;
    move-result-object v2
    invoke-virtual {p6}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->novaUpstreamBufferSize()I
    move-result v0
    invoke-static {v2, p4, p5, v0}, Lcom/archos/filecorelibrary/StreamOverHttp;->bufferResponseInput(Ljava/io/InputStream;JI)Ljava/io/InputStream;
    move-result-object v2
    :nova_reopen_try_end
    .catch Ljava/lang/Exception; {:nova_reopen_try_start .. :nova_reopen_try_end} :nova_reopen_failed
    goto :nova_copy_loop

    :nova_reopen_failed
    move-exception v6
    goto :nova_copy_retry

    :nova_copy_interrupted
    move-exception v0
    invoke-static {}, Ljava/lang/Thread;->currentThread()Ljava/lang/Thread;
    move-result-object v1
    invoke-virtual {v1}, Ljava/lang/Thread;->interrupt()V
    return-void

    :nova_copy_exhausted
    const-string v0, "NOVA_WEBDAV_MIDSTREAM"
    const-string v1, "EXHAUSTED: three attempts failed; propagate error to player"
    invoke-static {v0, v1, v6}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I
    throw v6

    :nova_copy_done
    return-void
.end method
'''

SESSION_METHODS = r'''
.method public novaMediaResumeEligible()Z
    .locals 2
    iget-boolean v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->supersedableMediaRequest:Z
    if-eqz v0, :nova_not_eligible
    invoke-direct {p0}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->isCancelled()Z
    move-result v0
    if-nez v0, :nova_not_eligible
    iget-object v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->this$0:Lcom/archos/filecorelibrary/StreamOverHttp;
    invoke-virtual {v0}, Lcom/archos/filecorelibrary/StreamOverHttp;->novaWebdavOrigin()Z
    move-result v0
    return v0
    :nova_not_eligible
    const/4 v0, 0x0
    return v0
.end method

.method public novaRequestedStart()J
    .locals 2
    iget-wide v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->requestedStart:J
    return-wide v0
.end method

.method public novaUpstreamBufferSize()I
    .locals 1
    iget v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->upstreamBufferSize:I
    return v0
.end method

.method public novaResumeUpstreamAt(J)Ljava/io/InputStream;
    .locals 4
    invoke-virtual {p0}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->novaMediaResumeEligible()Z
    move-result v0
    if-nez v0, :nova_resume_allowed
    new-instance v0, Ljava/io/IOException;
    const-string v1, "WebDAV media request cancelled before reconnect"
    invoke-direct {v0, v1}, Ljava/io/IOException;-><init>(Ljava/lang/String;)V
    throw v0
    :nova_resume_allowed
    invoke-direct {p0}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->takeInput()Ljava/io/InputStream;
    move-result-object v0
    invoke-direct {p0, v0}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->closeInput(Ljava/io/InputStream;)V
    iget-object v0, p0, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->this$0:Lcom/archos/filecorelibrary/StreamOverHttp;
    invoke-virtual {v0}, Lcom/archos/filecorelibrary/StreamOverHttp;->novaGetOriginUri()Landroid/net/Uri;
    move-result-object v1
    invoke-virtual {v0, v1}, Lcom/archos/filecorelibrary/StreamOverHttp;->getFileEditor(Landroid/net/Uri;)Lcom/archos/filecorelibrary/FileEditor;
    move-result-object v2
    invoke-direct {p0}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->readOptions()Lcom/archos/filecorelibrary/ReadOptions;
    move-result-object v3
    invoke-virtual {v2, p1, p2, v3}, Lcom/archos/filecorelibrary/FileEditor;->getInputStream(JLcom/archos/filecorelibrary/ReadOptions;)Ljava/io/InputStream;
    move-result-object v0
    invoke-direct {p0, v0}, Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;->publishInput(Ljava/io/InputStream;)V
    return-object v0
.end method
'''

ACTIVITY_METHOD = r'''
.method public novaFinishWebdavFileError(I)Z
    .locals 3
    const/16 v0, 0x3e9
    if-ne p1, v0, :nova_normal_error
    iget-object v0, p0, Lcom/archos/mediacenter/video/player/PlayerActivity;->mUri:Landroid/net/Uri;
    if-eqz v0, :nova_normal_error
    invoke-virtual {v0}, Landroid/net/Uri;->getScheme()Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :nova_normal_error
    const-string v1, "webdav"
    invoke-virtual {v0, v1}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-nez v2, :nova_finish_webdav
    const-string v1, "webdavs"
    invoke-virtual {v0, v1}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-eqz v2, :nova_normal_error
    :nova_finish_webdav
    const-string v0, "NOVA_WEBDAV_MIDSTREAM"
    const-string v1, "Terminal WebDAV file error: finishing player activity"
    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I
    invoke-virtual {p0}, Lcom/archos/mediacenter/video/player/PlayerActivity;->finish()V
    const/4 v0, 0x1
    return v0
    :nova_normal_error
    const/4 v0, 0x0
    return v0
.end method
'''

def exactly_one(root: Path, name: str) -> Path:
    result = list(root.glob("smali*/" + name))
    if len(result) != 1:
        raise RuntimeError(f"{name}: expected exactly one decoded class, found {len(result)}")
    return result[0]

def patch_outer(text: str) -> str:
    if "novaCopyStreamRecovering(" in text or "novaGetOriginUri()" in text:
        raise RuntimeError("StreamOverHttp midstream patch already present")
    for required in ("novaWebdavOrigin()Z", "bufferResponseInput(Ljava/io/InputStream;JI)Ljava/io/InputStream;",
                     "mUri:Landroid/net/Uri;"):
        if required not in text:
            raise RuntimeError("Missing StreamOverHttp feature: " + required)
    original = re.compile(r"(?m)^(\.method [^\n]*\s)copyStream" + re.escape(COPY_PROTO) + r"\s*$")
    matches = list(original.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one copyStream{COPY_PROTO}, found {len(matches)}")
    text = original.sub(lambda m: m.group(1) + "novaCopyStreamOriginal" + COPY_PROTO, text, count=1)
    return text.rstrip() + "\n" + OUTER_METHODS

def patch_session(text: str) -> str:
    if "novaResumeUpstreamAt(" in text:
        raise RuntimeError("Midstream resume already installed in HttpSession")
    for required in ("supersedableMediaRequest:Z", "this$0:Lcom/archos/filecorelibrary/StreamOverHttp;",
                     "requestedStart:J", "upstreamBufferSize:I", "isCancelled()Z",
                     "takeInput()Ljava/io/InputStream;", "closeInput(Ljava/io/InputStream;)V",
                     "readOptions()Lcom/archos/filecorelibrary/ReadOptions;",
                     "publishInput(Ljava/io/InputStream;)V"):
        if required not in text:
            raise RuntimeError("Missing HttpSession member: " + required)
    return text.rstrip() + "\n" + SESSION_METHODS

def patch_activity(text: str) -> str:
    if "novaFinishWebdavFileError(" in text:
        raise RuntimeError("WebDAV terminal finish already installed")
    if ".field" not in text or "mUri:Landroid/net/Uri;" not in text:
        raise RuntimeError("PlayerActivity.mUri field missing")
    return text.rstrip() + "\n" + ACTIVITY_METHOD

def patch_listener(text: str) -> str:
    if "novaFinishWebdavFileError(I)Z" in text:
        raise RuntimeError("WebDAV terminal finish listener already installed")
    if "this$0:Lcom/archos/mediacenter/video/player/PlayerActivity;" not in text:
        raise RuntimeError("PlayerListener outer reference missing")
    pat = re.compile(r"(?ms)^(\.method [^\n]* onError\(IILjava/lang/String;\)Z\n)"
                     r"(.*?)(^\.end method$)")
    matches = list(pat.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one PlayerListener.onError, got {len(matches)}")
    m = matches[0]
    body = m.group(2)
    loc = re.search(r"(?m)^[ \t]+\.locals ([0-9]+)\s*$", body)
    if not loc:
        raise RuntimeError("PlayerListener.onError .locals missing")
    if int(loc.group(1)) < 2:
        body = body[:loc.start(1)] + "2" + body[loc.end(1):]
        loc = re.search(r"(?m)^[ \t]+\.locals ([0-9]+)\s*$", body)
    inject = r'''
    move-object/from16 v1, p0
    iget-object v0, v1, Lcom/archos/mediacenter/video/player/PlayerActivity$PlayerListener;->this$0:Lcom/archos/mediacenter/video/player/PlayerActivity;
    move/from16 v1, p1
    invoke-virtual {v0, v1}, Lcom/archos/mediacenter/video/player/PlayerActivity;->novaFinishWebdavFileError(I)Z
    move-result v0
    if-eqz v0, :nova_continue_default_player_error
    const/4 v0, 0x1
    return v0
    :nova_continue_default_player_error
'''
    body = body[:loc.end()] + inject + body[loc.end():]
    return text[:m.start()] + m.group(1) + body + m.group(3) + text[m.end():]

def apply(root: Path, report: Path | None = None) -> dict:
    specs = [
        ("com/archos/filecorelibrary/StreamOverHttp.smali", patch_outer),
        ("com/archos/filecorelibrary/StreamOverHttp$HttpSession.smali", patch_session),
        ("com/archos/mediacenter/video/player/PlayerActivity.smali", patch_activity),
        ("com/archos/mediacenter/video/player/PlayerActivity$PlayerListener.smali", patch_listener),
    ]
    updated = []
    for name, patch in specs:
        path = exactly_one(root, name)
        source = path.read_text(encoding="utf-8")
        updated.append((path, patch(source)))
    for path, changed in updated:
        path.write_text(changed, encoding="utf-8")
    info = {
        "status": "PASS",
        "changed_classes": [str(p.relative_to(root)) for p, _ in updated],
        "connection_resume": "Same localhost HTTP response; new WebDAV input from delivered byte offset",
        "read_error_handling": "IOException or premature EOF with known Content-Length",
        "retries": 3,
        "retry_delays_ms": [0, 500, 500],
        "retry_scope": "Only active WebDAV media responses; no retry after cancel/seek",
        "normal_eof": "preserved",
        "terminal_failure": "WebDAV MEDIA_ERROR_VE_FILE_ERROR finishes PlayerActivity",
        "other_schemes_and_errors": "original code preserved",
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    print(json.dumps(apply(args.root, args.report), indent=2))
