#!/usr/bin/env python3
"""NOVA 1074: move last-reference subtitle EGL teardown off UI/stream threads.

Registry remains sole lifetime owner; no earlier free, no forced EGL cancel.
A single process-lifetime worker owns a bounded FIFO of retired engines.
If worker init or queueing fails, synchronous fallback preserves correctness.
"""
import argparse
from pathlib import Path

DECL=r'''
/* NOVA_1074_SUB_EGL_ASYNC: process-lifetime bounded teardown worker.
 * Never access or reuse a retired SUB_ENGINE after enqueuing it. */
#include <time.h>
#include <stdint.h>
#include <sys/syscall.h>
#include <unistd.h>
#define NOVA_1074_QCAP 32
typedef struct {
    SUB_ENGINE *eng;
    sub_engine_destroy_fn fn;
    uint64_t id;
    int64_t queued_ms;
} NOVA1074Job;
static NOVA1074Job nova1074_jobs[NOVA_1074_QCAP];
static pthread_mutex_t nova1074_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t nova1074_cond=PTHREAD_COND_INITIALIZER;
static pthread_once_t nova1074_once=PTHREAD_ONCE_INIT;
static int nova1074_worker_ok=0;
static int nova1074_head=0,nova1074_count=0;
static uint64_t nova1074_seq=0;
static int64_t nova1074_mono_ms(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC,&t);
    return ((int64_t)t.tv_sec)*1000+t.tv_nsec/1000000;
}
static void *nova1074_worker(void *unused) {
    (void)unused;
    REG_LOGW("NOVA_1074_EGL_WORKER_START tid=%ld",(long)syscall(SYS_gettid));
    for (;;) {
        NOVA1074Job job;
        pthread_mutex_lock(&nova1074_lock);
        while(nova1074_count==0)
            pthread_cond_wait(&nova1074_cond,&nova1074_lock);
        job=nova1074_jobs[nova1074_head];
        nova1074_head=(nova1074_head+1)%NOVA_1074_QCAP;
        --nova1074_count;
        pthread_mutex_unlock(&nova1074_lock);
        int64_t start=nova1074_mono_ms();
        REG_LOGW("NOVA_1074_EGL_DESTROY_BEGIN seq=%llu queueMs=%lld"
                 " tid=%ld", (unsigned long long)job.id,
                 (long long)(start-job.queued_ms),(long)syscall(SYS_gettid));
        job.fn(job.eng); /* May block indefinitely in EGL pthread_join, but not UI. */
        REG_LOGW("NOVA_1074_EGL_DESTROY_END seq=%llu elapsedMs=%lld",
                 (unsigned long long)job.id,
                 (long long)(nova1074_mono_ms()-start));
    }
    return NULL;
}
static void nova1074_start_worker(void) {
    pthread_t t;
    int rc=pthread_create(&t,NULL,nova1074_worker,NULL);
    if(rc==0) {
        pthread_detach(t);
        nova1074_worker_ok=1;
    } else {
        REG_LOGW("NOVA_1074_EGL_WORKER_FAIL rc=%d",rc);
    }
}
static void nova1074_retire_engine(SUB_ENGINE *eng,sub_engine_destroy_fn fn) {
    if(!fn)return;
    pthread_once(&nova1074_once,nova1074_start_worker);
    if(nova1074_worker_ok) {
        pthread_mutex_lock(&nova1074_lock);
        if(nova1074_count < NOVA_1074_QCAP) {
            int idx=(nova1074_head+nova1074_count)%NOVA_1074_QCAP;
            uint64_t id=++nova1074_seq;
            int64_t now=nova1074_mono_ms();
            nova1074_jobs[idx]=(NOVA1074Job){.eng=eng,.fn=fn,.id=id,.queued_ms=now};
            ++nova1074_count;
            int depth=nova1074_count;
            pthread_cond_signal(&nova1074_cond);
            pthread_mutex_unlock(&nova1074_lock);
            REG_LOGW("NOVA_1074_EGL_RETIRE_ASYNC seq=%llu depth=%d callerTid=%ld",
                     (unsigned long long)id,depth,(long)syscall(SYS_gettid));
            return;
        }
        pthread_mutex_unlock(&nova1074_lock);
        REG_LOGW("NOVA_1074_EGL_QUEUE_FULL count=%d fallback=sync",NOVA_1074_QCAP);
    }
    int64_t start=nova1074_mono_ms();
    REG_LOGW("NOVA_1074_EGL_RETIRE_SYNC_FALLBACK tid=%ld",
             (long)syscall(SYS_gettid));
    fn(eng);
    REG_LOGW("NOVA_1074_EGL_SYNC_END elapsedMs=%lld",
             (long long)(nova1074_mono_ms()-start));
}
'''

def replace_exact(s,a,b,description):
    count=s.count(a)
    if count!=1:raise RuntimeError(f"{description}: anchor count {count}")
    return s.replace(a,b,1)

def patch(root):
    reg=root/"Source/sub_engine_registry.c"
    s=reg.read_text()
    s=replace_exact(s,"static REG_ENTRY *s_current = NULL;", "static REG_ENTRY *s_current = NULL;\n"+DECL,
                    "static registry definitions")
    # Both zero-ref paths -- never touch engine or fn after handoff.
    if s.count("if (destroy) destroy(eng);")!=1:
        raise RuntimeError("unpublished engine destruction anchor")
    s=s.replace("if (destroy) destroy(eng);",
                "if (destroy) nova1074_retire_engine(eng,destroy);",1)
    if s.count("if (fn) fn(eng);")!=2:
        raise RuntimeError("registry zero-ref destruction locations changed")
    s=s.replace("if (fn) fn(eng);","if (fn) nova1074_retire_engine(eng,fn);")
    reg.write_text(s)
    # EGL thread teardown phase evidence: no locks/logs around the join
    egl=root/"Source/sub_render_gl.c"
    s=egl.read_text()
    s=replace_exact(s,"#include <time.h>","#include <time.h>\n#include <sys/syscall.h>","egl headers")
    s=replace_exact(s,"    pthread_join(r->thread, NULL);\n    // The engine is already destroyed",
      '    struct timespec nova1074_t0,nova1074_t1;\n'
      '    clock_gettime(CLOCK_MONOTONIC,&nova1074_t0);\n'
      '    serprintf("NOVA_1074_EGL_JOIN_BEGIN tid=%ld\\\\n",(long)syscall(SYS_gettid));\n'
      '    pthread_join(r->thread, NULL);\n'
      '    clock_gettime(CLOCK_MONOTONIC,&nova1074_t1);\n'
      '    long long nova1074_join_ms=((long long)nova1074_t1.tv_sec-nova1074_t0.tv_sec)*1000+\n'
      '       (nova1074_t1.tv_nsec-nova1074_t0.tv_nsec)/1000000;\n'
      '    serprintf("NOVA_1074_EGL_JOIN_END elapsedMs=%lld\\\\n",nova1074_join_ms);\n'
      '    // The engine is already destroyed',"egl pthread_join")
    egl.write_text(s)
    print("NOVA_1074_SUBTITLE_ASYNC_PATCH=PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--native",required=True,type=Path)
    patch(p.parse_args().native)
