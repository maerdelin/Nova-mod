#!/usr/bin/env python3
"""ISO-only hardware decoder CBE diagnosis/retry; apply last before AVOS build."""
from pathlib import Path
import argparse

MARKER="NOVA_1052_ISO_HW_CBE_V1"

def one(text,old,new,label):
    if text.count(old)!=1:
        raise RuntimeError(f"1052 {label}: anchor count={text.count(old)}")
    return text.replace(old,new,1)

def patch(root):
    path=Path(root)/"Source/stream_video.c"
    text=path.read_text()
    if MARKER in text:
        raise RuntimeError("1052 CBE double-apply")
    text=one(text,"#include <signal.h>\n","#include <signal.h>\n#include <errno.h>\n","errno header")
    text=one(text,
        "\ts->video_decoder_drained = 0;\nDBGS serprintf(\"stream_open_video_dec\\r\\n\");",
        "\ts->video_decoder_drained = 0;\n"
        "\t/* NOVA_1052_ISO_HW_ONLY_V1: ISO never silently falls back\n"
        "\t * to the unusable legacy sfdec or FFmpeg software decoder. */\n"
        "\tint nova_iso_hw_only = strstr(s->src_query,\"&nova_iso=1\") != NULL;\n"
        "DBGS serprintf(\"stream_open_video_dec\\r\\n\");",
        "ISO decoder guard")
    text=one(text,
        "\twhile( prio ) {\n\t\tint try_prio = prio;",
        "\twhile( prio ) {\n"
        "\t\tif(nova_iso_hw_only && prio<STREAM_CPU_DSP3){\n"
        "\t\t\tserprintf(\"NOVA_1052_ISO_HW_ONLY_V1: hardware failed; block software fallback\\n\");\n"
        "\t\t\tbreak;\n"
        "\t\t}\n"
        "\t\tint try_prio = prio;",
        "priorities")
    start=text.index("\t\tint size = mem_size ? mem_size : get_default_stream_max_iframe_size();")
    end=text.index("\n\n\t\ts->num_frames = s->video_rc.num_frames;",start)
    old=text[start:end]
    if "cbe_new( size, size, type )" not in old or "cannot alloc CBE" not in old or len(old)>400:
        raise RuntimeError("1052 unexpected _allocate_video_buffers window")
    new=r'''		int size = mem_size ? mem_size : get_default_stream_max_iframe_size();
		int type = (mem_type == STREAM_MEM_DMA) ? 1 : 0;
		/* NOVA_1052_ISO_HW_CBE_V1: sfdec2 normally requests 6 MiB
		 * input with 6 MiB overlap (12 MiB heap total). Log precise
		 * requested bytes, errno, codec and frame size. Only ISO sfdec2
		 * retries with smaller, bounded CBE when the default fails. */
		int iso_sfdec2 = strstr(s->src_query,"&nova_iso=1") != NULL &&
			s->video_dec && s->video_dec->name &&
			!strcmp(s->video_dec->name,"sfdec2");
		if(iso_sfdec2 && size>6*1024*1024){
			serprintf("NOVA_1052_ISO_HW_CBE_V1: excessive size=%d cap=%d\n",
				size,6*1024*1024);
			size=6*1024*1024;
		}
		errno=0;
		s->cbe=cbe_new(size,size,type);
		int alloc_errno=errno;
		if(iso_sfdec2){
			serprintf("NOVA_1052_ISO_HW_CBE_V1: first capacity=%d alloc=%lld mem_type=%d configured=%d default=%d dim=%dx%d errno=%d ok=%d\n",
				size,(long long)size*2,mem_type,mem_size,
				get_default_stream_max_iframe_size(),width,height,
				alloc_errno,s->cbe!=NULL);
		}
		if(!s->cbe && iso_sfdec2 && !type){
			const int retries[]={4*1024*1024,3*1024*1024};
			for(int i=0;i<2 && !s->cbe;i++){
				int retry=retries[i];
				if(retry>=size)continue;
				errno=0;
				s->cbe=cbe_new(retry,retry,type);
				alloc_errno=errno;
				serprintf("NOVA_1052_ISO_HW_CBE_V1: retry capacity=%d alloc=%lld errno=%d ok=%d\n",
					retry,(long long)retry*2,alloc_errno,s->cbe!=NULL);
			}
		}
		if(!s->cbe){
			serprintf("NOVA_1052_ISO_HW_CBE_V1: terminal alloc=%lld mem_type=%d errno=%d iso=%d\n",
				(long long)size*2,mem_type,alloc_errno,iso_sfdec2);
			serprintf("cannot alloc CBE\r\n");
			return 1;
		}'''
    text=text[:start]+new+text[end:]
    if text.count(MARKER)<3:
        raise RuntimeError("1052 incomplete hardware diagnostic")
    path.write_text(text)
    print("NOVA_1052_ISO_HW_CBE_PATCH=PASS")
if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--native",required=True,type=Path)
    patch(ap.parse_args().native)
