#!/usr/bin/env python3
"""Run1133: session-driven, fail-closed diagnostics. Apply after ALL native patches.
Normal playback: no diagnostics worker, sys/proc scan, logger thread, or counters.
ADB explicit broadcast: opt in; auto expiration (<=900s); STOP immediately OFF.
No changes to media/transport/seek decision paths.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re

MARKER="NOVA_GLOBAL_LOGS_TOGGLE_V1"
GATE_C=Path("iso/nova_global_gate.c")
GATE_HELPER=r'''
/* NOVA_GLOBAL_LOGS_TOGGLE_V1. All diagnostic writes share a 1-byte
 * mmap flag. OFF performs only an atomic memory read: no filesystem,
 * sampling, sysprop, or background listener/polling. */
#include "nova_global_flag.h"
static inline int nova_diag_on(void) {
    return nova_global_log_enabled();
}
'''

AVOS_LOG=r'''
#define NOVA_DIAG_LOG_IMPL 1
#include "log.h"
#include <android/log.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
/* NOVA_GLOBAL_LOGS_TOGGLE_V1: direct logcat without any pipe reader. */
#ifdef DEBUG_MSG
static const char *nova_log_tag="avos";
void LOG_open(void) {}
void LOG_open_name(const char *name) { if(name) nova_log_tag=name; }
void LOG_close(void) {}
int vserprintf(const char *fmt,va_list args){
    return nova_diag_on()?__android_log_vprint(ANDROID_LOG_DEBUG,nova_log_tag,fmt,args):0;
}
int serprintf(const char *fmt,...){
    if(!nova_diag_on())return 0;
    va_list args;
    va_start(args,fmt);
    int rc=vserprintf(fmt,args);
    va_end(args);
    return rc;
}
int serprintf_record(const char *fmt,...){
    if(!nova_diag_on())return 0;
    va_list args;
    va_start(args,fmt);
    int rc=vserprintf(fmt,args);
    va_end(args);
    return rc;
}
#endif
'''


def once(s,a,b,label):
    n=s.count(a)
    if n!=1: raise RuntimeError(f"{label}: expected one anchor, found {n}")
    return s.replace(a,b,1)

def rewrite_counter_lines(src):
    """Gate diagnostic-owned atomic writes, including multi-line arguments."""
    pattern=re.compile(
        r'(?m)^([ \t]*)(__atomic_(?:fetch_add|add_fetch|store_n|exchange_n)\s*'
        r'\(\s*&(?:s|p|nova_diag_s)->'
        r'(?:nova_diag_|nova_final_|nova_seek_diag_|nova_seek_engine_loops)[^;]*;)')
    return pattern.sub(lambda m: m.group(1)+'if(nova_diag_on()) '+m.group(2),src)

def guard_owned_snippets(s):
    """Guard the entire stateful AVOS diagnostic tick and Seek stage observer."""
    s=once(s,'static void nova_avdiag_tick(STREAM *s)\n{\n    if (!s) return;',
           'static void nova_avdiag_tick(STREAM *s)\n{\n    if (!s || !nova_diag_on()) return;',
           'AV diagnostic sampler')
    s=once(s,'static void nova_seek_diag_v2(STREAM *s, int phase)\n{\n',
           'static void nova_seek_diag_v2(STREAM *s, int phase)\n{\n    if(!nova_diag_on()) return;\n',
           'Seek-stage observer')
    return s


def native(root:Path,transport:Path,blackbox:Path):
    header=root/"Include/log.h"
    h=header.read_text()
    shared=root/"Include/nova_global_flag.h"
    shared.write_text(Path("iso/nova_global_flag.h").read_text())
    (root/"Include/nova_global_gate_impl.inc").write_text(GATE_C.read_text())
    guard=GATE_HELPER+r'''
/* AVOS log arguments must not be evaluated in OFF state. */
#if defined(CONFIG_ANDROID) && defined(DEBUG_MSG) && !defined(NOVA_DIAG_LOG_IMPL)
#define serprintf(...) (nova_diag_on() ? (serprintf)(__VA_ARGS__) : 0)
#define serprintf_record(...) (nova_diag_on() ? (serprintf_record)(__VA_ARGS__) : 0)
#endif
'''
    header.write_text(once(h,"#endif // _LOG_H_",guard+"\n#endif // _LOG_H_","AVOS log gate"))
    writer=root/"Source/log_android.c"
    writer.write_text('#include "../Include/nova_global_gate_impl.inc"\n'+AVOS_LOG)
    # 50ms existing controller is business; only optional sampler guarded.
    video=root/"Source/stream_video.c"
    v=guard_owned_snippets(video.read_text())
    # The diagnostic worker is *not* spawned at normal playback startup.
    v=once(v,'    pthread_once(&nova_60fps_monitor_once,nova_60fps_start_sampler);',
           '    /* '+MARKER+': monitor is created only during an active session. */',
           'remove permanent 60fps worker')
    v=once(v,'static pthread_once_t nova_60fps_monitor_once=PTHREAD_ONCE_INIT;',
           '/* monitor state lives before worker function */',
           'replace process lifetime monitor once')
    v=once(v,'static void *nova_60fps_sys_sampler(void *unused)',
           'static volatile int nova_60fps_monitor_started=0;\nstatic void *nova_60fps_sys_sampler(void *unused)',
           'monitor worker state declared before use')
    v=once(v,'static void nova_60fps_start_sampler(void)\n{\n    pthread_t id;\n    if(!pthread_create(&id,NULL,nova_60fps_sys_sampler,NULL))\n        pthread_detach(id);\n}',
           '''static void nova_60fps_start_sampler(void)
{
    if(!nova_diag_on()) return;
    int empty=0;
    if(!__atomic_compare_exchange_n(&nova_60fps_monitor_started,&empty,1,0,
                                    __ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return;
    pthread_t id;
    if(!pthread_create(&id,NULL,nova_60fps_sys_sampler,NULL))
        pthread_detach(id);
    else __atomic_store_n(&nova_60fps_monitor_started,0,__ATOMIC_RELEASE);
}''','60fps worker on demand')
    v=once(v,'    while(1){\n        struct timespec when;',
           '    while(nova_diag_on()){\n        struct timespec when;',
           '60fps stop after session')
    v=once(v,'        nanosleep(&pause,NULL);\n    }\n    return NULL;\n}\n/* monitor state lives before worker function */',
           '        nanosleep(&pause,NULL);\n    }\n    __atomic_store_n(&nova_60fps_monitor_started,0,__ATOMIC_RELEASE);\n    return NULL;\n}\n/* monitor state lives before worker function */',
           '60fps exit reset')
    # A currently playing video can start the sampler on next native 50ms tick.
    v=once(v,'        nova_avdiag_tick(s);',
           '        if(nova_diag_on()) nova_60fps_start_sampler();\n        nova_avdiag_tick(s);',
           '60fps lazy activate')
    v=once(v,'void nova_60fps_note_late(void) {\n',
           'void nova_60fps_note_late(void) {\n    if(!nova_diag_on()) return;\n',
           '60fps late count')
    v=rewrite_counter_lines(v)
    v=v.replace('nova_1073_external(s->cbe ? 21 : 20,',
                'if(nova_diag_on()) nova_1073_external(s->cbe ? 21 : 20,')
    video.write_text(v)
    # Guard diagnostic-only computation around buffer/seek and codec probes,
    # without changing the real av_read_frame, sfdec_* or playback calls.
    for name in ("stream_parser_ffmpeg.c","stream_sink_audio.c","codec_sfdec2.c"):
        p=root/"Source"/name
        s=p.read_text()
        s=rewrite_counter_lines(s)
        if name=="stream_parser_ffmpeg.c":
            s=once(s,'static int nova_direct_init_fail(NOVA_RAW_PREFETCH *raw, const char *stage, int ret)\n{\n    int saved_errno=errno;',
                   'static int nova_direct_init_fail(NOVA_RAW_PREFETCH *raw, const char *stage, int ret)\n{\n    int saved_errno=errno;\n    if(!nova_diag_on()) { errno=saved_errno; return ret; }',
                   'DirectTransport failed-init /proc diagnostics')
            s=s.replace('if(result==AVERROR(ENOMEM) &&\n               strstr(s->src_query,"nova_iso=1")){',
                        'if(nova_diag_on() && result==AVERROR(ENOMEM) &&\n               strstr(s->src_query,"nova_iso=1")){')
            s=once(s,'static void nova_raw_log_locked(NOVA_RAW_PREFETCH *raw)\n{\n',
                   'static void nova_raw_log_locked(NOVA_RAW_PREFETCH *raw)\n{\n    if(!nova_diag_on())return;\n',
                   'RAW diagnostic sampler')
            s=once(s,'    pthread_once(&nova_1073_bridge_once,nova_1073_bridge_init);',
                     '    if(!nova_diag_on())return;\n    pthread_once(&nova_1073_bridge_once,nova_1073_bridge_init);',
                     'no lazy dlopen while OFF')
            for part in ('10,want,0','11,want,got',
                         '40,(int64_t)(fmt->pb?avio_tell(fmt->pb):-1),0',
                         '41,(int64_t)(fmt->pb?avio_tell(fmt->pb):-1),result'):
                s=s.replace('nova_1073_external('+part+');',
                            'if(nova_diag_on()) nova_1073_external('+part+');')
        if name=="codec_sfdec2.c":
            s=s.replace('if(clock_gettime(CLOCK_THREAD_CPUTIME_ID,\n                                 &nova_60fps_renderer_cpu_ts)==0)',
                        'if(nova_diag_on() && clock_gettime(CLOCK_THREAD_CPUTIME_ID,\n                                 &nova_60fps_renderer_cpu_ts)==0)')
            s=once(s,"void nova_sfdec2_pool_owners_report(STREAM *s)\n{\n",
                   "void nova_sfdec2_pool_owners_report(STREAM *s)\n{\n    if(!nova_diag_on())return;\n",
                   "pool owner diagnostics")
        p.write_text(s)
    # Transport logger and blackbox use the same process-wide native session.
    t=transport.read_text()
    t=once(t,'#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)\n#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)',
      '''/* NOVA_1133_ZERO_IDLE_DIAG_V1: all app telemetry requires ADB START. */
extern int nova_diag_gate_on(void);
#define LOGI(...) do { if(nova_diag_gate_on()) __android_log_print(ANDROID_LOG_INFO,TAG,__VA_ARGS__); } while(0)
#define LOGE(...) do { if(nova_diag_gate_on()) __android_log_print(ANDROID_LOG_ERROR,TAG,__VA_ARGS__); } while(0)''',
      "transport printf")
    # 60fps IO/CPU evidence is diagnostic ONLY. Avoid CPU sampling and
    # warehouse locking unless an explicit capture session is active.
    lite=transport.parent/"nova_literange4.inc"
    l=lite.read_text()
    a=l.index("    /* NOVA_60FPS_W2_IO_CPU_V1:")
    end=l.index("    /* W=2 only, never the obsolete",a)
    segment=l[a:end]
    if "received,delivered);" not in segment:
        raise RuntimeError("60fps IO evidence delimiters changed")
    l=l[:a]+"    if(nova_diag_gate_on()){\n"+segment+"    }\n"+l[end:]
    lite.write_text(l)
    t=t.replace("nova_diag_gate_on()", "nova_global_log_enabled()")
    transport.write_text(t)
    b=blackbox.read_text()
    b=once(b,'    while(1){\n        struct timespec delay={.tv_sec=1,.tv_nsec=0};',
           '    while(nova_diag_gate_on()){\n        struct timespec delay={.tv_sec=1,.tv_nsec=0};',
           "blackbox ON only")
    b=once(b,'        nanosleep(&delay,NULL);\n        uint64_t gen=',
           '        nanosleep(&delay,NULL);\n        if(!nova_diag_gate_on()) break;\n        uint64_t gen=',
           "blackbox immediate skip after sleep")
    b=once(b,'    return NULL;\n}\nstatic void nova_bb_start_thread(void)',
           '    __atomic_store_n(&g_bb_watch_started,0,__ATOMIC_RELEASE);\n    __atomic_store_n(&g_bb_armed,0,__ATOMIC_RELEASE);\n    return NULL;\n}\nstatic void nova_bb_start_thread(void)',
           "blackbox release worker")
    b=once(b,'    pthread_t watcher;\n    int rc=pthread_create(&watcher,NULL,nova_bb_watchdog,NULL);',
           '''    if(!nova_diag_gate_on())return;
    int empty=0;
    if(!__atomic_compare_exchange_n(&g_bb_watch_started,&empty,1,0,
                                    __ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return;
    pthread_t watcher;
    int rc=pthread_create(&watcher,NULL,nova_bb_watchdog,NULL);''',
           "blackbox create only ON")
    b=once(b,'        __atomic_store_n(&g_bb_watch_started,1,__ATOMIC_RELEASE);\n    }else\n        LOGE("NOVA_1073_BB_WATCHDOG_START_FAIL rc=%d",rc);',
           '    }else {\n        __atomic_store_n(&g_bb_watch_started,0,__ATOMIC_RELEASE);\n        LOGE("NOVA_1073_BB_WATCHDOG_START_FAIL rc=%d",rc);\n    }',
           "blackbox start state")
    b=once(b,'    __atomic_store_n(&g_bb_armed,1,__ATOMIC_RELEASE);\n    __atomic_store_n(&g_bb_mode,mode,__ATOMIC_RELEASE);\n    pthread_once(&g_bb_watch_once,nova_bb_start_thread);',
           '    __atomic_store_n(&g_bb_armed,nova_diag_gate_on(),__ATOMIC_RELEASE);\n    __atomic_store_n(&g_bb_mode,mode,__ATOMIC_RELEASE);\n    nova_bb_start_thread();',
           "blackbox arm")
    b=once(b,'static void nova_bb_fault(int kind,uint64_t gen,int64_t a,int64_t b)\n{\n',
           'static void nova_bb_fault(int kind,uint64_t gen,int64_t a,int64_t b)\n{\n    if(!nova_diag_gate_on())return;\n',
           'blackbox anomaly gate')
    b=once(b,'static void nova_bb_event(int kind,uint64_t gen,int64_t a,int64_t b)\n{\n    if(!__atomic_load_n(&g_bb_armed,__ATOMIC_ACQUIRE))return;',
           'static void nova_bb_event(int kind,uint64_t gen,int64_t a,int64_t b)\n{\n    if(!nova_diag_gate_on() || !__atomic_load_n(&g_bb_armed,__ATOMIC_ACQUIRE))return;',
           "blackbox event")
    b=b.replace('    if(id<0 || id>=NOVA_BB_PHASES ||',
                '    if(!nova_diag_gate_on() || id<0 || id>=NOVA_BB_PHASES ||')
    b=once(b,'static void nova_bb_arm(int mode)\n{',
           '''void nova_bb_on_diag_start(void)
{
    if(!nova_diag_gate_on())return;
    __atomic_store_n(&g_bb_armed,1,__ATOMIC_RELEASE);
    __atomic_store_n(&g_bb_first_fault,0,__ATOMIC_RELEASE);
    __atomic_store_n(&g_bb_freeze_pending,0,__ATOMIC_RELEASE);
    nova_bb_start_thread();
}
static void nova_bb_arm(int mode)
{''',
           "blackbox explicit activation")
    b=once(b,'void nova_transport_diag_external(int kind,int64_t amount,int rc)\n{\n',
           'void nova_transport_diag_external(int kind,int64_t amount,int rc)\n{\n    if(!nova_diag_gate_on())return;\n',
           'AVOS bridge OFF')
    b=b.replace("nova_diag_gate_on()", "nova_global_log_enabled()")
    blackbox.write_text(b)
    # Global gate is in a separate compilation unit shared by transport.
    if not GATE_C.is_file():raise RuntimeError("Global gate native C missing")
    from strict_idle_hotpaths_1133 import patch as strict_1133_hotpaths
    strict_1133_hotpaths(root)
    print(MARKER+"=PASS native")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--native",required=True,type=Path)
    p.add_argument("--transport",required=True,type=Path)
    a=p.parse_args()
    native(a.native,a.transport,a.transport.parent/"nova_iso_blackbox.inc")
