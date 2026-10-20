#!/usr/bin/env python3
"""Four targeted Run400 follow-up repairs. Fail closed when APK anchors change.

Does not change native 2X/5X/10X arithmetic, decoder selection, credentials,
TLS verification or exact Content-Range validation. Apply smali after P012.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

EDITOR = 'Lcom/archos/filecorelibrary/webdav/WebdavFileEditor;'
POLICY = 'Lcom/archos/filecorelibrary/NovaWebdavOpenPolicy;'
SOURCE = 'Lcom/archos/filecorelibrary/NovaWebdavOpenPolicy$Source;'
SESSION = 'Lcom/archos/filecorelibrary/StreamOverHttp$HttpSession;'
PROXY = 'Lcom/archos/mediacenter/video/player/BlurayIsoProxy;'
GUARD = 'Lcom/archos/filecorelibrary/NovaIsoSessionGuard;'
TASK_SOURCE = 'Lcom/archos/mediacenter/video/player/NovaIsoSourceClose;'
TASK_NATIVE = 'Lcom/archos/mediacenter/video/player/NovaIsoNativeClose;'
METHOD = re.compile(r'(?ms)^\.method [^\n]+\n.*?^\.end method$')

def once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f'{label}: expected one anchor, got {text.count(old)}')
    return text.replace(old, new, 1)

def rename_declaration(body: str, old: str, new: str, label: str) -> str:
    # Only the declaration owns the method name. Debug metadata/comments may
    # repeat it; replacing/counting the whole body conflates data with code.
    header, sep, rest = body.partition("\n")
    if not sep or not header.startswith(".method ") or not header.endswith(" " + old):
        raise RuntimeError(label + ": unexpected method declaration")
    return header[:-len(old)] + new + sep + rest

def add_interface(text: str, interface: str) -> str:
    if ('.implements ' + interface) in text:
        raise RuntimeError('Interface already installed: ' + interface)
    # Baksmali emits .source before .implements. Preserve that canonical ordering
    # so the strict APK roundtrip compares identical class headers.
    anchor = re.search(r'(?m)^\.source [^\n]+$', text)
    if anchor is None:
        anchor = re.search(r'(?m)^\.super [^\n]+$', text)
    if anchor is None:
        raise RuntimeError('Class source/super header missing')
    return text[:anchor.end()] + '\n.implements ' + interface + text[anchor.end():]

def replace_method(text: str, name: str, transform) -> str:
    found = [m for m in METHOD.finditer(text) if re.search(r'\s'+re.escape(name)+r'(?:\s|$)', m.group().splitlines()[0])]
    if len(found) != 1: raise RuntimeError(f'{name}: expected one method, got {len(found)}')
    m = found[0]
    return text[:m.start()] + transform(m.group()) + text[m.end():]

EDITOR_WRAPPER = f'''
.method public getInputStream(J)Ljava/io/InputStream;
    .locals 0
    invoke-static {{p0, p1, p2}}, {POLICY}->open({SOURCE}J)Ljava/io/InputStream;
    move-result-object p0
    return-object p0
.end method

.method public novaOrigin()Ljava/lang/String;
    .locals 1
    iget-object v0, p0, Lcom/archos/filecorelibrary/FileEditor;->mUri:Landroid/net/Uri;
    invoke-static {{v0}}, Lcom/archos/filecorelibrary/webdav/WebdavFile2;->uriToHttp(Landroid/net/Uri;)Landroid/net/Uri;
    move-result-object v0
    invoke-virtual {{v0}}, Landroid/net/Uri;->toString()Ljava/lang/String;
    move-result-object v0
    return-object v0
.end method

.method private static novaTraceResponse(Ll31;)V
    .locals 7
    iget v0, p0, Ll31;->d:I
    iget-object v1, p0, Ll31;->a:Lj21;
    iget-object v1, v1, Lj21;->a:Lzb0;
    invoke-virtual {{v1}}, Lzb0;->toString()Ljava/lang/String;
    move-result-object v1
    const/4 v2, 0x0
    const/4 v5, 0x0
    move-object v3, p0
    :nova_prior_loop
    iget-object v3, v3, Ll31;->l:Ll31;
    if-eqz v3, :nova_trace_done
    iget v4, v3, Ll31;->d:I
    const/16 v6, 0x12d
    if-eq v4, v6, :nova_count_redirect
    const/16 v6, 0x12e
    if-eq v4, v6, :nova_count_redirect
    const/16 v6, 0x12f
    if-eq v4, v6, :nova_count_redirect
    const/16 v6, 0x133
    if-eq v4, v6, :nova_count_redirect
    const/16 v6, 0x134
    if-ne v4, v6, :nova_next_prior
    :nova_count_redirect
    add-int/lit8 v2, v2, 0x1
    :nova_next_prior
    add-int/lit8 v5, v5, 0x1
    const/16 v4, 0x14
    if-lt v5, v4, :nova_prior_loop
    :nova_trace_done
    iget-object v3, p0, Ll31;->f:Lf90;
    const-string v4, "Content-Range"
    invoke-virtual {{v3, v4}}, Lf90;->a(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v3
    invoke-static {{v0, v1, v2, v3}}, {POLICY}->response(ILjava/lang/String;ILjava/lang/String;)V
    return-void
.end method
'''

def editor_text(text: str) -> str:
    if 'novaOpenOnce(JZ)' in text: raise RuntimeError('Fourfix editor already installed')
    def change(body):
        body = rename_declaration(body, 'getInputStream(J)Ljava/io/InputStream;', 'novaOpenOnce(JZ)Ljava/io/InputStream;', 'backend rename')
        # Retain the exact original validation/body/cancellation ownership logic.
        for anchor in ('    .locals 18', 'invoke-virtual {v12}, Ltz0;->c()Ll31;',
                       'validateExactContentRangeStart(Ljava/lang/String;J)Z',
                       'OwnedStreams;->cancellableInput('):
            if anchor not in body: raise RuntimeError('HTTP implementation shape changed: '+anchor)
        headers = '''    move/from16 v11, p3
    if-eqz v11, :nova_no_fresh_headers
    const-string v11, "Cache-Control"
    const-string v12, "no-cache"
    invoke-virtual {v14, v11, v12}, Ljava/util/HashMap;->put(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;
    const-string v11, "Pragma"
    invoke-virtual {v14, v11, v12}, Ljava/util/HashMap;->put(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;
    :nova_no_fresh_headers
'''
        body = once(body, '    invoke-static {v14}, Lf90;->b(Ljava/util/Map;)Lf90;', headers+'    invoke-static {v14}, Lf90;->b(Ljava/util/Map;)Lf90;', 'fresh headers')
        anchor = '    move-result-object v10\n\n    iget-object v11, v10, Ll31;->f:Lf90;'
        body = once(body, anchor, '    move-result-object v10\n\n    invoke-static {v10}, '+EDITOR+'->novaTraceResponse(Ll31;)V\n\n    iget-object v11, v10, Ll31;->f:Lf90;', 'actual response trace')
        return body
    text = replace_method(text, 'getInputStream(J)Ljava/io/InputStream;', change)
    text = add_interface(text, SOURCE)
    return text.rstrip()+'\n'+EDITOR_WRAPPER


def session_text(text: str) -> str:
    if 'requestReparse=0' in text: raise RuntimeError('Fourfix session already installed')
    def change(body):
        if ('novaOpenInputStreamOnce()V' not in body or 'novaTransientConnectionFailure' not in body
                or 'Transient upstream connection failed; retry ' not in body):
            raise RuntimeError('Expected legacy whole-request retry wrapper')
        return f'''.method private openInputStream()V
    .locals 0
    # requestReparse=0: read/parse this localhost request exactly once.
    # Bounded upstream GET retries now live in WebdavFileEditor.novaOpenOnce.
    invoke-direct {{p0}}, {SESSION}->novaOpenInputStreamOnce()V
    return-void
.end method'''
    return replace_method(text, 'openInputStream()V', change)

SOURCE_TASK = f'''.class public final {TASK_SOURCE}
.super Ljava/lang/Object;
.implements Ljava/lang/Runnable;
.field private final source:Lcom/archos/filecorelibrary/StreamOverHttp;
.method public constructor <init>(Lcom/archos/filecorelibrary/StreamOverHttp;)V
    .locals 0
    invoke-direct {{p0}}, Ljava/lang/Object;-><init>()V
    iput-object p1, p0, {TASK_SOURCE}->source:Lcom/archos/filecorelibrary/StreamOverHttp;
    return-void
.end method
.method public run()V
    .locals 1
    iget-object v0, p0, {TASK_SOURCE}->source:Lcom/archos/filecorelibrary/StreamOverHttp;
    invoke-virtual {{v0}}, Lcom/archos/filecorelibrary/StreamOverHttp;->close()V
    return-void
.end method
'''
NATIVE_TASK = f'''.class public final {TASK_NATIVE}
.super Ljava/lang/Object;
.implements Ljava/lang/Runnable;
.field private final generation:J
.method public constructor <init>(J)V
    .locals 0
    invoke-direct {{p0}}, Ljava/lang/Object;-><init>()V
    iput-wide p1, p0, {TASK_NATIVE}->generation:J
    return-void
.end method
.method public run()V
    .locals 2
    iget-wide v0, p0, {TASK_NATIVE}->generation:J
    invoke-static {{v0, v1}}, {PROXY}->nativeCloseGeneration(J)V
    return-void
.end method
'''

def proxy_text(text: str) -> str:
    if 'resolveOwned(' in text: raise RuntimeError('Fourfix proxy already installed')
    def change(body):
        body = rename_declaration(body, 'resolve(Landroid/net/Uri;)Landroid/net/Uri;', 'resolveOwned(Landroid/net/Uri;Ljava/lang/Object;)Landroid/net/Uri;', 'ISO owner resolve')
        body = once(body, '    .locals 5', f'''    .locals 5
    invoke-static {{p1}}, {GUARD}->begin(Ljava/lang/Object;)Z
    move-result v0
    if-nez v0, :nova_owner_live
    new-instance v0, Ljava/lang/IllegalStateException;
    const-string v1, "ISO owner already released"
    invoke-direct {{v0, v1}}, Ljava/lang/IllegalStateException;-><init>(Ljava/lang/String;)V
    throw v0
    :nova_owner_live''', 'released owner guard')
        attach = f'''    sput-object v0, {PROXY}->sInput:Lcom/archos/filecorelibrary/StreamOverHttp;
    new-instance v3, {TASK_SOURCE}
    invoke-direct {{v3, v0}}, {TASK_SOURCE}-><init>(Lcom/archos/filecorelibrary/StreamOverHttp;)V
    invoke-static {{p1, v3}}, {GUARD}->attachSource(Ljava/lang/Object;Ljava/lang/Runnable;)Z
    move-result v3
    if-nez v3, :nova_source_attached
    new-instance v3, Ljava/lang/IllegalStateException;
    const-string v4, "ISO cancelled while opening source"
    invoke-direct {{v3, v4}}, Ljava/lang/IllegalStateException;-><init>(Ljava/lang/String;)V
    throw v3
    :nova_source_attached'''
        body = once(body, f'    sput-object v0, {PROXY}->sInput:Lcom/archos/filecorelibrary/StreamOverHttp;', attach, 'attach live source')
        anchor = '    move-result-object p0\n\n    return-object p0'
        replacement = f'''    move-result-object p0
    const-string v3, "nova_iso_generation"
    invoke-virtual {{p0, v3}}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v3
    invoke-static {{v3}}, Ljava/lang/Long;->parseLong(Ljava/lang/String;)J
    move-result-wide v3
    new-instance v1, {TASK_NATIVE}
    invoke-direct {{v1, v3, v4}}, {TASK_NATIVE}-><init>(J)V
    invoke-static {{p1, v1}}, {GUARD}->attachNative(Ljava/lang/Object;Ljava/lang/Runnable;)Z
    move-result v0
    if-nez v0, :nova_native_attached
    new-instance v0, Ljava/lang/IllegalStateException;
    const-string v1, "ISO cancelled before native open completed"
    invoke-direct {{v0, v1}}, Ljava/lang/IllegalStateException;-><init>(Ljava/lang/String;)V
    throw v0
    :nova_native_attached
    return-object p0'''
        return once(body, anchor, replacement, 'attach generation close')
    text = replace_method(text, 'resolve(Landroid/net/Uri;)Landroid/net/Uri;', change)
    return text.rstrip()+f'\n\n.method public static native nativeCloseGeneration(J)V\n.end method\n'


def player_text(text: str) -> str:
    old = f'    invoke-static {{p1}}, {PROXY}->resolve(Landroid/net/Uri;)Landroid/net/Uri;'
    new = f'''    iget v0, p0, Lcom/archos/mediacenter/video/player/Player;->mOpenGeneration:I
    if-eq p2, v0, :nova_resolve_generation_live
    return-void
    :nova_resolve_generation_live
    invoke-static {{p1, p4}}, {PROXY}->resolveOwned(Landroid/net/Uri;Ljava/lang/Object;)Landroid/net/Uri;'''
    text = once(text, old, new, 'resolve current media owner')
    def change(body):
        old = '    iget-object v0, p0, Lcom/archos/mediacenter/video/player/Player;->mMediaPlayer:Lcom/archos/medialib/IMediaPlayer;'
        return once(body, old, old+f'\n\n    invoke-static {{v0}}, {GUARD}->release(Ljava/lang/Object;)V', 'immediate source cancellation')
    return replace_method(text, 'closeCurrentPlayer()V', change)


def release_text(text: str) -> str:
    def change(body):
        if GUARD in body: raise RuntimeError('ISO release hook already installed')
        return once(body, '    .locals 4', f'    .locals 4\n\n    invoke-static {{p0}}, {GUARD}->release(Ljava/lang/Object;)V', 'release lifecycle hook')
    return replace_method(text, 'release()V', change)

NATIVE_CLOSE = r'''
JNIEXPORT void JNICALL
Java_com_archos_mediacenter_video_player_BlurayIsoProxy_nativeCloseGeneration(
        JNIEnv *env, jclass cls, jlong generation) {
    (void)env; (void)cls;
    pthread_mutex_lock(&g_lock);
    if (generation > 0 && g_session && g_session->generation == (uint64_t)generation) {
        iso_session *old = g_session;
        g_session = NULL;
        LOGI("CLOSE_GENERATION generation=%" PRIu64, old->generation);
        session_destroy(old);
    }
    pthread_mutex_unlock(&g_lock);
}
'''

def iso_text(text: str) -> str:
    if 'nativeCloseGeneration' in text: raise RuntimeError('Fourfix ISO already installed')
    text = once(text, '    uint64_t title_size;\n', '    uint64_t title_size;\n    uint64_t generation;\n', 'native owner generation')
    text = once(text, 'static iso_session *g_session = NULL;', 'static iso_session *g_session = NULL;\nstatic uint64_t g_generation = 0;', 'native generation counter')
    text = once(text, '        char out[256];', '        char out[320];\n        g_session->generation = ++g_generation;', 'native generation assignment')
    add = r'''        {
            size_t used = strlen(out);
            int added = snprintf(out + used, sizeof(out) - used,
                "&nova_iso_generation=%" PRIu64, g_session->generation);
            if (added < 0 || (size_t)added >= sizeof(out) - used) {
                session_destroy(g_session); g_session = NULL;
                pthread_mutex_unlock(&g_lock); return NULL;
            }
        }
'''
    text = once(text, '        result = (*env)->NewStringUTF(env, out);', add+'        result = (*env)->NewStringUTF(env, out);', 'generation export')
    text = once(text, 'JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *vm, void *reserved) {', NATIVE_CLOSE+'\nJNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *vm, void *reserved) {', 'generation-checked shutdown')
    return text


def one(root: Path, path: str) -> Path:
    found = list(root.glob('smali*/'+path))
    if len(found) != 1: raise RuntimeError(f'{path}: expected one file, got {len(found)}')
    return found[0]


def apply(root: Path, report: Path | None = None) -> dict:
    # Obfuscated HTTP symbols are fail-closed pinned to the actual APK. No reflection guesses.
    checks = {
        'l31.smali': ['.field public final a:Lj21;', '.field public final d:I', '.field public final l:Ll31;', '.field public final f:Lf90;'],
        'j21.smali': ['.field public final a:Lzb0;'],
        'zb0.smali': ['.method public final toString()Ljava/lang/String;'],
    }
    for name, tokens in checks.items():
        text = one(root, name).read_text()
        if any(t not in text for t in tokens): raise RuntimeError('HTTP mapping changed: '+name)
    transforms = {
        'com/archos/filecorelibrary/webdav/WebdavFileEditor.smali': editor_text,
        'com/archos/filecorelibrary/StreamOverHttp$HttpSession.smali': session_text,
        'com/archos/mediacenter/video/player/BlurayIsoProxy.smali': proxy_text,
        'com/archos/mediacenter/video/player/Player.smali': player_text,
        'com/archos/medialib/AvosMediaPlayer.smali': release_text,
    }
    changes = [(one(root, path), fn(one(root, path).read_text())) for path, fn in transforms.items()]
    sardine = one(root, 'com/thegrizzlylabs/sardineandroid/impl/OkHttpSardine.smali')
    def release_put(body):
        return once(body, '.catch Ljava/io/IOException;', '.catch Ljava/lang/Throwable;', 'release sidecar in-flight on every failure')
    changes.append((sardine, replace_method(sardine.read_text(), 'put(Ljava/lang/String;Ljava/io/File;Ljava/lang/String;)V', release_put)))
    folder = one(root, 'com/archos/mediacenter/video/player/BlurayIsoProxy.smali').parent
    for name, text in [('NovaIsoSourceClose.smali', SOURCE_TASK), ('NovaIsoNativeClose.smali', NATIVE_TASK)]:
        p = folder/name
        if p.exists(): raise RuntimeError('Unexpected existing adapter '+name)
        changes.append((p,text))
    for p, text in changes: p.write_text(text)
    result = {'status':'PASS','scope':'WebDAV backend open, response diagnosis, ISO owner close, optional sidecar PUT',
              'localhost_request_parsed_once': True, 'range_validation_unchanged':True,
              'transient_open_max_attempts':3,'redirected403_refresh_per_origin_cooldown_seconds':30,
              'redirected403_max_distinct_offsets_per_cooldown':4,
              'credential_tls_and_url_query_unchanged':True,'native_10x_math_unchanged':True,
              'device_webdav_playback_verified':False}
    if report: report.write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__ == '__main__':
    p = argparse.ArgumentParser(); g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--smali', type=Path); g.add_argument('--iso', type=Path)
    p.add_argument('--report',type=Path); a=p.parse_args()
    if a.smali: print(json.dumps(apply(a.smali,a.report),indent=2))
    else:
        a.iso.write_text(iso_text(a.iso.read_text()))
        if a.report: a.report.write_text(json.dumps({'status':'PASS','scope':'ISO generation identity only'})+'\n')
