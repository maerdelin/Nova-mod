#!/usr/bin/env python3
"""Patch AVOS after native_rebuffer_patch.py and direct_transport_native_patch.py.

In non-ISO mode full/partial HTTP receive pages transfer to RAW without a
stage-to-RAW copy. ISO still materializes libbluray output directly into RAW
pages. All direct sources use one refcounted 128 MiB pool and RAW cap 86 MiB.
"""
import argparse
from pathlib import Path

def once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)

def patch(text):
    if "NOVA_SHARED42_AVOS" in text:
        raise RuntimeError("shared42 patch applied already")
    fields = r"""    nova_transport_set_target_bps_fn direct_set_target_bps;
    /* NOVA_SHARED42_AVOS: RAW holds a reference to transport-owned pages. */
    void *shared_base;
    int shared_pages;
    void *(*shared_acquire)(uint64_t);
    void (*shared_release)(void *);
    int (*page_take)(uint64_t,int *,int);
    void *(*page_data)(void *,int);
    int (*page_length)(void *,int);
    void (*page_release)(void *,int);
    int page_queue[2048];
    int page_head;
    int page_tail;
    int page_queued;
    int page_head_consumed;
"""
    text=once(text,"    nova_transport_set_target_bps_fn direct_set_target_bps;\n",fields,"shared RAW fields")
    pre=r"""/* Shared-page transport ABI is resolved through the already open handle. */
"""
    text=once(text,"static uint64_t nova_direct_generation(const char *url)",pre+"static uint64_t nova_direct_generation(const char *url)","ABI marker")
    old="""    if (!raw->direct_read || !raw->direct_seek ||
        !raw->direct_size || !raw->direct_abort || !raw->direct_set_target_bps)
        return AVERROR(ENOSYS);

    unsigned char *buffer = av_malloc(NOVA_RAW_IO_BYTES);"""
    new="""    if (!raw->direct_read || !raw->direct_seek ||
        !raw->direct_size || !raw->direct_abort || !raw->direct_set_target_bps)
        return AVERROR(ENOSYS);
    raw->shared_acquire=(void *(*)(uint64_t))dlsym(raw->transport_handle,
                         "nova_transport_warehouse_acquire");
    raw->shared_release=(void (*)(void *))dlsym(raw->transport_handle,
                         "nova_transport_warehouse_release");
    raw->page_take=(int (*)(uint64_t,int *,int))dlsym(raw->transport_handle,
                         "nova_transport_page_take");
    raw->page_data=(void *(*)(void *,int))dlsym(raw->transport_handle,
                         "nova_transport_page_data");
    raw->page_length=(int (*)(void *,int))dlsym(raw->transport_handle,
                         "nova_transport_page_length");
    raw->page_release=(void (*)(void *,int))dlsym(raw->transport_handle,
                         "nova_transport_page_release");
    if(!raw->shared_acquire || !raw->shared_release ||
       !raw->page_take || !raw->page_data || !raw->page_length ||
       !raw->page_release)return AVERROR(ENOSYS);
    raw->shared_base=raw->shared_acquire(raw->transport_generation);
    if(!raw->shared_base)return AVERROR(ENOMEM);
    raw->shared_pages=1;
    raw->capacity_bytes=86 * 1024 * 1024;
    raw->page_head=raw->page_tail=raw->page_queued=0;
    raw->page_head_consumed=0;

    unsigned char *buffer = av_malloc(NOVA_RAW_IO_BYTES);"""
    text=once(text,old,new,"shared acquire in direct open")
    old="""        if (raw->transport_handle)
            dlclose(raw->transport_handle);
        raw->transport_handle = NULL;"""
    new="""        if(raw->shared_base && raw->shared_release)
            raw->shared_release(raw->shared_base);
        raw->shared_base=NULL;
        raw->shared_pages=0;
        if (raw->transport_handle)
            dlclose(raw->transport_handle);
        raw->transport_handle = NULL;"""
    text=once(text,old,new,"shared release direct close")
    old="""    raw->read_off = 0;
    raw->write_off = 0;
    raw->used_bytes = 0;
}"""
    new="""    if(raw->shared_pages && raw->shared_base && raw->page_release){
        while(raw->page_queued>0){
            int n=raw->page_queue[raw->page_head];
            raw->page_head=(raw->page_head+1)%2048;
            raw->page_queued--;
            raw->page_release(raw->shared_base,n);
        }
        raw->page_head=raw->page_tail=0;
        raw->page_head_consumed=0;
    }
    raw->read_off = 0;
    raw->write_off = 0;
    raw->used_bytes = 0;
}"""
    text=once(text,old,new,"shared reset")
    text=once(text,"    raw->capacity_bytes = NOVA_RAW_FALLBACK_CAP_BYTES;\n    pthread_cond_broadcast(&raw->can_write);",
              "    raw->capacity_bytes = raw->shared_pages ? 86 * 1024 * 1024 : NOVA_RAW_FALLBACK_CAP_BYTES;\n    if(raw->shared_pages){\n        int cap=(int)raw->capacity_bytes;\n        if(resume_bytes>cap)resume_bytes=cap;\n        if(low_bytes>=resume_bytes)low_bytes=resume_bytes>2?resume_bytes/2:1;\n        raw->resume_bytes=resume_bytes;\n        raw->low_bytes=low_bytes;\n    }\n    pthread_cond_broadcast(&raw->can_write);","policy capacity")
    text=once(text,"    raw->s->rebuffer_capacity_bytes = NOVA_RAW_FALLBACK_CAP_BYTES;",
              "    raw->s->rebuffer_capacity_bytes = raw->capacity_bytes;","policy report")
    text=once(text,
              "        int64_t ask = room < contiguous ? room : contiguous;",
              "        int64_t ask = raw->shared_pages ? room : (room < contiguous ? room : contiguous);",
              "shared pages ignore byte-ring wrap")
    text=once(text,"        if( ask > NOVA_RAW_IO_BYTES ) ask = NOVA_RAW_IO_BYTES;",
              "        if( ask > (raw->shared_pages ? 64 * 1024 : NOVA_RAW_IO_BYTES) )\n            ask = raw->shared_pages ? 64 * 1024 : NOVA_RAW_IO_BYTES;","producer ask")
    old="""        int got = avio_read(raw->source, raw->ring + write_off, want);
        pthread_mutex_unlock(&raw->source_mutex);

        pthread_mutex_lock(&raw->mutex);
        if( generation != raw->generation ) {
            pthread_mutex_unlock(&raw->mutex);
            continue;
        }

        if( got > 0 ) {
            raw->write_off += got;"""
    new="""        int incoming_page=-1;
        int got=raw->shared_pages ?
            raw->page_take(raw->transport_generation,&incoming_page,want) :
            avio_read(raw->source, raw->ring + write_off, want);
        pthread_mutex_unlock(&raw->source_mutex);

        pthread_mutex_lock(&raw->mutex);
        if( generation != raw->generation ) {
            if(raw->shared_pages && incoming_page>=0)
                raw->page_release(raw->shared_base,incoming_page);
            pthread_mutex_unlock(&raw->mutex);
            continue;
        }

        if( got > 0 ) {
            if(raw->shared_pages){
                if(incoming_page<0 || raw->page_queued>=2048){
                    if(incoming_page>=0)
                        raw->page_release(raw->shared_base,incoming_page);
                    raw->error=AVERROR(EIO);
                    pthread_cond_broadcast(&raw->can_read);
                    pthread_mutex_unlock(&raw->mutex);
                    continue;
                }
                raw->page_queue[raw->page_tail]=incoming_page;
                raw->page_tail=(raw->page_tail+1)%2048;
                raw->page_queued++;
            }
            raw->write_off += got;"""
    text=once(text,old,new,"RAW producer page take")
    old="""    int copied = 0;
    while( copied < size && raw->used_bytes > 0 ) {
        int64_t contiguous = raw->capacity_bytes - raw->read_off;"""
    new="""    int copied = 0;
    while( copied < size && raw->used_bytes > 0 ) {
        if(raw->shared_pages){
            if(raw->page_queued<=0)break;
            int n=raw->page_queue[raw->page_head];
            int nbytes=raw->page_length(raw->shared_base,n);
            int avail=nbytes-raw->page_head_consumed;
            if(avail<=0)break;
            int take=avail<(size-copied)?avail:(size-copied);
            memcpy(dst+copied,
                   (uint8_t *)raw->page_data(raw->shared_base,n)
                     +raw->page_head_consumed,take);
            raw->page_head_consumed+=take;
            raw->used_bytes-=take;
            raw->consumed_bytes+=take;
            raw->consumer_pos+=take;
            copied+=take;
            if(raw->page_head_consumed==nbytes){
                raw->page_release(raw->shared_base,n);
                raw->page_head=(raw->page_head+1)%2048;
                raw->page_queued--;
                raw->page_head_consumed=0;
            }
            continue;
        }
        int64_t contiguous = raw->capacity_bytes - raw->read_off;"""
    text=once(text,old,new,"RAW consumer reads pages")
    # RAW allocation is skipped for direct URL; source open acquires the same
    # transport-owned warehouse before the producer is started.
    old="""    raw->ring = av_malloc(NOVA_RAW_FALLBACK_CAP_BYTES);
    if( !raw->ring ) {
        ret = AVERROR(ENOMEM);
        goto fail;
    }"""
    new="""    if(!nova_direct)raw->ring=av_malloc(NOVA_RAW_FALLBACK_CAP_BYTES);
    if(!nova_direct && !raw->ring){
        ret=AVERROR(ENOMEM);
        goto fail;
    }"""
    text=once(text,old,new,"skip independent RAW128 allocation")
    old="""    if( !nova_direct )
        raw->source_size = avio_size(raw->source);
"""
    new="""    if( !nova_direct )
        raw->source_size = avio_size(raw->source);
    else {
        s->rebuffer_capacity_bytes=raw->capacity_bytes;
    }
"""
    text=once(text,old,new,"direct capacity publish")
    old="""    s->rebuffer_capacity_bytes = NOVA_RAW_FALLBACK_CAP_BYTES;
    __atomic_store_n(&s->raw_prefetch_enabled, 1, __ATOMIC_RELEASE);"""
    new="""    s->rebuffer_capacity_bytes = raw->capacity_bytes;
    __atomic_store_n(&s->raw_prefetch_enabled, 1, __ATOMIC_RELEASE);"""
    text=once(text,old,new,"open capacity telemetry")
    # The post-patch cleanup hook is installed by the previous direct source
    # patch; no extra raw->ring cleanup needed (null for shared).
    return text

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--native",required=True,type=Path)
    args=a.parse_args()
    target=args.native/"Source"/"stream_parser_ffmpeg.c"
    text=target.read_text()
    updated=patch(text)
    target.write_text(updated)
    print("NOVA_SHARED42_AVOS_PATCH=PASS")

if __name__=="__main__":
    main()
