#!/usr/bin/env python3
"""NOVA global logs checkbox and Java log gate. Based on Always-new.

Log setting is persistent and defaults ON. A one-byte MAP_SHARED private flag
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
    invoke-virtual {v3}, Ljava/io/RandomAccessFile;->length()J
    move-result-wide v4
    const-wide/16 v6, 0x1
    cmp-long v8, v4, v6
    if-gez v8, :nova_flag_exists
    invoke-virtual {v3, v6, v7}, Ljava/io/RandomAccessFile;->setLength(J)V
    invoke-static {p0}, Landroid/preference/PreferenceManager;->getDefaultSharedPreferences(Landroid/content/Context;)Landroid/content/SharedPreferences;
    move-result-object v0
    const-string v1, "nova_logs_enabled"
    const/4 v2, 0x1
    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences;->getBoolean(Ljava/lang/String;Z)Z
    move-result v2
    const-wide/16 v4, 0x0
    invoke-virtual {v3, v4, v5}, Ljava/io/RandomAccessFile;->seek(J)V
    invoke-virtual {v3, v2}, Ljava/io/RandomAccessFile;->write(I)V
    :nova_flag_exists
    invoke-virtual {v3}, Ljava/io/RandomAccessFile;->getChannel()Ljava/nio/channels/FileChannel;
    move-result-object v0
    sget-object v1, Ljava/nio/channels/FileChannel$MapMode;->READ_WRITE:Ljava/nio/channels/FileChannel$MapMode;
    const-wide/16 v2, 0x0
    const-wide/16 v4, 0x1
    invoke-virtual/range {v0 .. v5}, Ljava/nio/channels/FileChannel;->map(Ljava/nio/channels/FileChannel$MapMode;JJ)Ljava/nio/MappedByteBuffer;
    move-result-object v0
    sput-object v0, Lcom/archos/mediacenter/video/NovaGlobalLogs;->flag:Ljava/nio/MappedByteBuffer;
    invoke-virtual {v3}, Ljava/io/RandomAccessFile;->close()V
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


def smali(root:Path):
    prefs=root/'res/xml/preferences_video.xml'
    s=prefs.read_text()
    anchor='<PreferenceScreen android:title="@string/preferences_video_licenses" android:key="preferences_video_licences" app:iconSpaceReserved="false" />'
    row='<CheckBoxPreference android:persistent="true" android:title="日志" android:key="nova_logs_enabled" android:defaultValue="true" app:iconSpaceReserved="false" />'
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
    const/4 v0, 0x1
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
        for m in matches:signatures.add((m.group(1),m.group(2),m.group(3)))
        text,n=pat.subn(lambda m:CLASS+'->'+m.group(1)+'('+m.group(2)+')'+m.group(3),text)
        if n: p.write_text(text)
        num+=n
    if num<100:raise RuntimeError(f"Only {num} Android Log callsites: expected >=100")

    # Put new file inside an already-existing small DEX, avoiding early-app
    # startup and main multidex method-ref limits.
    smalis=sorted(root.glob('smali_classes*/com/archos/mediacenter/video/'))
    out=smalis[-1] if smalis else application.parent
    dest=out/'NovaGlobalLogs.smali'
    if dest.exists():raise RuntimeError("NovaGlobalLogs already present")
    dest.write_text(GATE_SMALI+wrappers(signatures))
    print(f'{MARK}=PASS UI after licenses; AndroidLogCallsites={num}; overloads={len(signatures)}')


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--smali',required=True,type=Path)
    args=ap.parse_args()
    smali(args.smali)
if __name__=='__main__':main()
