#!/usr/bin/env python3
"""NOVA Shared42 ownership audit, activated only on page-allocation failures.

Counts the physical 2048 x 64KiB pages by owner and checks free-stack
integrity. No network, Range, HTTP403, or page ownership rule is modified.
"""
import argparse
from pathlib import Path

def once(s,a,b,label):
    n=s.count(a)
    if n!=1:raise RuntimeError(f"{label}: expected 1 anchor, got {n}")
    return s.replace(a,b,1)

AUDIT=r'''
/* Snapshot is only called on ENOMEM, and only emitted for the first three
 * and each 20th event. Keep diagnostics independent from AVOS queue locks. */
static void nova_wh_diag_v2(nova_shared_warehouse *w,const char *reason)
{
    static unsigned failure_count;
    unsigned event=__atomic_add_fetch(&failure_count,1u,__ATOMIC_RELAXED);
    if(!w || (event>3u && event%20u!=0u))return;
    int free_pages=0,stage=0,raw=0,bad=0,free_stack_bad=0;
    int stage_bytes=0,raw_bytes=0,raw_zero=0,stage_zero=0;
    uint8_t on_stack[NOVA_WH_PAGES]={0};
    pthread_mutex_lock(&w->lock);
    free_pages=w->free_count;
    if(free_pages<0 || free_pages>(int)NOVA_WH_PAGES)free_stack_bad++;
    int safe_free=free_pages;
    if(safe_free<0)safe_free=0;
    if(safe_free>(int)NOVA_WH_PAGES)safe_free=(int)NOVA_WH_PAGES;
    for(int i=0;i<safe_free;i++){
        int n=w->free_stack[i];
        if(n<0 || n>=(int)NOVA_WH_PAGES || on_stack[n]){
            free_stack_bad++;
            continue;
        }
        on_stack[n]=1;
    }
    int mismatch=0;
    for(int i=0;i<(int)NOVA_WH_PAGES;i++){
        nova_wh_page *p=&w->pages[i];
        if(p->state==NOVA_WH_FREE){
            if(!on_stack[i])mismatch++;
        } else if(p->state==NOVA_WH_STAGE){
            stage++;
            stage_bytes+=p->length;
            if(p->length==0)stage_zero++;
            if(on_stack[i])mismatch++;
        } else if(p->state==NOVA_WH_RAW){
            raw++;
            raw_bytes+=p->length;
            if(p->length==0)raw_zero++;
            if(on_stack[i])mismatch++;
        } else {
            bad++;
            if(on_stack[i])mismatch++;
        }
    }
    pthread_mutex_unlock(&w->lock);
    LOGE("NOVA_WH_POOL_AUDIT_V2: why=%s sample=%u free=%d stagePages=%d rawPages=%d badPages=%d accounted=%d total=%d freeStackErrors=%d membershipMismatches=%d stageBytes=%d rawBytes=%d stageZero=%d rawZero=%d",
         reason,event,free_pages,stage,raw,bad,
         free_pages+stage+raw+bad,(int)NOVA_WH_PAGES,
         free_stack_bad,mismatch,stage_bytes,raw_bytes,stage_zero,raw_zero);
}
'''
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--transport",required=True,type=Path)
    args=ap.parse_args()
    p=args.transport
    s=p.read_text()
    if "NOVA_WH_POOL_AUDIT_V2" in s:
        raise RuntimeError("audit already applied")
    anchor='__attribute__((visibility("default")))\nint nova_transport_page_take(uint64_t generation, int *out_page, int max_bytes)'
    s=once(s,anchor,AUDIT+"\n"+anchor,"inventory helper")
    s=once(s,
       '            nova_wh_page_free(w,n);\n            return got;',
       '            nova_wh_page_free(w,n);\n            if(got==AVERROR(ENOMEM))\n                nova_wh_diag_v2(w,"upstream_enomem");\n            return got;',
       "differentiate upstream return from page exhaustion")
    s=once(s,
       '        ret=AVERROR(ENOMEM);\n    }\n    pthread_mutex_unlock(&s->io_lock);',
       '        nova_wh_diag_v2(w,"raw_page_alloc_failed");\n        ret=AVERROR(ENOMEM);\n    }\n    pthread_mutex_unlock(&s->io_lock);',
       "physical free page exhaustion")
    p.write_text(s)
    print("NOVA_SHARED42_POOL_AUDIT_V2=PATCHED",p)

if __name__=="__main__":
    main()
