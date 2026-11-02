#!/usr/bin/env python3
"""1073: one-time AVOS hooks for ISO blackbox; apply after other AVOS patches."""
import argparse
from pathlib import Path

def once(s,a,b,label):
    n=s.count(a)
    if n!=1:
        raise RuntimeError(f"1073 {label} anchor count {n}")
    return s.replace(a,b,1)

# Small, single-dlopen bridge. The shared library remains referenced until
# process exit. Hot-path calls do not allocate or resolve symbols.
BRIDGE=r'''
#include <dlfcn.h>
#include <stdint.h>
#include <pthread.h>
static pthread_once_t nova_1073_bridge_once=PTHREAD_ONCE_INIT;
static void (*nova_1073_bridge_fn)(int,int64_t,int);
static void *nova_1073_bridge_lib;
static void nova_1073_bridge_init(void)
{
    nova_1073_bridge_lib=dlopen("libnova_transport.so",RTLD_NOW);
    if(nova_1073_bridge_lib)
        nova_1073_bridge_fn=(void (*)(int,int64_t,int))
            dlsym(nova_1073_bridge_lib,"nova_transport_diag_external");
}
static void nova_1073_external(int kind,int64_t amount,int rc)
{
    pthread_once(&nova_1073_bridge_once,nova_1073_bridge_init);
    if(nova_1073_bridge_fn)nova_1073_bridge_fn(kind,amount,rc);
}
'''

def main(root):
    ff=root/"Source/stream_parser_ffmpeg.c"
    s=ff.read_text()
    s=once(s,'#include <signal.h>',BRIDGE+'\n#include <signal.h>',"ff bridge")
    # startup_boot_raw_diag already inserts timing around the actual
    # Shared42 conditional page_take. Hook outside its timing brackets.
    needle='        int64_t nova_boot_io_begin=av_gettime_relative();'
    s=once(s,needle,'        nova_1073_external(10,want,0);\n'+needle,
           "RAW begin")
    needle='        int64_t nova_boot_io_ms=(av_gettime_relative()-nova_boot_io_begin)/1000;'
    s=once(s,needle,'        nova_1073_external(11,want,got);\n'+needle,
           "RAW end")
    needle='    int result = av_read_frame(fmt, &packet);'
    s=once(s,needle,
        '    nova_1073_external(40,(int64_t)(fmt->pb?avio_tell(fmt->pb):-1),0);\n'
        +needle+
        '\n    nova_1073_external(41,(int64_t)(fmt->pb?avio_tell(fmt->pb):-1),result);',
        "FFmpeg demux")
    needle='            if(result==AVERROR(ENOMEM) &&\n               strstr(s->src_query,"nova_iso=1")){'
    s=once(s,needle,
        needle+
        '\n                nova_1073_external(30,(int64_t)(fmt->pb?avio_tell(fmt->pb):-1),result);',
        "ISO demux allocation failure")
    ff.write_text(s)

    video=root/"Source/stream_video.c"
    s=video.read_text()
    s=once(s,'#include <signal.h>',BRIDGE+'\n#include <signal.h>',"video bridge")
    needle='\t\tint alloc_errno=errno;'
    s=once(s,needle,needle+
        '\n\t\tif(iso_sfdec2)\n'
        '\t\t\tnova_1073_external(s->cbe ? 21 : 20,\n'
        '\t\t\t                   (int64_t)size*2,alloc_errno);',
        "first ISO CBE allocation")
    needle='\t\t\t\talloc_errno=errno;\n\t\t\t\tserprintf("NOVA_1052_ISO_HW_CBE_V1: retry'
    s=once(s,needle,
        '\t\t\t\talloc_errno=errno;\n'
        '\t\t\t\tnova_1073_external(s->cbe ? 21 : 20,\n'
        '\t\t\t\t                   (int64_t)retry*2,alloc_errno);\n'
        '\t\t\t\tserprintf("NOVA_1052_ISO_HW_CBE_V1: retry',
        "retry ISO CBE allocation")
    video.write_text(s)
    print("NOVA_1073_AVOS_DIAGNOSTICS=PASS")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--native",required=True,type=Path)
    main(parser.parse_args().native)
