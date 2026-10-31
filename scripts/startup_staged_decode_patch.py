#!/usr/bin/env python3
"""MKV-only staged first-frame trial for the pinned #983 AVOS source.

Probe stream metadata once at 64 KiB; then test genuine decoded frames on
the same FFmpeg demuxer while accumulating 64/128/256/512 KiB, 1/2/3 MiB,
then every additional MiB. Never repeat find_stream_info on one context.
Every packet read for the trial is moved (not copied) into a FIFO and
replayed unmodified to AVOS, keeping audio/subtitle/PTS/seek behavior.
At a conservative memory ceiling hand off to the original AVOS decoder,
which continues until first frame or a real EOF/error/cancellation.
"""
import argparse
from pathlib import Path

NODE = r'''
typedef struct NOVA_STAGED_PKT {
    AVPacket pkt;
    struct NOVA_STAGED_PKT *next;
} NOVA_STAGED_PKT;
'''

HELPERS = r'''
/* NOVA_STAGED_DECODE_64K_V1. All demux access remains on the parser-open
 * thread. No second AVFormatContext, network source, or speculative seek.
 * Lossless packet replay is necessary because the trial software decoder
 * must NOT steal packet data from the real AVOS hardware decoder. */
#define NOVA_STAGED_PACKET_WALL (32LL * 1024 * 1024)
#define NOVA_STAGED_PACKET_COUNT_WALL 8192

static void nova_staged_clear(FF_PRIV *p)
{
    if(!p)return;
    NOVA_STAGED_PKT *n=p->nova_staged_first;
    while(n){
        NOVA_STAGED_PKT *next=n->next;
        av_packet_unref(&n->pkt);
        av_free(n);
        n=next;
    }
    p->nova_staged_first=NULL;
    p->nova_staged_last=NULL;
    p->nova_staged_bytes=0;
    p->nova_staged_packets=0;
}

static int nova_staged_replay_or_read(FF_PRIV *p,AVFormatContext *fmt,
                                      AVPacket *dst)
{
    NOVA_STAGED_PKT *n=p->nova_staged_first;
    if(!n)return av_read_frame(fmt,dst);
    p->nova_staged_first=n->next;
    if(!p->nova_staged_first)p->nova_staged_last=NULL;
    p->nova_staged_bytes-=n->pkt.size;
    p->nova_staged_packets--;
    av_packet_move_ref(dst,&n->pkt);
    av_free(n);
    return 0;
}

/* MKV headers generally contain codec and track metadata. If they do not,
 * leave normal 10 MB FFmpeg probing intact rather than lose an audio/PGS
 * stream. A short probe must not silently turn missing tracks into success. */
static int nova_staged_header_ok(AVFormatContext *fmt)
{
    if(!fmt || fmt->nb_streams==0)return 0;
    int videos=0;
    for(unsigned i=0;i<fmt->nb_streams;i++){
        const AVStream *st=fmt->streams[i];
        if(!st || !st->codecpar)return 0;
        const AVCodecParameters *cp=st->codecpar;
        if(cp->codec_type==AVMEDIA_TYPE_VIDEO &&
           !(st->disposition&AV_DISPOSITION_ATTACHED_PIC)){
            videos++;
            if(cp->codec_id==AV_CODEC_ID_NONE ||
               cp->width<=0 || cp->height<=0)return 0;
        } else if(cp->codec_type==AVMEDIA_TYPE_AUDIO){
            if(cp->codec_id==AV_CODEC_ID_NONE ||
               cp->sample_rate<=0 || cp->ch_layout.nb_channels<=0)
                return 0;
        } else if(cp->codec_type==AVMEDIA_TYPE_SUBTITLE){
            if(cp->codec_id==AV_CODEC_ID_NONE)return 0;
        }
    }
    return videos>0;
}

/* Feed the real software decoder without resetting it between thresholds.
 * EAGAIN means a packet needs draining, not a failed frame. Returns 1 only
 * after avcodec_receive_frame has actually returned a decoded AVFrame. */
static int nova_staged_feed(AVCodecContext *dec,AVFrame *frame,
                            const AVPacket *pkt)
{
    int sr=avcodec_send_packet(dec,pkt);
    if(sr==AVERROR(EAGAIN)){
        int rr=avcodec_receive_frame(dec,frame);
        if(rr>=0){av_frame_unref(frame);return 1;}
        if(rr!=AVERROR(EAGAIN) && rr!=AVERROR_EOF)return -1;
        sr=avcodec_send_packet(dec,pkt);
    }
    if(sr<0)return -1;
    int rr;
    while((rr=avcodec_receive_frame(dec,frame))>=0){
        av_frame_unref(frame);
        return 1;
    }
    return rr==AVERROR(EAGAIN) || rr==AVERROR_EOF ? 0 : -1;
}

/* The next checkpoint advances 1 MiB at a time beyond 3 MiB.
 * It is not a maximum read limit. No arbitrary 3/10 MiB stop. */
static int64_t nova_staged_next_level(int64_t level)
{
    if(level<128*1024LL)return 128*1024LL;
    if(level<256*1024LL)return 256*1024LL;
    if(level<512*1024LL)return 512*1024LL;
    if(level<1024*1024LL)return 1024*1024LL;
    if(level>=INT64_MAX-1024*1024LL)return INT64_MAX;
    return level+1024*1024LL;
}

static void nova_staged_try_first_frame(FF_PRIV *p)
{
    AVFormatContext *fmt=p->fmt;
    if(!fmt || !nova_staged_header_ok(fmt)){
        serprintf("NOVA_STAGED_DECODE_SKIP reason=metadata-incomplete\n");
        return;
    }
    int vi=-1;
    for(unsigned i=0;i<fmt->nb_streams;i++){
        const AVStream *st=fmt->streams[i];
        if(st->codecpar->codec_type==AVMEDIA_TYPE_VIDEO &&
           !(st->disposition&AV_DISPOSITION_ATTACHED_PIC)){
            vi=(int)i;break;
        }
    }
    if(vi<0)return;
    const AVCodecParameters *cp=fmt->streams[vi]->codecpar;
    const AVCodec *codec=avcodec_find_decoder(cp->codec_id);
    if(!codec){
        serprintf("NOVA_STAGED_DECODE_SKIP reason=decoder-unavailable codec=%d\n",
                  cp->codec_id);
        return;
    }
    AVCodecContext *dec=avcodec_alloc_context3(codec);
    AVFrame *frame=av_frame_alloc();
    if(!dec || !frame ||
       avcodec_parameters_to_context(dec,cp)<0){
        serprintf("NOVA_STAGED_DECODE_SKIP reason=decoder-parameters\n");
        goto done;
    }
    dec->thread_count=1;
    if(avcodec_open2(dec,codec,NULL)<0){
        serprintf("NOVA_STAGED_DECODE_SKIP reason=decoder-open codec=%d\n",
                  cp->codec_id);
        goto done;
    }
    int64_t total=0, level=64*1024LL, start=av_gettime_relative();
    int got_frame=0, damaged_packets=0;
    serprintf("NOVA_STAGED_DECODE_BEGIN first=65536 stepBeyond3M=1048576 streams=%u video=%d\n",
              fmt->nb_streams,vi);
    while(!got_frame && !p->s->parser_interrupt &&
          !stream_abort(p->s) &&
          p->nova_staged_bytes<NOVA_STAGED_PACKET_WALL &&
          p->nova_staged_packets<NOVA_STAGED_PACKET_COUNT_WALL){
        NOVA_STAGED_PKT *n=av_mallocz(sizeof(*n));
        if(!n){serprintf("NOVA_STAGED_DECODE_STOP reason=alloc\n");break;}
        AVPacket pkt={0};
        int result=av_read_frame(fmt,&pkt);
        if(result<0){
            av_packet_unref(&pkt);av_free(n);
            serprintf("NOVA_STAGED_DECODE_HANDOFF reason=demux rc=%d bytes=%lld\n",
                      result,(long long)total);
            break;
        }
        av_packet_move_ref(&n->pkt,&pkt);
        if(p->nova_staged_last)p->nova_staged_last->next=n;
        else p->nova_staged_first=n;
        p->nova_staged_last=n;
        p->nova_staged_packets++;
        p->nova_staged_bytes+=n->pkt.size>0?n->pkt.size:0;
        total+=n->pkt.size>0?n->pkt.size:0;
        if(n->pkt.stream_index==vi){
            int d=nova_staged_feed(dec,frame,&n->pkt);
            if(d>0)got_frame=1;
            if(d<0)damaged_packets++;
        }
        while(!got_frame && total>=level){
            serprintf("NOVA_STAGED_DECODE_RETRY threshold=%lld observed=%lld outcome=need-more packets=%d\n",
                      (long long)level,(long long)total,p->nova_staged_packets);
            int64_t next=nova_staged_next_level(level);
            if(next<=level)break;
            level=next;
        }
    }
    if(got_frame){
        serprintf("NOVA_STAGED_DECODE_SUCCESS observed=%lld stage=%lld packets=%d elapsedMs=%lld\n",
                  (long long)total,(long long)level,p->nova_staged_packets,
                  (long long)((av_gettime_relative()-start)/1000));
    }else{
        serprintf("NOVA_STAGED_DECODE_HANDOFF reason=%s observed=%lld next=%lld packets=%d damaged=%d\n",
                  p->s->parser_interrupt || stream_abort(p->s)?"cancel":
                  p->nova_staged_bytes>=NOVA_STAGED_PACKET_WALL ||
                  p->nova_staged_packets>=NOVA_STAGED_PACKET_COUNT_WALL
                  ?"memory-wall":"no-software-frame",
                  (long long)total,(long long)level,
                  p->nova_staged_packets,damaged_packets);
    }
done:
    av_frame_free(&frame);
    avcodec_free_context(&dec);
}
'''

def once(src, old, new, label):
    count=src.count(old)
    if count!=1:
        raise RuntimeError(f"NOVA_STAGED_DECODE {label}: expected one anchor, got {count}")
    return src.replace(old,new,1)

def apply(root: Path):
    path=root/"Source"/"stream_parser_ffmpeg.c"
    src=path.read_text()
    if "NOVA_STAGED_DECODE_64K_V1" in src:
        raise RuntimeError("NOVA_STAGED_DECODE already installed")
    src=once(src,"typedef struct FF_PRIV\n",NODE+"\ntypedef struct FF_PRIV\n","node")
    src=once(src,"\tAVFormatContext *fmt;\n",
        "\tAVFormatContext *fmt;\n"
        "\tNOVA_STAGED_PKT *nova_staged_first, *nova_staged_last;\n"
        "\tint64_t nova_staged_bytes;\n"
        "\tint nova_staged_packets;\n","fields")
    src=once(src,"static int _open( STREAM *s, int buffer_size, int flags )\n",
        HELPERS+"\nstatic int _open( STREAM *s, int buffer_size, int flags )\n","helpers")
    src=once(src,"\tff_p->flags = flags;\n",
        '\tff_p->flags = flags;\n'
        '\t/* MKV marker lives in src.url, NOT src_query (only ?mpegts& copied). */\n'
        '\tint nova_staged_mkv = !(flags & STREAM_PARSER_THUMB) &&\n'
        '\t\ts->src.url && !strncmp(s->src.url,"novatransport://",16) &&\n'
        '\t\tstrstr(s->src.url,"&nova_mkv=1")!=NULL;\n','scope')
    src=once(src,'av_dict_set(&ff_p->fmt_opts, "probesize", "10000000", 0);',
        'av_dict_set(&ff_p->fmt_opts, "probesize",\n'
        '\t\t\tnova_staged_mkv ? "65536" : "10000000", 0);',
        'probe limit')
    src=once(src,"\t\t// Normal mode: analyze all streams\n",
        '\t\t/* ONE find_stream_info call: its FFStreamInfo state is freed\n'
        '\t\t * after return. Incomplete headers keep original 10 MB path. */\n'
        '\t\tif(nova_staged_mkv && !nova_staged_header_ok(ff_p->fmt)){\n'
        '\t\t\tserprintf("NOVA_STAGED_DECODE_SKIP reason=incomplete-header legacy=1\\n");\n'
        '\t\t\tff_p->fmt->probesize=10000000;\n'
        '\t\t\tnova_staged_mkv=0;\n'
        '\t\t}\n'
        "\t\t// Normal mode: analyze all streams\n","guard")
    src=once(src,
        "\t\tif (avformat_find_stream_info(ff_p->fmt, NULL) < 0) {\n"
        '\t\t\tprintf("FFMPEG: cannot find stream info\\r\\n");\n'
        "\t\t}\n",
        "\t\tif (avformat_find_stream_info(ff_p->fmt, NULL) < 0) {\n"
        '\t\t\tprintf("FFMPEG: cannot find stream info\\r\\n");\n'
        "\t\t}\n"
        '\t\tif(nova_staged_mkv)nova_staged_try_first_frame(ff_p);\n',
        "trial after probe")
    src=once(src,"int result = av_read_frame(fmt, &packet);",
        "int result = nova_staged_replay_or_read(ff_p,fmt,&packet);",
        "FIFO into parser")
    src=once(src,"ErrorExit4:\nErrorExit3:\n",
        "ErrorExit4:\nErrorExit3:\n\tnova_staged_clear(ff_p);\n",
        "open error cleanup")
    src=once(src,"\tif( ff_p ) {\n\t\tif( ff_p->fmt ) {\n",
        "\tif( ff_p ) {\n\t\tnova_staged_clear(ff_p);\n\t\tif( ff_p->fmt ) {\n",
        "normal close cleanup")
    src=once(src,"\ts->audio_parse_end = 0;\n\ts->video_parse_end = 0;\n",
        "\t/* Drop replay on successful timeline seek, not before. */\n"
        "\tnova_staged_clear(ff_p);\n"
        "\ts->audio_parse_end = 0;\n\ts->video_parse_end = 0;\n",
        "successful seek invalidates preview")
    for token in ("NOVA_STAGED_DECODE_BEGIN","NOVA_STAGED_DECODE_RETRY",
                  "NOVA_STAGED_DECODE_SUCCESS","NOVA_STAGED_DECODE_HANDOFF",
                  "nova_staged_next_level(level)","nova_staged_replay_or_read(ff_p,fmt,&packet)"):
        if token not in src:
            raise RuntimeError("Missing postcondition "+token)
    path.write_text(src)
    print("NOVA_STAGED_DECODE_64K_PATCH=PASS")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--native",type=Path,required=True)
    args=parser.parse_args()
    apply(args.native)
