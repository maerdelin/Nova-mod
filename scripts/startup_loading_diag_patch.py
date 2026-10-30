#!/usr/bin/env python3
"""NOVA 947: read-only start-loading diagnostics in final APK smali.

Only trace marker instructions and a dedicated log class are injected. The
original player conditions, network policies, seek, decoding and buffers stay
untouched. No URLs, tokens, cookies, credential contents or file names logged.
"""
from __future__ import annotations

import re
from pathlib import Path

TRACE = "Lcom/archos/mediacenter/video/player/NovaLoadingTrace;"
METHOD = re.compile(r"^\.method[^\n]*\n.*?^\.end method", re.M | re.S)

# Android's elapsedRealtime is a monotonic wall clock across all Java workers.
# Logcat's own PID/TID identify whether stages overlap or run serially.
TRACE_SMALI = r'''.class public final Lcom/archos/mediacenter/video/player/NovaLoadingTrace;
.super Ljava/lang/Object;
.source "NovaLoadingTrace.java"

.field private static sActive:Z
.field private static sSession:I
.field private static sHttpId:I

.method private constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public static begin()V
    .locals 1
    sget v0, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->sSession:I
    add-int/lit8 v0, v0, 0x1
    sput v0, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->sSession:I
    const/4 v0, 0x1
    sput-boolean v0, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->sActive:Z
    const-string v0, "UI_START"
    invoke-static {v0}, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->mark(Ljava/lang/String;)V
    return-void
.end method

.method public static visible()V
    .locals 1
    const-string v0, "UI_SPINNER_VISIBLE"
    invoke-static {v0}, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->mark(Ljava/lang/String;)V
    return-void
.end method

.method public static visibility(I)V
    .locals 1
    if-nez p0, :done
    const-string v0, "UI_HANDLER_VIEW_VISIBLE"
    invoke-static {v0}, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->mark(Ljava/lang/String;)V
    :done
    return-void
.end method

.method public static markMessage(Landroid/os/Message;)V
    .locals 3
    if-eqz p0, :done
    iget v0, p0, Landroid/os/Message;->what:I
    new-instance v1, Ljava/lang/StringBuilder;
    invoke-direct {v1}, Ljava/lang/StringBuilder;-><init>()V
    const-string v2, "UI_HANDLER_WHAT="
    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v1, v0}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    invoke-virtual {v1}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v1
    invoke-static {v1}, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->mark(Ljava/lang/String;)V
    :done
    return-void
.end method

.method public static end()V
    .locals 1
    const-string v0, "UI_SPINNER_HIDE"
    invoke-static {v0}, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->mark(Ljava/lang/String;)V
    const/4 v0, 0x0
    sput-boolean v0, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->sActive:Z
    return-void
.end method

.method public static mark(Ljava/lang/String;)V
    .locals 5
    sget-boolean v0, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->sActive:Z
    if-eqz v0, :done
    invoke-static {}, Landroid/os/SystemClock;->elapsedRealtime()J
    move-result-wide v0
    invoke-static {}, Landroid/os/Process;->myTid()I
    move-result v2
    new-instance v3, Ljava/lang/StringBuilder;
    invoke-direct {v3}, Ljava/lang/StringBuilder;-><init>()V
    const-string v4, "sid="
    invoke-virtual {v3, v4}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    sget v4, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->sSession:I
    invoke-virtual {v3, v4}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    const-string v4, " tMs="
    invoke-virtual {v3, v4}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v3, v0, v1}, Ljava/lang/StringBuilder;->append(J)Ljava/lang/StringBuilder;
    const-string v4, " tid="
    invoke-virtual {v3, v4}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v3, v2}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    const-string v4, " phase="
    invoke-virtual {v3, v4}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v3, p0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v3}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v3
    const-string v4, "NOVA_LOADING_DIAG"
    invoke-static {v4, v3}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    :done
    return-void
.end method

.method public static markHttp(Ljava/lang/String;II)V
    .locals 3
    new-instance v0, Ljava/lang/StringBuilder;
    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V
    invoke-virtual {v0, p0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    const-string v1, " hop="
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, p1}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    const-string v1, " status="
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, p2}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v0
    invoke-static {v0}, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->mark(Ljava/lang/String;)V
    return-void
.end method
.method public static synchronized nextHttp()I
    .locals 1
    sget v0, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->sHttpId:I
    add-int/lit8 v0, v0, 0x1
    sput v0, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->sHttpId:I
    return v0
.end method

.method public static markReq(Ljava/lang/String;III)V
    .locals 3
    new-instance v0, Ljava/lang/StringBuilder;
    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V
    invoke-virtual {v0, p0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    const-string v1, " req="
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, p1}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    const-string v1, " hop="
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, p2}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    const-string v1, " status="
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, p3}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v0
    invoke-static {v0}, Lcom/archos/mediacenter/video/player/NovaLoadingTrace;->mark(Ljava/lang/String;)V
    return-void
.end method
'''

def _method(text: str, name: str, edit) -> str:
    hits = [m for m in METHOD.finditer(text) if name in m.group(0).split("\n", 1)[0]]
    if len(hits) != 1:
        raise RuntimeError(f"startup trace: expected 1 {name}, found {len(hits)}")
    m = hits[0]
    body = edit(m.group(0))
    if body == m.group(0):
        raise RuntimeError("startup trace: no-op in " + name)
    return text[:m.start()] + body + text[m.end():]


def _alloc(body: str):
    """Add exactly one temporary local, preserving existing parameter aliases."""
    m = re.search(r"(?m)^    \.(locals|registers) (\d+)$", body)
    if not m:
        raise RuntimeError("startup trace: registers not found")
    n = int(m.group(2))
    if m.group(1) == "registers":
        # Only handle zero-argument instance methods or known concrete signatures.
        header = body.split("\n", 1)[0]
        if "()V" not in header:
            raise RuntimeError("startup trace: nontrivial .registers signature")
        temp = n - (0 if " static " in header else 1)
    else:
        temp = n
    if temp < 0 or temp > 250:
        raise RuntimeError("startup trace: unexpected register width")
    body = body[:m.start(2)] + str(n + 1) + body[m.end(2):]
    return body, f"v{temp}"


def _log(reg: str, name: str) -> str:
    return (f"    const-string {reg}, \"{name}\"\n"
            f"    invoke-static {{{reg}}}, {TRACE}->mark(Ljava/lang/String;)V\n")


def _log_method_entry(body: str, stage: str) -> str:
    # Both hooks enter before any original local register is initialized.
    # Reuse the existing low scratch v0; no extra locals and no >v15 access.
    # Original instructions immediately overwrite v0 on their normal path.
    m = re.search(r"(?m)^    \.(?:locals|registers) \d+\n", body)
    if not m:
        raise RuntimeError("startup trace: entry registers missing")
    return body[:m.end()] + _log("v0", stage) + body[m.end():]


def patch_activity(text: str) -> str:
    text = _method(text, " start()V", lambda body: _inject_begin(body))
    text = _method(text, " stop()V", lambda body: _log_method_entry(body, "UI_STOP"))
    text = _method(text, " postVideoInfoAndPrepared()V", _inject_hide)
    # Actual UI visibility event, not the 500ms-delayed start entry.
    # Add an unambiguous trace at the VISIBLE instruction, preserving flow.
    return text


def _inject_visible(body: str) -> str:
    """Trace actual View.VISIBLE writes, or record the Handler message identity.

    Never guess the meaning of a visibility call, and do not alter any
    application condition, register allocation or original instruction.
    """
    anchor = re.compile(
        r"(?m)^([ \t]*)invoke-virtual(?:/range)? \{([^}\n]+)\}, "
        r"Landroid/view/View;->setVisibility\(I\)V[ \t]*$"
    )
    matches = list(anchor.finditer(body))
    if matches:
        for m in reversed(matches):
            args = m.group(2).strip()
            reg = args.split("..")[-1].strip() if ".." in args else args.split(",")[-1].strip()
            if not re.fullmatch(r"[vp]\d+", reg):
                raise RuntimeError(f"UI visible: invalid visibility argument register {reg!r}")
            prefix = (
                f"{m.group(1)}invoke-static/range {{{reg} .. {reg}}}, "
                f"{TRACE}->visibility(I)V\n"
            )
            body = body[:m.start()] + prefix + body[m.start():]
        print(f"NOVA_LOADING_DIAG_VISIBILITY=RUNTIME_CHECK count={len(matches)}")
        return body
    # Some upstream handlers delegate visibility writes to another method.
    # Log Message.what rather than falsely claim the spinner is visible.
    header = re.search(r"(?m)^    \.(?:locals|registers) \d+\n", body)
    if not header or " handleMessage(Landroid/os/Message;)V" not in body.split("\n", 1)[0]:
        raise RuntimeError("UI visible: handler method signature/register declaration changed")
    print("NOVA_LOADING_DIAG_VISIBILITY=HANDLER_MESSAGE_FALLBACK count=0")
    hook = f"    invoke-static/range {{p1 .. p1}}, {TRACE}->markMessage(Landroid/os/Message;)V\n"
    return body[:header.end()] + hook + body[header.end():]

def _inject_begin(body: str) -> str:
    if "NovaLoadingTrace" in body:
        raise RuntimeError("startup trace applied twice")
    m = re.search(r"(?m)^    \.(?:locals|registers) \d+\n", body)
    if not m:
        raise RuntimeError("activity start registers missing")
    # begin() owns its registers; no host method register changes.
    return (body[:m.end()] +
            f"    invoke-static {{}}, {TRACE}->begin()V\n" +
            body[m.end():])


def _inject_hide(body: str) -> str:
    anchor = re.compile(r"(?m)^    invoke-virtual(?:/range)? \{[^}\n]+\}, Landroid/view/View;->setVisibility\(I\)V$")
    hits = list(anchor.finditer(body))
    if len(hits) != 1:
        raise RuntimeError(f"loading hide: expected 1 visibility call, got {len(hits)}")
    m = hits[0]
    return body[:m.start()] + f"    invoke-static {{}}, {TRACE}->end()V\n" + body[m.start():]


def patch_player_listener(text: str) -> str:
    return _method(text, " onPrepared()V", lambda b: _log_method_entry(b, "UI_PREPARED_CALLBACK"))


def patch_player(text: str) -> str:
    return _method(text, " onPrepared(Lcom/archos/medialib/IMediaPlayer;)V",
                   lambda b: _log_method_entry(b, "JAVA_MEDIA_PREPARED"))


def _replace_1(text: str, before: str, after: str, name: str) -> str:
    n = text.count(before)
    if n != 1:
        raise RuntimeError(f"startup trace anchor {name}: {n} matches")
    return text.replace(before, after, 1)


def patch_weak_proxy(text: str) -> str:
    # v5 is the unused sixth local of WeakStartProxy.run() (verified template).
    header = ".method public run()V\n    .locals 6\n"
    if header not in text:
        raise RuntimeError("weak proxy run signature changed")
    def at(s, mark, label):
        return _replace_1(s, mark, _log("v5", label) + mark, label)
    text = at(text, "    invoke-static {v0}, Lcom/archos/mediacenter/video/player/DirectTransportProxy;->resolve(Landroid/net/Uri;)Landroid/net/Uri;\n", "WEAK_RESOLVE_BEGIN")
    text = _replace_1(text,
         "    move-result-object v1\n    iput-object v1, p0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->mResolved:Landroid/net/Uri;",
         "    move-result-object v1\n" + _log("v5", "WEAK_RESOLVE_END") +
         "    iput-object v1, p0, Lcom/archos/mediacenter/video/player/WeakStartProxy;->mResolved:Landroid/net/Uri;",
         "WEAK_RESOLVE_END")
    text = at(text,
         "    const-wide/16 v2, 0x3e8\n    invoke-static {v2, v3}, Landroid/os/SystemClock;->sleep(J)V",
         "WEAK_RESOLVE_RETRY_1S")
    text = at(text,
         "    invoke-virtual {v0, p0}, Landroid/os/Handler;->post(Ljava/lang/Runnable;)Z",
         "WEAK_POST_UI")
    return text


def patch_range_http(text: str) -> str:
    # The generated DirectRangeHttp.open() has 14 locals, v13 is unused.
    if ".method public static open(Ljava/lang/String;Ljava/lang/String;J)Ljava/net/HttpURLConnection;\n    .locals 14" not in text:
        raise RuntimeError("HTTP trace: open template changed")
    if re.search(r"\bv13\b", text):
        raise RuntimeError("HTTP trace: v13 is not available")
    text = _replace_1(text,
        "    invoke-virtual {v1}, Ljava/net/URL;->openConnection()Ljava/net/URLConnection;\n",
        _log("v13", "HTTP_HOP_CONNECT_BEGIN") +
        "    invoke-virtual {v1}, Ljava/net/URL;->openConnection()Ljava/net/URLConnection;\n",
        "HTTP_HOP_CONNECT_BEGIN")
    text = _replace_1(text,
        "    invoke-virtual {v4}, Ljava/net/HttpURLConnection;->getResponseCode()I\n    move-result v6\n",
        '    invoke-static {}, ' + TRACE + '->nextHttp()I\n'
        '    move-result v13\n'
        '    const-string v5, "HTTP_RESPONSE_WAIT_BEGIN"\n'
        '    const/4 v6, -0x1\n'
        + f"    invoke-static {{v5, v13, v2, v6}}, {TRACE}->markReq(Ljava/lang/String;III)V\n"
        + "    invoke-virtual {v4}, Ljava/net/HttpURLConnection;->getResponseCode()I\n"
        + "    move-result v6\n"
        + '    const-string v5, "HTTP_RESPONSE_WAIT_END"\n'
        + f"    invoke-static {{v5, v13, v2, v6}}, {TRACE}->markReq(Ljava/lang/String;III)V\n",
        "HTTP_RESPONSE_WAIT")
    text = _replace_1(text,
        "    :redirect\n    const-string v7, \"Location\"\n",
        "    :redirect\n" + _log("v13", "HTTP_REDIRECT") +
        "    const-string v7, \"Location\"\n", "HTTP_REDIRECT")
    text = _replace_1(text,
        "    return-object v4\n",
        _log("v13", "HTTP_RANGE_READY") + "    return-object v4\n",
        "HTTP_RANGE_READY")
    return text


def patch_redirect_resolver(text: str) -> str:
    # Other formats resolve a Range 0-0 before the transport opens.
    def edit(body):
        body, reg = _alloc(body)
        body = _replace_1(body,
            "    invoke-virtual {v1}, Ljava/net/URL;->openConnection()Ljava/net/URLConnection;\n",
            _log(reg, "RESOLVER_HOP_CONNECT_BEGIN") +
            "    invoke-virtual {v1}, Ljava/net/URL;->openConnection()Ljava/net/URLConnection;\n",
            "RESOLVER_HOP_CONNECT_BEGIN")
        body = _replace_1(body,
            "    invoke-virtual {v4}, Ljava/net/HttpURLConnection;->getResponseCode()I\n    move-result v5\n",
            '    invoke-static {}, ' + TRACE + '->nextHttp()I\n'
            + '    move-result ' + reg + '\n'
            + '    const-string v9, "RESOLVER_RESPONSE_WAIT_BEGIN"\n'
            + '    const/4 v5, -0x1\n'
            + f"    invoke-static {{v9, {reg}, v3, v5}}, {TRACE}->markReq(Ljava/lang/String;III)V\n"
            + "    invoke-virtual {v4}, Ljava/net/HttpURLConnection;->getResponseCode()I\n"
            + "    move-result v5\n"
            + '    const-string v9, "RESOLVER_RESPONSE_WAIT_END"\n'
            + f"    invoke-static {{v9, {reg}, v3, v5}}, {TRACE}->markReq(Ljava/lang/String;III)V\n",
            "RESOLVER_RESPONSE_WAIT")
        return body
    return _method(text, " resolve(Ljava/lang/String;Ljava/lang/String;)[Ljava/lang/String;", edit)


def apply_smali_trace(root: Path) -> None:
    group = "com/archos/mediacenter/video/player"
    all_paths = list(root.glob("smali*/" + group))
    if not all_paths:
        raise RuntimeError("startup trace: video player smali directory missing")

    def one(name):
        matches = list(root.glob("smali*/" + group + "/" + name))
        if len(matches) != 1:
            raise RuntimeError(f"startup trace: {name}: {len(matches)} matches")
        return matches[0]

    for name, patch in (
        ("PlayerActivity.smali", patch_activity),
        ("PlayerActivity$PlayerListener.smali", patch_player_listener),
        ("Player.smali", patch_player),
        ("WeakStartProxy.smali", patch_weak_proxy),
        ("DirectRangeHttp.smali", patch_range_http),
        ("DirectRedirectResolver.smali", patch_redirect_resolver),
    ):
        path = one(name)
        old = path.read_text()
        new = patch(old)
        if new == old:
            raise RuntimeError("startup trace empty patch: " + name)
        path.write_text(new)
    # UI Handler is a compiler-generated inner class, not PlayerActivity itself.
    # Match the actual handler by its method body and enforce a unique anchor.
    handlers = []
    for h in root.glob("smali*/" + group + "/PlayerActivity$*.smali"):
        content = h.read_text()
        if " handleMessage(Landroid/os/Message;)V" in content and "setVisibility(I)V" in content:
            handlers.append((h, content))
    if len(handlers) != 1:
        raise RuntimeError(f"startup spinner handler unique match required: {len(handlers)}")
    h, content = handlers[0]
    h.write_text(_method(content, " handleMessage(Landroid/os/Message;)V", _inject_visible))
    target = one("WeakStartProxy.smali").parent / "NovaLoadingTrace.smali"
    if target.exists():
        raise RuntimeError("startup trace helper already exists")
    target.write_text(TRACE_SMALI)
    print("NOVA_LOADING_DIAG_V1=PASS UI prepared/hide; worker; redirects; HTTP phases")
