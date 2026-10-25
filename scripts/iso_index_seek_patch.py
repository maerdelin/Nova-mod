#!/usr/bin/env python3
"""Non-mutating CLPI-indexed single-clip Blu-ray seek with timestamp fallback."""
import argparse
from pathlib import Path

def once(s,a,b):
    if s.count(a)!=1: raise RuntimeError("expected unique anchor: "+a[:70])
    return s.replace(a,b,1)

BRIDGE=r'''
/* NOVA_ISO_INDEX_MAP_V3: non-mutating Blu-ray CLPI time index.
 * The active libbluray reader, AVIO source and ring generation are untouched.
 */
extern int64_t bd_nova_map_time_to_byte(BLURAY *, uint64_t, uint64_t *);
__attribute__((visibility("default")))
int64_t nova_transport_time_to_byte(uint64_t generation, int64_t ms)
{
    nova_session *s=session_acquire(generation);
    if (!s) return AVERROR_EXIT;
    int64_t answer=AVERROR(ENOSYS);
    pthread_mutex_lock(&s->io_lock);
    if(!s->stopping && s->mode==NOVA_MODE_BLURAY_ISO && s->bd &&
       s->clip_count==1 && ms>0 && (uint64_t)ms<s->duration_us/1000) {
        uint64_t indexed_tick=0;
        int64_t byte=bd_nova_map_time_to_byte(s->bd,(uint64_t)ms*90ULL,
                                              &indexed_tick);
        int64_t actual=(int64_t)(indexed_tick/90ULL);
        int64_t delta=actual-ms;
        if(delta<0)delta=-delta;
        if(byte>=0 && (uint64_t)byte<s->output_size && delta<=5000)
            answer=byte;
        LOGI("NOVA_ISO_INDEX_MAP_V3: targetMs=%" PRId64
             " indexedMs=%" PRId64 " byte=%" PRId64
             " answer=%" PRId64,ms,actual,byte,answer);
    }
    pthread_mutex_unlock(&s->io_lock);
    session_release(s);
    return answer;
}

'''
SEEK=r'''
    /* NOVA_ISO_INDEX_SEEK_V3: only verified single-clip ISO, never MP4/MKV. */
    int ret=-1;
    if(ff_p->nova_iso_time_mode && time>0 && s->video->valid &&
       ff_p->raw.direct_transport && ff_p->raw.direct_time_to_byte) {
        int64_t idx;
        pthread_mutex_lock(&ff_p->raw.source_mutex);
        idx=ff_p->raw.direct_time_to_byte(ff_p->raw.transport_generation,time);
        pthread_mutex_unlock(&ff_p->raw.source_mutex);
        if(idx>=0 && (uint64_t)idx<s->size) {
            ret=av_seek_frame(fmt,-1,idx,AVSEEK_FLAG_BYTE|AVSEEK_FLAG_BACKWARD);
            serprintf("NOVA_ISO_INDEX_SEEK_V3: timeMs=%d byte=%lld ret=%d\n",
                      time,(long long)idx,ret);
        }
    }
    if(ret<0) {
        /* Unindexed, multi-clip, failed mapping or unsupported BYTE seek:
         * keep the old timestamp behavior. Do not approximate with bitrate. */
        if(ff_p->nova_iso_time_mode && time>0)
            serprintf("NOVA_ISO_INDEX_FALLBACK_V3: timeMs=%d\n",time);
        ret=avformat_seek_file(fmt,-1,seek_min,new_pos,seek_max,av_flags);
    }
'''

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--native',type=Path,required=True)
    ap.add_argument('--transport',type=Path,required=True)
    a=ap.parse_args()
    f=a.native/'Source/stream_parser_ffmpeg.c'
    s=f.read_text()
    assert 'NOVA_PGS_HISTORY_BYPASS_AB_V1' in s
    s=once(s,'typedef struct NOVA_RAW_PREFETCH {',
       'typedef int64_t (*nova_transport_time_byte_fn)(uint64_t,int64_t);\n'
       'typedef struct NOVA_RAW_PREFETCH {')
    s=once(s,'    nova_transport_abort_fn direct_abort;\n',
       '    nova_transport_abort_fn direct_abort;\n'
       '    nova_transport_time_byte_fn direct_time_to_byte;\n')
    s=once(s,'        raw->transport_handle, "nova_transport_abort");\n',
       '        raw->transport_handle, "nova_transport_abort");\n'
       '    raw->direct_time_to_byte=(nova_transport_time_byte_fn)dlsym(\n'
       '        raw->transport_handle,"nova_transport_time_to_byte");\n')
    s=once(s,'\tint ret = avformat_seek_file( fmt, -1, seek_min, new_pos, seek_max, av_flags);\n',SEEK)
    t=a.transport.read_text()
    t=once(t,'__attribute__((visibility("default")))\nint64_t nova_transport_size(uint64_t generation)',
       BRIDGE+'__attribute__((visibility("default")))\nint64_t nova_transport_size(uint64_t generation)')
    f.write_text(s)
    a.transport.write_text(t)
    print('NOVA_ISO_INDEX_SEEK_V3=PATCHED')

if __name__=='__main__':
    main()
