#!/usr/bin/env python3
"""NOVA global logs checkbox and Java log gate. Based on Always-new.

Log setting is persistent and defaults OFF. On first launch of this version,
legacy ON-by-default installs are migrated to OFF once. A one-byte MAP_SHARED private flag
is the single authority across Java, AVOS, transport, and :scanner processes.
No background polling or diagnostic thread is created by this control.
"""
from pathlib import Path
import argparse
import re
import xml.etree.ElementTree as ET

KEY = "nova_logs_enabled"
CLASS = "Lcom/archos/mediacenter/video/NovaGlobalLogs;"
MARK = "NOVA_GLOBAL_LOGS_TOGGLE_V1"


def one(s, old, new, label):
    n=s.count(old)
    if n!=1: raise RuntimeError(f"{label}: expected unique anchor, got {n}")
    return s.replace(old,new,1)


# This class uses one shared byte at files/nova_logs_enabled.bin. Its
# MappedByteBuffer allows all processes to see a toggle without any polling.
# A failed/absent map always means OFF (fail closed).
GATE_SMALI=r'''
.class public final Lcom/archos/mediacenter/video/NovaGlobalLogs;
.super Ljava/lang/Object;
.source "NOVA_GLOBAL_LOGS_TOGGLE_V1"

.field private static volatile flag:Ljava/nio/MappedByteBuffer;

.method private constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public static init(Landroid/content/Context;)V
    .locals 11
    :try_start_0
    invoke-virtual {p0}, Landroid/content/Context;->getFilesDir()Ljava/io/File;
    move-result-object v0
    new-instance v1, Ljava/io/File;
    const-string v2, "nova_logs_enabled.bin"
    invoke-direct {v1, v0, v2}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V
    new-instance v3, Ljava/io/RandomAccessFile;
    const-string v4, "rw"
    invoke-direct {v3, v1, v4}, Ljava/io/RandomAccessFile;-><init>(Ljava/io/File;Ljava/lang/String;)V
    # One-time v2 default-OFF migration: 1194 persisted ON implicitly.
    # Reset the shared file first, then persist the default and migration marker
    # synchronously. After this one-time migration, deliberate ON persists.
    invoke-static {p0}, Landroid/preference/PreferenceManager;->getDefaultSharedPreferences(Landroid/content/Context;)Landroid/content/SharedPreferences;
    move-result-object v0
    const-string v1, "nova_logs_default_off_v2_done"
    const/4 v2, 0x0
    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences;->getBoolean(Ljava/lang/String;Z)Z
    move-result v8
    if-nez v8, :nova_logs_default_off_done
    const-wide/16 v4, 0x0
    invoke-virtual {v3, v4, v5}, Ljava/io/RandomAccessFile;->seek(J)V
    invoke-virtual {v3, v2}, Ljava/io/RandomAccessFile;->write(I)V
    invoke-interface {v0}, Landroid/content/SharedPreferences;->edit()Landroid/content/SharedPreferences$Editor;
    move-result-object v9
    const-string v10, "nova_logs_enabled"
    invoke-interface {v9, v10, v2}, Landroid/content/SharedPreferences$Editor;->putBoolean(Ljava/lang/String;Z)Landroid/content/SharedPreferences$Editor;
    move-result-object v9
    const/4 v8, 0x1
    invoke-interface {v9, v1, v8}, Landroid/content/SharedPreferences$Editor;->putBoolean(Ljava/lang/String;Z)Landroid/content/SharedPreferences$Editor;
    move-result-object v9
    invoke-interface {v9}, Landroid/content/SharedPreferences$Editor;->commit()Z
    move-result v8
    if-nez v8, :nova_logs_default_off_done
    new-instance v8, Ljava/io/IOException;
    const-string v9, "Cannot persist NOVA logs default-off migration"
    invoke-direct {v8, v9}, Ljava/io/IOException;-><init>(Ljava/lang/String;)V
    throw v8
    :nova_logs_default_off_done
    invoke-virtual {v3}, Ljava/io/RandomAccessFile;->length()J
    move-result-wide v4
    const-wide/16 v6, 0x1
    cmp-long v8, v4, v6
    if-gez v8, :nova_flag_exists
    invoke-virtual {v3, v6, v7}, Ljava/io/RandomAccessFile;->setLength(J)V
    invoke-static {p0}, Landroid/preference/PreferenceManager;->getDefaultSharedPreferences(Landroid/content/Context;)Landroid/content/SharedPreferences;
    move-result-object v0
    const-string v1, "nova_logs_enabled"
    const/4 v2, 0x0
    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences;->getBoolean(Ljava/lang/String;Z)Z
    move-result v2
    const-wide/16 v4, 0x0
    invoke-virtual {v3, v4, v5}, Ljava/io/RandomAccessFile;->seek(J)V
    invoke-virtual {v3, v2}, Ljava/io/RandomAccessFile;->write(I)V
    :nova_flag_exists
    invoke-virtual {v3}, Ljava/io/RandomAccessFile;->getChannel()Ljava/nio/channels/FileChannel;
    move-result-object v0
    sget-object v1, Ljava/nio/channels/FileChannel$MapMode;->READ_WRITE:Ljava/nio/channels/FileChannel$MapMode;
    move-object v9, v3
    const-wide/16 v2, 0x0
    const-wide/16 v4, 0x1
    invoke-virtual/range {v0 .. v5}, Ljava/nio/channels/FileChannel;->map(Ljava/nio/channels/FileChannel$MapMode;JJ)Ljava/nio/MappedByteBuffer;
    move-result-object v0
    sput-object v0, Lcom/archos/mediacenter/video/NovaGlobalLogs;->flag:Ljava/nio/MappedByteBuffer;
    invoke-virtual {v9}, Ljava/io/RandomAccessFile;->close()V
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :nova_init_failed
    return-void
    :nova_init_failed
    move-exception v0
    const/4 v1, 0x0
    sput-object v1, Lcom/archos/mediacenter/video/NovaGlobalLogs;->flag:Ljava/nio/MappedByteBuffer;
    return-void
.end method

.method public static enabled()Z
    .locals 2
    sget-object v0, Lcom/archos/mediacenter/video/NovaGlobalLogs;->flag:Ljava/nio/MappedByteBuffer;
    if-eqz v0, :nova_disabled
    :try_start_0
    const/4 v1, 0x0
    invoke-virtual {v0, v1}, Ljava/nio/MappedByteBuffer;->get(I)B
    move-result v0
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :nova_disabled
    if-eqz v0, :nova_disabled
    const/4 v0, 0x1
    return v0
    :nova_disabled
    const/4 v0, 0x0
    return v0
.end method

.method public static update(Z)V
    .locals 3
    sget-object v0, Lcom/archos/mediacenter/video/NovaGlobalLogs;->flag:Ljava/nio/MappedByteBuffer;
    if-eqz v0, :nova_no_mapping
    const/4 v1, 0x0
    move v2, p0
    :try_start_0
    invoke-virtual {v0, v1, v2}, Ljava/nio/MappedByteBuffer;->put(IB)Ljava/nio/ByteBuffer;
    invoke-virtual {v0}, Ljava/nio/MappedByteBuffer;->force()Ljava/nio/MappedByteBuffer;
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :nova_write_failed
    # The output is gated through the same Log.i wrapper. This lets Android
    # runtime validation observe OFF->ON after the real Settings callback.
    # When OFF, wrapper returns without writing any logcat line.
    const-string v0, "NOVA_GLOBAL_LOGS_TEST"
    const-string v1, "ON_AFTER_APPLY"
    invoke-static {v0, v1}, Lcom/archos/mediacenter/video/NovaGlobalLogs;->i(Ljava/lang/String;Ljava/lang/String;)I
    move-result v0
    return-void
    :nova_write_failed
    move-exception v0
    new-instance v1, Ljava/lang/IllegalStateException;
    const-string v2, "Unable to update Nova diagnostic gate"
    invoke-direct {v1, v2, v0}, Ljava/lang/IllegalStateException;-><init>(Ljava/lang/String;Ljava/lang/Throwable;)V
    throw v1
    :nova_no_mapping
    new-instance v0, Ljava/lang/IllegalStateException;
    const-string v1, "Nova diagnostic gate was not initialized"
    invoke-direct {v0, v1}, Ljava/lang/IllegalStateException;-><init>(Ljava/lang/String;)V
    throw v0
.end method
'''


def wrappers(sigs):
    out=[]
    for name, params, ret in sorted(sigs):
        # Existing callsites use only primitive ints and object references;
        # no wide arguments. Unknown signatures are fatal, never skipped.
        tokens=re.findall(r'(?:\[*L[^;]+;|\[*[ZBCSIFJD])',params)
        if ''.join(tokens)!=params or any(x in ('J','D') for x in tokens):
            raise RuntimeError(f"unsupported Log signature: {name}({params}){ret}")
        if ret not in ('I','Z','Ljava/lang/String;'):
            raise RuntimeError(f"unsupported Log return: {name} -> {ret}")
        ps=", ".join(f"p{i}" for i in range(len(tokens)))
        out.append(f'''
.method public static {name}({params}){ret}
    .locals 1
    invoke-static {{}}, {CLASS}->enabled()Z
    move-result v0
    if-eqz v0, :nova_off
    invoke-static {{{ps}}}, Landroid/util/Log;->{name}({params}){ret}
    move-result-object v0
    return-object v0
    :nova_off
    const/4 v0, 0x0
    return-object v0
.end method
''' if ret.startswith('L') else f'''
.method public static {name}({params}){ret}
    .locals 1
    invoke-static {{}}, {CLASS}->enabled()Z
    move-result v0
    if-eqz v0, :nova_off
    invoke-static {{{ps}}}, Landroid/util/Log;->{name}({params}){ret}
    move-result v0
    return v0
    :nova_off
    const/4 v0, 0x0
    return v0
.end method
''')
    return '\n'.join(out)



def gate_logback(root:Path):
    """Stop SLF4J/Logback event creation and appender work while OFF.

    This is not only an output filter: the three Logback filterAndLog()
    functions are exited before event creation, and is*Enabled methods
    become false in the OFF state so callers skip constructing arguments.
    """
    candidates=list(root.glob("smali*/ch/qos/logback/classic/Logger.smali"))
    if len(candidates)!=1:
        raise RuntimeError("Logback Logger not uniquely located")
    file=candidates[0]
    src=file.read_text()
    regex=re.compile(r'(?ms)^\.method [^\n]+\n.*?^\.end method')
    count=0
    def patch_method(m):
        nonlocal count
        text=m.group(0)
        name=text.splitlines()[0]
        is_filter=" filterAndLog_" in name
        is_call=" callAppenders(" in name
        is_enabled=bool(re.search(r' is(?:Trace|Debug|Info|Warn|Error)Enabled\(',name))
        if not (is_filter or is_call or is_enabled):
            return text
        # Any zero-local method aliases v0 to p0. The injected gate uses v0,
        # so reserve a local for ALL guarded methods, including callAppenders
        # and filterAndLog, not only is*Enabled overloads.
        if ".locals 0" in text:
            text=text.replace(".locals 0",".locals 1",1)
        # Insert after any method annotations. No instruction may precede
        # a .annotation block in a well-formed method.
        pos=text.rfind(".end annotation")
        body_start=pos+len(".end annotation") if pos>=0 else text.index("\n",text.index(".locals"))+1
        code_match=re.search(r'(?m)^    (?!\.|#)(?:iget-|sget-|const|invoke-|move-|new-|if-|return)',text[body_start:])
        if not code_match:raise RuntimeError("Logback no first opcode: "+name)
        index=body_start+code_match.start()
        guard=(f"    invoke-static {{}}, {CLASS}->enabled()Z\n"
               "    move-result v0\n"
               "    if-nez v0, :nova_global_logback_on\n"
               +("    const/4 v0, 0x0\n    return v0\n" if is_enabled else "    return-void\n")
               +"    :nova_global_logback_on\n")
        count+=1
        return text[:index]+guard+text[index:]
    src=regex.sub(patch_method,src)
    if count < 18:raise RuntimeError("Expected Logback 3 writers + enabled variants, found "+str(count))
    file.write_text(src)
    return count

def smali(root:Path):
    prefs=root/'res/xml/preferences_video.xml'
    s=prefs.read_text()
    anchor='<PreferenceScreen android:title="@string/preferences_video_licenses" android:key="preferences_video_licences" app:iconSpaceReserved="false" />'
    row='<CheckBoxPreference android:persistent="true" android:title="日志" android:key="nova_logs_enabled" android:defaultValue="false" app:iconSpaceReserved="false" />'
    s=one(s,anchor,anchor+'\n        '+row,"Settings: exactly below licenses")
    prefs.write_text(s)
    ET.fromstring(s)
    application=next(iter(root.glob('smali*/com/archos/mediacenter/video/CustomApplication.smali')),None)
    if application is None:raise RuntimeError("CustomApplication missing")
    a=application.read_text()
    anchor='    invoke-super {p0, p1}, Landroid/app/Application;->attachBaseContext(Landroid/content/Context;)V'
    a=one(a,anchor,anchor+f'\n    invoke-static {{p0}}, {CLASS}->init(Landroid/content/Context;)V\n',
          'initialize gate in ALL app processes before Sentry and playback')
    application.write_text(a)

    common=next(iter(root.glob('smali*/com/archos/mediacenter/video/utils/VideoPreferencesCommon.smali')),None)
    if common is None:raise RuntimeError("VideoPreferencesCommon missing")
    t=common.read_text()
    trigger='.method public onSharedPreferenceChanged(Landroid/content/SharedPreferences;Ljava/lang/String;)V\n    .locals 5'
    hook=f'''
    const-string v0, "nova_logs_enabled"
    invoke-virtual {{p2, v0}}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v0
    if-eqz v0, :nova_logs_other_preferences
    const/4 v0, 0x0
    invoke-interface {{p1, p2, v0}}, Landroid/content/SharedPreferences;->getBoolean(Ljava/lang/String;Z)Z
    move-result v0
    invoke-static {{v0}}, {CLASS}->update(Z)V
    return-void
    :nova_logs_other_preferences
'''
    t=one(t,trigger,trigger+'\n'+hook,"onSharedPreferenceChanged")
    common.write_text(t)

    # Route ALL Android Log callsites (including libraries' SLF4J backends)
    # through the SAME application gate. Do not change non-Log business APIs.
    pat=re.compile(r'Landroid/util/Log;->([A-Za-z][A-Za-z0-9]*)\(([^)]*)\)([VZBCSIJDF]|L[^;]+;)')
    signatures=set()
    num=0
    for p in root.glob('smali*/**/*.smali'):
        text=p.read_text(errors='ignore')
        matches=list(pat.finditer(text))
        if not matches:continue
        for m in matches:
            # getStackTraceString is an exception-formatting utility, not a
            # logging output; preserve its business semantics when OFF.
            if m.group(1)!="getStackTraceString":
                signatures.add((m.group(1),m.group(2),m.group(3)))
        text,n=pat.subn(lambda m: (CLASS+'->'+m.group(1)+'('+m.group(2)+')'+m.group(3))
                         if m.group(1)!="getStackTraceString" else m.group(0),text)
        if n: p.write_text(text)
        num+=n
    if num<100:raise RuntimeError(f"Only {num} Android Log callsites: expected >=100")
    # Required by the device-side UI smoke probe in update(Z), irrespective
    # of the upstream APK's existing Android Log.i signatures.
    signatures.add(("i", "Ljava/lang/String;Ljava/lang/String;", "I"))

    # Put new file inside an already-existing small DEX, avoiding early-app
    # startup and main multidex method-ref limits.
    smalis=sorted(root.glob('smali_classes*/com/archos/mediacenter/video/'))
    out=smalis[-1] if smalis else application.parent
    dest=out/'NovaGlobalLogs.smali'
    if dest.exists():raise RuntimeError("NovaGlobalLogs already present")
    dest.write_text(GATE_SMALI+wrappers(signatures))
    logback_count=gate_logback(root)
    print(f'{MARK}=PASS UI after licenses; AndroidLogCallsites={num}; overloads={len(signatures)}; LogbackGates={logback_count}')


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--smali',required=True,type=Path)
    args=ap.parse_args()
    smali(args.smali)
if __name__=='__main__':main()
