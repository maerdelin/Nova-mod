/*
 * NOVA_LITERANGE4_V1 -- zero additional download threads.
 *
 * All CURLM/CURL operations belong to the already existing RAW128 source
 * producer, which invokes nova_transport_read() under s->io_lock. The ISO
 * movie callback reaches the same owner. No pthread_create, JNI read, or
 * busy-spin occurs in this data plane. Abort only marks s->stopping; the
 * owner disposes CURL handles before session destruction.
 *
 * Two long 4*X-byte media-time ranges (X=average bytes/second) with
 * W=2 in-order completion gate. The second slot stays reserved when
 * it finishes first; new ranges start only as the oldest outstanding
 * slot is committed in order. Each of the two long-lived HTTP/1.1
 * responses uses a fixed 32 MiB circular receive window; when future
 * data gets ahead, libcurl PAUSE applies backpressure without closing
 * its TCP connection. Along with the paired 64 MiB RAW ring this has
 * a 128 MiB *data warehouse* budget (not counting codec/TLS overhead).
 * Every seek resets the two-slot epoch at the *actual seek byte offset*.
 * TLS verification and strict 206 Content-Range remain mandatory.
 */

/* Bounded staging shares RAW's single 128 MiB backing allocation. */
#define NOVA_LITE_STAGE_BYTES NOVA_WH_STAGE_BYTES
#define NOVA_LITE_HEAD_BYTES NOVA_WH_HEAD_BYTES
#define NOVA_LITE_FUTURE_BYTES NOVA_WH_FUTURE_BYTES
#define NOVA_LITE_SLOTS 2
#define NOVA_LITE_SEGMENT_SECONDS 4
#define NOVA_LITE_DATA_WAREHOUSE_BYTES (128 * 1024 * 1024)
#define NOVA_LITE_RAW_RING_BYTES (64 * 1024 * 1024)
#define NOVA_LITE_MAX_PIECE_BYTES (128 * 1024 * 1024)
#define NOVA_LITE_RESUME_FREE (64 * 1024)
#define NOVA_LITE_POLL_MS 40
#define NOVA_LITE_UPSHIFT_GAP_MS 2000
#define NOVA_LITE_WAIT_TRIGGER_MS 80
#define NOVA_LITE_CA_LIMIT (4 * 1024 * 1024)
#define NOVA_LITE_URL_LIMIT 65536

#include <dirent.h>
#include <ctype.h>

/* Normalize the WebDAV-origin URL before handing it to libcurl. Java accepts
 * raw UTF-8 and spaces; preserve signed query delimiters and existing %HH.
 * Never log an origin URL, query token, or Authorization header.
 */
static char *nova_lite_encode_url(const char *raw,unsigned *escaped,unsigned *bad_pct)
{
    *escaped=0; *bad_pct=0;
    if(!raw)return NULL;
    size_t len=strlen(raw);
    if(!len || len>NOVA_LITE_URL_LIMIT ||
       (strncasecmp(raw,"http://",7) && strncasecmp(raw,"https://",8)))
        return NULL;
    size_t scheme=strncasecmp(raw,"https://",8)==0?8:7;
    size_t hostend=scheme;
    while(hostend<len && raw[hostend]!='/' &&
          raw[hostend]!='?' && raw[hostend]!='#'){
        unsigned char a=(unsigned char)raw[hostend];
        if(a<=32 || a>=127 || a=='\\' || a=='"' ||
           a=='<' || a=='>' || a=='|')return NULL;
        hostend++;
    }
    if(hostend==scheme || len>(SIZE_MAX-1)/3)return NULL;
    char *out=(char *)malloc(len*3+1);
    if(!out)return NULL;
    size_t at=0;
    for(size_t i=0;i<len;++i){
        unsigned char a=(unsigned char)raw[i];
        if(i>=hostend && a=='#')break;
        int pct=(a=='%' && i+2<len &&
                 isxdigit((unsigned char)raw[i+1]) &&
                 isxdigit((unsigned char)raw[i+2]));
        if(i>=hostend && (a<=32 || a>=127 || a=='<' ||
           a=='>' || a=='"' || a=='\\' || a=='^' ||
           a==96 || a=='{' || a=='}' || a=='|' ||
           (a=='%' && !pct))){
            static const char hex[]="0123456789ABCDEF";
            out[at++]='%'; out[at++]=hex[a>>4]; out[at++]=hex[a&15];
            ++*escaped;
            if(a=='%')++*bad_pct;
        }else out[at++]=(char)a;
    }
    out[at]=0;
    CURLU *url=curl_url();
    if(!url){free(out);return NULL;}
    CURLUcode rc=curl_url_set(url,CURLUPART_URL,out,0);
    curl_url_cleanup(url);
    if(rc!=CURLUE_OK){free(out);return NULL;}
    return out;
}


typedef struct nova_lite_slot {
    struct nova_lite_state *owner;
    CURL *easy;
    struct curl_slist *headers;
    int page_head;
    int page_tail;
    int page_count;
    int state;
    int index;
    int filled;  /* all received bytes, including already delivered */
    int delivered; /* bytes consumed from this lane */
    int paused;  /* CURL_WRITEFUNC_PAUSE until stage has room */
    int pause_need_pages; /* exact callback allocation demand (0..16) */
    int length;
    int64_t start;
    long status;
    int range_ok;
    int encoding_ok;
    long retry_after_sec;
    char range_str[64];
    char curl_error[CURL_ERROR_SIZE];
} nova_lite_slot;

typedef struct nova_lite_state {
    nova_session *session;
    CURLM *multi;
    nova_lite_slot slots[NOVA_LITE_SLOTS];
    uint64_t generation;
    int running;
    int64_t piece_origin;
    uint64_t piece_bytes;
    int64_t last_gate_log_ms;
    int64_t last_raise_ms;
    int64_t last_sample_ms;
    uint64_t committed_sample_bytes;
    uint64_t received_sample_bytes;
    unsigned starvation_count;
    unsigned good_samples;
    char *request_url;
    char *ca_pem;
    size_t ca_pem_len;
    unsigned ca_count;
    int64_t last_starve_tick_ms;
    CURLcode last_curl_error;
    long last_http_status;
    unsigned successful_ranges;
    long last_retry_after_sec;
    uint64_t metric_requests,metric_new_connections,metric_reused_requests;
    uint64_t metric_connect_ms,metric_tls_ms,metric_ttfb_ms;
} nova_lite_state;

/* Android CA roots are hashed with an older algorithm and cannot be passed
 * directly as OpenSSL 3 CAPATH. Supply a validated PEM bundle in memory.
 * No change to TLS peer/hostname checks, and no insecure fallback.
 */
static void nova_lite_load_android_roots(nova_lite_state *e)
{
    static const char *dirs[]={
        "/apex/com.android.conscrypt/cacerts",
        "/system/etc/security/cacerts",NULL};
    char *bundle=(char *)malloc(NOVA_LITE_CA_LIMIT+1);
    if(!bundle)return;
    size_t used=0;
    unsigned count=0;
    for(int d=0;dirs[d] && !count;++d){
        DIR *dir=opendir(dirs[d]);
        if(!dir)continue;
        struct dirent *item;
        while((item=readdir(dir))!=NULL && count<512){
            const char *name=item->d_name;
            if(strlen(name)<10 || name[8]!='.')continue;
            int ok=1;
            for(int i=0;i<8;++i)
                if(!isxdigit((unsigned char)name[i]))ok=0;
            for(const char *p=name+9;*p;++p)
                if(!isdigit((unsigned char)*p))ok=0;
            if(!ok || !name[9])continue;
            char path[512];
            int n=snprintf(path,sizeof(path),"%s/%s",dirs[d],name);
            if(n<=0 || n>=(int)sizeof(path))continue;
            FILE *file=fopen(path,"rb");
            if(!file)continue;
            if(fseek(file,0,SEEK_END)!=0){fclose(file);continue;}
            long size=ftell(file);
            if(size<=0 || size>128*1024 ||
               (size_t)size+used+2>NOVA_LITE_CA_LIMIT ||
               fseek(file,0,SEEK_SET)!=0){fclose(file);continue;}
            char *cert=(char *)malloc((size_t)size+1);
            if(!cert){fclose(file);continue;}
            size_t got=fread(cert,1,(size_t)size,file);
            fclose(file);
            cert[got]=0;
            if(got==(size_t)size &&
               strstr(cert,"-----BEGIN CERTIFICATE-----") &&
               strstr(cert,"-----END CERTIFICATE-----")){
                memcpy(bundle+used,cert,got);
                used+=got;
                bundle[used++]='\n';
                count++;
            }
            free(cert);
        }
        closedir(dir);
    }
    if(count){
        bundle[used]=0;
        e->ca_pem=bundle;
        e->ca_pem_len=used;
        e->ca_count=count;
    }else free(bundle);
    LOGI("NOVA_LITERANGE4_TRUST certs=%u pemBytes=%zu verify=on",
         e->ca_count,e->ca_pem_len);
}

static pthread_once_t nova_lite_curl_once = PTHREAD_ONCE_INIT;
static void nova_lite_curl_initialize(void)
{
    curl_global_init(CURL_GLOBAL_DEFAULT);
}

static size_t nova_lite_header(char *ptr,size_t size,size_t nmemb,void *userdata)
{
    nova_lite_slot *slot=(nova_lite_slot *)userdata;
    size_t len=size*nmemb;
    if(!slot || len==0)return len;
    if(len>5 && !strncmp(ptr,"HTTP/",5)){
        slot->status=0;
        slot->range_ok=0;
        slot->encoding_ok=1;
        slot->retry_after_sec=0;
        const char *space=memchr(ptr,' ',len);
        if(space && space+4<=ptr+len)
            slot->status=strtol(space+1,NULL,10);
    } else if(len>14 && !strncasecmp(ptr,"Content-Range:",14)) {
        int64_t first=-1,last=-1,total=-1;
        if(sscanf(ptr+14," bytes %" SCNd64 "-%" SCNd64 "/%" SCNd64,
                  &first,&last,&total)==3){
            nova_session *s=slot->owner->session;
            slot->range_ok=(first==slot->start &&
                            last==slot->start+slot->length-1 &&
                            total==s->upstream_size);
        }
    } else if(len>12 && !strncasecmp(ptr,"Retry-After:",12)) {
        /* Accept a bounded integer Retry-After only; never trust raw text. */
        const char *p=ptr+12,*end=ptr+len;
        while(p<end && (*p==' ' || *p=='\t'))p++;
        long seconds=0;
        const char *first=p;
        while(p<end && *p>='0' && *p<='9'){
            if(seconds<120)seconds=seconds*10+(*p-'0');
            if(seconds>120)seconds=120;
            p++;
        }
        while(p<end && (*p==' ' || *p=='\t' || *p=='\r' || *p=='\n'))p++;
        if(p==end && p>first)slot->retry_after_sec=seconds;
    } else if(len>17 && !strncasecmp(ptr,"Content-Encoding:",17)) {
        /* Byte-for-byte ranges must not be transparently decompressed. */
        const char *value=ptr+17;
        while(value<ptr+len && (*value==' ' || *value=='\t'))value++;
        if(value<ptr+len && strncasecmp(value,"identity",8) &&
           *value!='\r' && *value!='\n')
            slot->encoding_ok=0;
    }
    return len;
}

/* Stage pages are distinct from RAW-owned pages even though the
 * physical allocation is common.  Only the head's byte cursor decides
 * which live slot gets the 6 MiB guaranteed head quota. */
static void nova_lite_release_pages(nova_lite_slot *p)
{
    if(!p || !p->owner || !p->owner->session->warehouse)return;
    nova_shared_warehouse *w=p->owner->session->warehouse;
    int n=p->page_head;
    while(n>=0){
        int next=w->pages[n].next;
        nova_wh_page_free(w,n);
        n=next;
    }
    p->page_head=p->page_tail=-1;
    p->page_count=0;
}
static int nova_lite_staged_pages(nova_lite_state *e)
{
    int n=0;
    for(int i=0;i<NOVA_LITE_SLOTS;i++)n+=e->slots[i].page_count;
    return n;
}
static int nova_lite_can_stage(nova_lite_slot *p,int extra)
{
    nova_lite_state *e=p->owner;
    nova_shared_warehouse *w=e->session->warehouse;
    if(!w || extra<0)return 0;
    int future=p->start>e->session->multi_committed_cursor;
    int limit=future?(int)NOVA_WH_FUTURE_PAGES:(int)NOVA_WH_HEAD_PAGES;
    if(p->page_count+extra>limit ||
       nova_lite_staged_pages(e)+extra>(int)NOVA_WH_STAGE_PAGES)return 0;
    pthread_mutex_lock(&w->lock);
    int free_pages=w->free_count;
    pthread_mutex_unlock(&w->lock);
    return free_pages>=extra;
}
/* NOVA_SHARED42_BACKPRESSURE_V2: exact replay requirements.
 * A paused libcurl callback is replayed in full (it is never partially
 * accepted). Waiting for just 1 page when the pending callback needs 16
 * causes immediate repeated pauses.  This helper executes on the sole
 * CURLM owner (the RAW producer) and never changes HTTP connection/Range. */
static int nova_lite_maybe_resume(nova_lite_slot *p)
{
    if(!p || p->state!=NOVA_MULTI_SLOT_ACTIVE || !p->paused)return 0;
    nova_shared_warehouse *w=p->owner->session->warehouse;
    if(!w)return 0;
    int required=p->pause_need_pages;
    if(required<0 || required>16)return -1;
    if(!nova_lite_can_stage(p,required))return 0;
    int free_before;
    pthread_mutex_lock(&w->lock);
    free_before=w->free_count;
    pthread_mutex_unlock(&w->lock);
    /* curl_easy_pause may synchronously replay the paused write callback:
     * clear 'paused' BEFORE the call; the callback can set it again. */
    p->paused=0;
    p->pause_need_pages=0;
    CURLcode rc=curl_easy_pause(p->easy,CURLPAUSE_CONT);
    if(rc!=CURLE_OK){
        p->paused=1;
        p->pause_need_pages=required;
        LOGI("NOVA_SHARED42_RESUME_ERROR slot=%d curl=%d",
             p->index,(int)rc);
        return -1; /* let the existing transport fallback handle the error */
    }
    LOGI("NOVA_SHARED42_RESUME_V2 slot=%d needPages=%d freeBefore=%d"
         " rePaused=%d nextNeed=%d at=%" PRId64,
         p->index,required,free_before,p->paused,p->pause_need_pages,
         p->start);
    return 1;
}

/* Priority follows the in-order cursor. Do NOT resume a future range
 * while the required head callback is still paused: otherwise repeated
 * small RAW frees can be stolen by future work forever.  Crucially,
 * call this on the empty-page WAIT path as well as after page delivery,
 * so RAW -> free pages -> HTTP resume cannot deadlock. */
static int nova_lite_resume_paused(nova_session *s)
{
    if(!s || !s->lite || !s->warehouse)return 0;
    nova_lite_state *e=s->lite;
    nova_lite_slot *head=NULL;
    for(int i=0;i<NOVA_LITE_SLOTS;i++){
        nova_lite_slot *p=&e->slots[i];
        if(p->state==NOVA_MULTI_SLOT_ACTIVE && p->paused &&
           s->multi_committed_cursor>=p->start &&
           s->multi_committed_cursor<p->start+(int64_t)p->length){
            head=p;
            break;
        }
    }
    if(head){
        int rc=nova_lite_maybe_resume(head);
        if(rc<0)return rc;
        if(head->paused)return rc;
    }
    for(int i=0;i<NOVA_LITE_SLOTS;i++){
        nova_lite_slot *p=&e->slots[i];
        if(p==head || p->state!=NOVA_MULTI_SLOT_ACTIVE || !p->paused)
            continue;
        int rc=nova_lite_maybe_resume(p);
        if(rc<0)return rc;
    }
    return 0;
}
static size_t nova_lite_write(char *ptr,size_t size,size_t nmemb,void *userdata)
{
    nova_lite_slot *p=(nova_lite_slot *)userdata;
    size_t bytes=size*nmemb;
    if(!p || !bytes)return bytes;
    if(p->owner->session->stopping || p->state!=NOVA_MULTI_SLOT_ACTIVE ||
       p->status!=206 || !p->range_ok || !p->encoding_ok ||
       bytes>(size_t)(p->length-p->filled))return 0;
    nova_shared_warehouse *w=p->owner->session->warehouse;
    if(!w || bytes>16u*NOVA_WH_PAGE_BYTES)return 0;
    size_t tailroom=p->page_tail>=0 ?
        NOVA_WH_PAGE_BYTES-(size_t)w->pages[p->page_tail].length : 0;
    size_t beyond=bytes>tailroom?bytes-tailroom:0;
    int extra=(int)((beyond+NOVA_WH_PAGE_BYTES-1)/NOVA_WH_PAGE_BYTES);
    if(!nova_lite_can_stage(p,extra)){
        p->paused=1;
        p->pause_need_pages=extra;
        LOGI("NOVA_SHARED42_PAUSE_V2 slot=%d needPages=%d staged=%d"
             " slotPages=%d future=%d",p->index,extra,
             nova_lite_staged_pages(p->owner),p->page_count,
             p->start>p->owner->session->multi_committed_cursor);
        return CURL_WRITEFUNC_PAUSE; /* callback replay must be whole */
    }
    int fresh[16],count=0;
    for(int k=0;k<extra;k++){
        int n=nova_wh_page_alloc(w,NOVA_WH_STAGE);
        if(n<0){
            for(int j=0;j<count;j++)nova_wh_page_free(w,fresh[j]);
            p->paused=1;
            p->pause_need_pages=extra;
            LOGI("NOVA_SHARED42_PAUSE_ALLOC_V2 slot=%d needPages=%d",
                 p->index,extra);
            return CURL_WRITEFUNC_PAUSE;
        }
        fresh[count++]=n;
    }
    const uint8_t *src=(const uint8_t *)ptr;
    size_t left=bytes;
    int nextnew=0;
    while(left){
        if(p->page_tail<0 ||
           w->pages[p->page_tail].length==(int)NOVA_WH_PAGE_BYTES){
            int n=fresh[nextnew++];
            if(p->page_tail<0)p->page_head=n;
            else w->pages[p->page_tail].next=n;
            p->page_tail=n;
            p->page_count++;
        }
        nova_wh_page *page=&w->pages[p->page_tail];
        size_t room=NOVA_WH_PAGE_BYTES-(size_t)page->length;
        size_t take=left<room?left:room;
        memcpy(nova_wh_page_ptr(w,p->page_tail)+page->length,src,take);
        page->length+=(int)take;
        src+=take;
        left-=take;
    }
    p->filled+=(int)bytes;
    p->owner->received_sample_bytes+=(uint64_t)bytes;
    return bytes;
}

static int nova_lite_prepare(nova_session *s)
{
    if(s->lite)return 0;
    if(!s->warehouse)s->warehouse=nova_shared_warehouse_new();
    if(!s->warehouse)return AVERROR(ENOMEM);
    pthread_once(&nova_lite_curl_once,nova_lite_curl_initialize);
    nova_lite_state *e=(nova_lite_state *)calloc(1,sizeof(*e));
    if(!e)return AVERROR(ENOMEM);
    e->session=s;
    e->multi=curl_multi_init();
    if(!e->multi){free(e);return AVERROR(ENOMEM);}
    unsigned encoded=0,bad_pct=0;
    e->request_url=nova_lite_encode_url(s->origin_url,&encoded,&bad_pct);
    LOGI("NOVA_LITERANGE4_URL valid=%d encodedBytes=%u invalidPct=%u schemeHttps=%d",
         e->request_url!=NULL,encoded,bad_pct,
         s->origin_url && !strncasecmp(s->origin_url,"https://",8));
    if(!e->request_url){curl_multi_cleanup(e->multi);free(e);return AVERROR(EINVAL);}
    nova_lite_load_android_roots(e);
    curl_multi_setopt(e->multi,CURLMOPT_MAX_TOTAL_CONNECTIONS,4L);
    curl_multi_setopt(e->multi,CURLMOPT_MAX_HOST_CONNECTIONS,4L);
    curl_multi_setopt(e->multi,CURLMOPT_MAXCONNECTS,4L);
    for(int i=0;i<NOVA_LITE_SLOTS;++i){
        nova_lite_slot *p=&e->slots[i];
        p->owner=e;
        p->index=i;
        p->page_head=p->page_tail=-1;
        p->page_count=0;
        p->easy=curl_easy_init();
        if(!p->easy){
            for(int k=0;k<=i;++k){
                if(e->slots[k].easy)curl_easy_cleanup(e->slots[k].easy);
            }
            curl_multi_cleanup(e->multi);
            free(e->request_url);
            free(e->ca_pem);
            free(e);
            return AVERROR(ENOMEM);
        }
    }
    s->lite=e;
    s->multi_buffers_ready=1;
    LOGI("NOVA_LITERANGE4_INIT workers=0 maxConnections=4 stagingBytes=%d",
         NOVA_LITE_STAGE_BYTES);
    return 0;
}

static void nova_lite_reset_slots(nova_session *s)
{
    nova_lite_state *e=s->lite;
    if(!e)return;
    for(int i=0;i<NOVA_LITE_SLOTS;++i){
        nova_lite_slot *p=&e->slots[i];
        if(p->state==NOVA_MULTI_SLOT_ACTIVE)
            curl_multi_remove_handle(e->multi,p->easy);
        if(p->headers){curl_slist_free_all(p->headers);p->headers=NULL;}
        nova_lite_release_pages(p);
        p->state=NOVA_MULTI_SLOT_EMPTY;
        p->filled=0;
        p->delivered=0;
        p->paused=0;
        p->pause_need_pages=0;
        p->range_ok=0;
    }
    e->running=0;
}

/* Reusing one CURLM retains connection and DNS caches between bounded
 * requests. An easy handle is reset, not destroyed, for each next Range. */
static int nova_lite_launch(nova_lite_slot *p)
{
    nova_lite_state *e=p->owner;
    nova_session *s=e->session;
    curl_easy_reset(p->easy);
    p->curl_error[0]=0;
    p->status=0;
    p->range_ok=0;
    p->encoding_ok=1;
    p->retry_after_sec=0;
    p->filled=0;
    p->delivered=0;
    p->paused=0;
    p->pause_need_pages=0;
    p->page_head=p->page_tail=-1;
    p->page_count=0;
    snprintf(p->range_str,sizeof(p->range_str),"%" PRId64 "-%" PRId64,
             p->start,p->start+(int64_t)p->length-1);
    if(p->headers){curl_slist_free_all(p->headers);p->headers=NULL;}
    p->headers=curl_slist_append(p->headers,"Accept-Encoding: identity");
    if(s->origin_auth && *s->origin_auth){
        size_t n=strlen(s->origin_auth)+16;
        char *line=(char *)malloc(n);
        if(!line)return AVERROR(ENOMEM);
        snprintf(line,n,"Authorization: %s",s->origin_auth);
        struct curl_slist *more=curl_slist_append(p->headers,line);
        free(line);
        if(!more)return AVERROR(ENOMEM);
        p->headers=more;
    }
    CURL *c=p->easy;
    CURLcode opt=CURLE_OK;
#define NOVA_CURL_SET(option,value) do { \
    CURLcode checked=curl_easy_setopt(c,option,value); \
    if(checked!=CURLE_OK && opt==CURLE_OK)opt=checked; \
}while(0)
    NOVA_CURL_SET(CURLOPT_ERRORBUFFER,p->curl_error);
    NOVA_CURL_SET(CURLOPT_URL,e->request_url);
    NOVA_CURL_SET(CURLOPT_RANGE,p->range_str);
    NOVA_CURL_SET(CURLOPT_HTTPHEADER,p->headers);
    NOVA_CURL_SET(CURLOPT_WRITEFUNCTION,nova_lite_write);
    NOVA_CURL_SET(CURLOPT_WRITEDATA,p);
    NOVA_CURL_SET(CURLOPT_HEADERFUNCTION,nova_lite_header);
    NOVA_CURL_SET(CURLOPT_HEADERDATA,p);
    NOVA_CURL_SET(CURLOPT_NOSIGNAL,1L);
    NOVA_CURL_SET(CURLOPT_FOLLOWLOCATION,1L);
    NOVA_CURL_SET(CURLOPT_MAXREDIRS,5L);
    NOVA_CURL_SET(CURLOPT_UNRESTRICTED_AUTH,0L);
    NOVA_CURL_SET(CURLOPT_PROTOCOLS_STR,"http,https");
    NOVA_CURL_SET(CURLOPT_REDIR_PROTOCOLS_STR,
                     !strncasecmp(s->origin_url,"https:",6)?"https":"http,https");
    NOVA_CURL_SET(CURLOPT_SSL_VERIFYPEER,1L);
    NOVA_CURL_SET(CURLOPT_SSL_VERIFYHOST,2L);
    if(e->ca_pem){
        struct curl_blob certs={e->ca_pem,e->ca_pem_len,CURL_BLOB_NOCOPY};
        NOVA_CURL_SET(CURLOPT_CAINFO_BLOB,&certs);
    }else{
        NOVA_CURL_SET(CURLOPT_CAPATH,"/system/etc/security/cacerts");
    }
    NOVA_CURL_SET(CURLOPT_HTTP_VERSION,CURL_HTTP_VERSION_1_1);
    NOVA_CURL_SET(CURLOPT_CONNECTTIMEOUT_MS,10000L);
    NOVA_CURL_SET(CURLOPT_LOW_SPEED_LIMIT,1024L);
    NOVA_CURL_SET(CURLOPT_LOW_SPEED_TIME,15L);
    NOVA_CURL_SET(CURLOPT_TCP_KEEPALIVE,1L);
    NOVA_CURL_SET(CURLOPT_FRESH_CONNECT,0L);
    NOVA_CURL_SET(CURLOPT_FORBID_REUSE,0L);
    NOVA_CURL_SET(CURLOPT_TCP_NODELAY,1L);
    NOVA_CURL_SET(CURLOPT_ACCEPT_ENCODING,"identity");
#undef NOVA_CURL_SET
    if(opt!=CURLE_OK){
        LOGI("NOVA_LITERANGE4_OPTION_ERROR curl=%d slot=%d",opt,p->index);
        return AVERROR(EINVAL);
    }
    CURLMcode rc=curl_multi_add_handle(e->multi,c);
    if(rc!=CURLM_OK)return AVERROR(EIO);
    p->state=NOVA_MULTI_SLOT_ACTIVE;
    e->running++;
    return 0;
}

/* 4X is a LENGTH, never a global byte-alignment boundary.
 * A seek to S must start exactly at S and use S+4X for the next slice.
 * Avoid a 32 MiB minimum: small/short media still use their real 4X. */
static uint64_t nova_lite_piece_quantum(nova_session *s)
{
    uint64_t x=0;
    pthread_mutex_lock(&s->multi_lock);
    x=s->adaptive_target_bps;
    pthread_mutex_unlock(&s->multi_lock);
    if(!x)return 1024 * 1024; /* temporary pre-probe choice */
    if(x>UINT64_MAX/NOVA_LITE_SEGMENT_SECONDS)
        return NOVA_LITE_MAX_PIECE_BYTES;
    uint64_t quantum=x*NOVA_LITE_SEGMENT_SECONDS;
    if(quantum<64*1024)quantum=64*1024;
    if(quantum>NOVA_LITE_MAX_PIECE_BYTES)
        quantum=NOVA_LITE_MAX_PIECE_BYTES;
    return quantum;
}

static int nova_lite_piece_length(nova_session *s,int64_t start)
{
    nova_lite_state *e=s->lite;
    uint64_t quantum=e && e->piece_bytes ? e->piece_bytes
                                         : nova_lite_piece_quantum(s);
    uint64_t remain=(uint64_t)(s->upstream_size-start);
    if(quantum>remain)quantum=remain;
    return (int)quantum;
}

/* W2_INORDER_GATE: completed-but-uncommitted future work still occupies
 * its slot. This is *not* curl's active request count: if B completes
 * before A, B holds the second reservation and there is no request C.
 * Once A is consumed into RAW, release A's slot and start C promptly;
 * after B commits, also start D. Never pre-queue beyond two slices.
 * Existing HTTP transfers are not cancelled for opportunistic stealing.
 */
static void nova_lite_schedule(nova_session *s)
{
    nova_lite_state *e=s->lite;
    if(!e || !s->multi_run || s->stopping)return;
    int used=0, active=0, ready_behind=0;
    int64_t cursor=s->multi_committed_cursor;
    for(int i=0;i<NOVA_LITE_SLOTS;++i){
        nova_lite_slot *p=&e->slots[i];
        if(p->state==NOVA_MULTI_SLOT_EMPTY)continue;
        used++;
        if(p->state==NOVA_MULTI_SLOT_ACTIVE)active++;
        if(p->state==NOVA_MULTI_SLOT_READY && p->start>cursor)
            ready_behind++;
    }
    if(used>=s->multi_active_lanes || used>=NOVA_LITE_SLOTS){
        int64_t now=nova_iso_uptime_ms();
        if(ready_behind && now-e->last_gate_log_ms>=1500){
            e->last_gate_log_ms=now;
            LOGI("NOVA_LITERANGE4_PAIR_HOLD cursor=%" PRId64
                 " occupied=%d active=%d readyAhead=%d",
                 cursor,used,active,ready_behind);
        }
        return;
    }
    /* The bitrate becomes known after probing. Freeze 4X from the next
     * available slice; any currently ACTIVE range keeps its original end. */
    if(e->piece_bytes==1024*1024 && s->adaptive_target_bps>0){
        e->piece_bytes=nova_lite_piece_quantum(s);
        e->piece_origin=s->multi_next_offset;
        LOGI("NOVA_LITERANGE4_RATE_READY origin=%" PRId64
             " piece=%" PRIu64 " x=%" PRIu64,
             e->piece_origin,e->piece_bytes,s->adaptive_target_bps);
    }
    while(used<s->multi_active_lanes && used<NOVA_LITE_SLOTS &&
          s->multi_next_offset<s->upstream_size){
        nova_lite_slot *p=NULL;
        for(int i=0;i<NOVA_LITE_SLOTS;++i)
            if(e->slots[i].state==NOVA_MULTI_SLOT_EMPTY){
                p=&e->slots[i];break;
            }
        if(!p)break;
        p->start=s->multi_next_offset;
        p->length=nova_lite_piece_length(s,p->start);
        if(p->length<=0){p->state=NOVA_MULTI_SLOT_ERROR;break;}
        s->multi_next_offset+=p->length;
        p->state=NOVA_MULTI_SLOT_QUEUED;
        p->filled=0;
        p->delivered=0;
        p->paused=0;
        LOGI("NOVA_LITERANGE4_PIECE slot=%d from=%" PRId64
             " to=%" PRId64 " len=%d x=%" PRIu64
             " window=2",
             p->index,p->start,p->start+(int64_t)p->length,p->length,
             s->adaptive_target_bps);
        used++;
        if(nova_lite_launch(p)<0){
            p->state=NOVA_MULTI_SLOT_ERROR;
            break;
        }
    }
}

static void nova_lite_complete(nova_session *s)
{
    nova_lite_state *e=s->lite;
    int pending=0;
    CURLMsg *msg;
    while((msg=curl_multi_info_read(e->multi,&pending))!=NULL){
        if(msg->msg!=CURLMSG_DONE)continue;
        nova_lite_slot *p=NULL;
        for(int i=0;i<NOVA_LITE_SLOTS;++i)
            if(e->slots[i].easy==msg->easy_handle){p=&e->slots[i];break;}
        if(!p)continue;
        long code=0;
        curl_easy_getinfo(p->easy,CURLINFO_RESPONSE_CODE,&code);
        /* NOVA_LITERANGE4_CONN_V1: query before remove_handle; do not log
         * URL, host, IP, auth, signed redirect, or curl error text. */
        long new_connections=0,redirects=0;
        curl_off_t conn_id=-1,connect_us=0,tls_end_us=0,ttfb_us=0,total_us=0;
        curl_easy_getinfo(p->easy,CURLINFO_NUM_CONNECTS,&new_connections);
        curl_easy_getinfo(p->easy,CURLINFO_REDIRECT_COUNT,&redirects);
        curl_easy_getinfo(p->easy,CURLINFO_CONN_ID,&conn_id);
        curl_easy_getinfo(p->easy,CURLINFO_CONNECT_TIME_T,&connect_us);
        curl_easy_getinfo(p->easy,CURLINFO_APPCONNECT_TIME_T,&tls_end_us);
        curl_easy_getinfo(p->easy,CURLINFO_STARTTRANSFER_TIME_T,&ttfb_us);
        curl_easy_getinfo(p->easy,CURLINFO_TOTAL_TIME_T,&total_us);
        if(new_connections<0)new_connections=0;
        uint64_t connect_ms=connect_us>0?(uint64_t)connect_us/1000:0;
        uint64_t tls_ms=tls_end_us>connect_us?
            (uint64_t)(tls_end_us-connect_us)/1000:0;
        uint64_t first_byte_ms=ttfb_us>0?(uint64_t)ttfb_us/1000:0;
        uint64_t duration_ms=total_us>0?(uint64_t)total_us/1000:0;
        /* NUM_CONNECTS accounts for all hops in a redirected transfer:
         * redirects=1 is NOT evidence of a new socket. Count reuse only
         * after a complete verified final 206; failed preconnect is not reuse. */
        int valid206=code==206 && msg->data.result==CURLE_OK &&
                     p->range_ok && p->encoding_ok && p->filled==p->length;
        int reused=valid206 && new_connections==0;
        e->metric_requests++;
        e->metric_new_connections+=(uint64_t)new_connections;
        if(reused)e->metric_reused_requests++;
        e->metric_connect_ms+=connect_ms;
        e->metric_tls_ms+=tls_ms;
        e->metric_ttfb_ms+=first_byte_ms;
        LOGI("NOVA_LITERANGE4_CONN slot=%d at=%" PRId64
             " len=%d new=%ld reused=%d connId=%" PRId64
             " connectMs=%" PRIu64 " tlsMs=%" PRIu64
             " ttfbMs=%" PRIu64 " totalMs=%" PRIu64
             " redirects=%ld http=%ld curl=%d",
             p->index,p->start,p->length,new_connections,reused,
             (int64_t)conn_id,connect_ms,tls_ms,first_byte_ms,
             duration_ms,redirects,code,(int)msg->data.result);
        if(e->metric_requests%10==0){
            LOGI("NOVA_LITERANGE4_CONN_SUMMARY requests=%" PRIu64
                 " newConnections=%" PRIu64 " reused=%" PRIu64
                 " newPer100=%" PRIu64 " avgConnectMs=%" PRIu64
                 " avgTlsMs=%" PRIu64 " avgTtfbMs=%" PRIu64,
                 e->metric_requests,e->metric_new_connections,
                 e->metric_reused_requests,
                 e->metric_new_connections*100/e->metric_requests,
                 e->metric_connect_ms/e->metric_requests,
                 e->metric_tls_ms/e->metric_requests,
                 e->metric_ttfb_ms/e->metric_requests);
        }
        curl_multi_remove_handle(e->multi,p->easy);
        if(p->headers){curl_slist_free_all(p->headers);p->headers=NULL;}
        if(e->running>0)e->running--;
        if(msg->data.result==CURLE_OK && code==206 &&
           p->range_ok && p->encoding_ok && p->filled==p->length){
            /* Following HTTP403, promote to W2 only after one verified 206.
             * After eight clean paired segments, clear the backoff history. */
            if(s->multi_http403_failures){
                /* Reset limiter history only after sustained error-free time.
                 * Eight clean ranges prove data integrity, NOT that WebDAV
                 * has stopped rate-limiting us for the next few seconds. */
                int64_t now=nova_iso_uptime_ms();
                if(s->multi_backoff_last_failure_ms>0 &&
                   now>=s->multi_backoff_last_failure_ms &&
                   now-s->multi_backoff_last_failure_ms>=NOVA_MULTI_BACKOFF_RESET_MS){
                    LOGI("NOVA_MULTI_RANGE_HISTORY_CLEAR quietMs=%" PRId64
                         " priorFailures=%u",
                         now-s->multi_backoff_last_failure_ms,
                         s->multi_http403_failures);
                    s->multi_http403_failures=0;
                    s->multi_http403_retry_ms=0;
                    s->multi_backoff_last_failure_ms=0;
                    s->multi_backoff_recovered_logged=0;
                    s->multi_backoff_status=0;
                }else{
                    e->successful_ranges++;
                    if(s->multi_active_lanes==2 && e->successful_ranges>=8 &&
                       !s->multi_backoff_recovered_logged){
                        if(s->multi_backoff_status==403)
                            LOGI("NOVA_MULTI_HTTP403_RECOVERED validRanges=%u",
                                 e->successful_ranges);
                        else
                            LOGI("NOVA_MULTI_RANGE_RECOVERED validRanges=%u",
                                 e->successful_ranges);
                        /* Mark this epoch healthy, but retain backoff tier. */
                        s->multi_backoff_recovered_logged=1;
                    }
                }
            }
            /* A piece may already be fully consumed before CURLMSG_DONE. */
            if(p->delivered==p->length){
                p->state=NOVA_MULTI_SLOT_EMPTY;
                p->filled=0;
                p->delivered=0;
            }else p->state=NOVA_MULTI_SLOT_READY;
            p->paused=0;
            p->pause_need_pages=0;
        }else{
            p->state=NOVA_MULTI_SLOT_ERROR;
            long ssl_verify=0,redirects=0;
            curl_easy_getinfo(p->easy,CURLINFO_SSL_VERIFYRESULT,&ssl_verify);
            curl_easy_getinfo(p->easy,CURLINFO_REDIRECT_COUNT,&redirects);
            e->last_curl_error=msg->data.result;
            e->last_http_status=code;
            e->last_retry_after_sec=p->retry_after_sec;
            /* Never print libcurl error text: some backends include signed
             * CDN URLs or Authorization fragments in it. Codes are safe. */
            LOGI("NOVA_LITERANGE4_RANGE_ERROR status=%ld curl=%d tlsVerify=%ld at=%" PRId64
                 " received=%d requested=%d redirects=%ld",
                 code,(int)msg->data.result,ssl_verify,p->start,p->filled,p->length,redirects);
        }
    }
}

static int nova_multi_session_init(nova_session *s)
{
    if(!s)return -1;
    if(pthread_mutex_init(&s->multi_lock,NULL))return -1;
    if(pthread_cond_init(&s->multi_cond,NULL)){
        pthread_mutex_destroy(&s->multi_lock);
        return -1;
    }
    s->multi_sync_ready=1;
    s->adaptive_lanes=1;
    s->multi_seek_restore_lanes=1;
    return 0;
}

static void nova_multi_reset_sample(nova_session *s)
{
    if(!s || !s->lite)return;
    s->lite->last_sample_ms=nova_iso_uptime_ms();
    s->lite->committed_sample_bytes=0;
    s->lite->received_sample_bytes=0;
    s->lite->starvation_count=0;
    s->lite->last_starve_tick_ms=0;
}

static void nova_multi_set_target(nova_session *s,uint64_t target_bps)
{
    if(!s || !s->multi_sync_ready)return;
    pthread_mutex_lock(&s->multi_lock);
    s->adaptive_target_bps=target_bps;
    pthread_mutex_unlock(&s->multi_lock);
    LOGI("NOVA_LITERANGE4_TARGET bytesPerSec=%" PRIu64
         " maxLanes=4 workers=0 stagingBytes=%d",
         target_bps,NOVA_LITE_STAGE_BYTES);
}

static void nova_adaptive_record_single(nova_session *s,int bytes)
{
    (void)s;(void)bytes;
    /* The lite source is already a persistent single native Range. */
}
static int nova_adaptive_take_upgrade(nova_session *s)
{
    (void)s;
    return 0;
}
static int nova_multi_current_lanes(nova_session *s)
{
    return s && s->multi_active?s->multi_active_lanes:1;
}

static int nova_multi_start(nova_session *s,int64_t start,int lanes)
{
    if(!s || !s->multi_http_ready || !s->origin_url || !*s->origin_url ||
       s->stopping || start<0 || start>=s->upstream_size ||
       lanes<1 || lanes>NOVA_MULTI_MAX_LANES)return AVERROR(EINVAL);
    if(s->multi_disabled)return AVERROR(EPERM);
    if(s->multi_active)return 0;
    int rc=nova_lite_prepare(s);
    if(rc<0)return rc;
    s->multi_generation++;
    s->multi_run=1;
    s->multi_active=1;
    /* This variant has exactly two slots. Even a seek restoring 4 old
     * lanes must be capped at two when the new epoch is created. */
    lanes=lanes>2?2:lanes;
    if(s->multi_http403_failures)lanes=1; /* safe W1 after backoff/seek */
    else if(s->adaptive_target_bps>0)lanes=2;
    s->multi_active_lanes=lanes;
    s->adaptive_lanes=lanes;
    s->multi_committed_cursor=start;
    s->multi_next_offset=start;
    s->lite->generation=s->multi_generation;
    s->lite->piece_origin=start;
    s->lite->piece_bytes=nova_lite_piece_quantum(s);
    s->lite->last_gate_log_ms=0;
    LOGI("NOVA_LITERANGE4_REBASE origin=%" PRId64
         " piece=%" PRIu64 " x=%" PRIu64
         " generation=%" PRIu64 " lanes=%d",
         start,s->lite->piece_bytes,s->adaptive_target_bps,
         s->multi_generation,lanes);
    s->lite->last_raise_ms=nova_iso_uptime_ms();
    s->lite->last_curl_error=CURLE_OK;
    s->lite->last_http_status=0;
    s->lite->last_retry_after_sec=0;
    s->lite->successful_ranges=0;
    nova_multi_reset_sample(s);
    nova_lite_schedule(s);
    /* Leave Java connections and the legacy AVIO path available only as
     * explicit failure fallbacks; no JNI in steady-state movie delivery. */
    if(s->file_http_mode)nova_file_java_close_active(s);
    LOGI("NOVA_LITERANGE4_START maxLanes=%d lanes=%d threads=0"
         " at=%" PRId64 " stagingBytes=%d",
         NOVA_MULTI_MAX_LANES,lanes,start,
         NOVA_LITE_STAGE_BYTES);
    return 0;
}

/* abort can be called by a different thread: never touch CURLM here. */
static void nova_multi_abort(nova_session *s)
{
    if(s)s->stopping=1;
}

static void nova_multi_stop(nova_session *s,const char *reason,int disable)
{
    if(!s || !s->multi_sync_ready)return;
    int previous=s->multi_active_lanes;
    nova_lite_reset_slots(s);
    s->multi_active=0;
    s->multi_run=0;
    s->multi_active_lanes=1;
    s->adaptive_lanes=1;
    if(disable)s->multi_disabled=1;
    nova_multi_reset_sample(s);
    if(previous>1 || (reason && strcmp(reason,"session-free")))
        LOGI("NOVA_LITERANGE4_STOP reason=%s previous=%d",
             reason?reason:"unknown",previous);
}

static void nova_lite_telemetry(nova_session *s,int waited_ms)
{
    nova_lite_state *e=s->lite;
    int64_t now=nova_iso_uptime_ms();
    if(!e)return;
    if(waited_ms>=NOVA_LITE_WAIT_TRIGGER_MS){
        if(e->starvation_count<1000)e->starvation_count++;
    }
    if(e->last_sample_ms<=0)e->last_sample_ms=now;
    if(now-e->last_sample_ms<1500)return;
    uint64_t delivered=e->committed_sample_bytes*1000ULL/
                       (uint64_t)(now-e->last_sample_ms);
    uint64_t received=e->received_sample_bytes*1000ULL/
                      (uint64_t)(now-e->last_sample_ms);
    uint64_t target=0;
    pthread_mutex_lock(&s->multi_lock);
    target=s->adaptive_target_bps;
    pthread_mutex_unlock(&s->multi_lock);
    LOGI("NOVA_LITERANGE4_NET lanes=%d deliveredBps=%" PRIu64
         " targetBps=%" PRIu64 " blocked=%u pending=%d wireBps=%" PRIu64,
         s->multi_active_lanes,delivered,target,
         e->starvation_count,e->running,received);
    /* W=2 only, never the obsolete 1->2->3->4 escalation.
     * Start second lane once real X is known; completed future work
     * remains a reservation until prefix is committed. */
    /* A repeat denial needs two verified full 206s before W2; the
     * first denial keeps the previously proven single-range rearm rule.
     * Never upgrade just because time has elapsed or single GET opened. */
    unsigned required_valid=s->multi_http403_failures>1?2:1;
    if(target>0 && s->multi_active_lanes<2 && !s->multi_seek_guard &&
       (!s->multi_http403_failures ||
        e->successful_ranges>=required_valid)){
        if(s->multi_http403_failures)
            LOGI("NOVA_MULTI_PAIR_REARM verified=%u required=%u failures=%u",
                 e->successful_ranges,required_valid,s->multi_http403_failures);
        s->multi_active_lanes=2;
        LOGI("NOVA_LITERANGE4_PAIR_ENABLE x=%" PRIu64
             " from=1 to=2",target);
        nova_lite_schedule(s);
    }
    e->committed_sample_bytes=0;
    e->received_sample_bytes=0;
    e->starvation_count=0;
    e->last_sample_ms=now;
}

/* Non-ISO transfers ownership of a staged page directly to RAW.
 * ISO/libbluray retains bytewise reads from the same staged page chain. */
static int nova_multi_read_core(nova_session *s,uint8_t *dst,int size,
                                int *out_page)
{
    if(!s || size<=0 || !s->lite || !s->multi_active ||
       (!dst && !out_page))return NOVA_MULTI_FALLBACK;
    if(out_page)*out_page=-1;
    nova_lite_state *e=s->lite;
    nova_shared_warehouse *w=s->warehouse;
    int64_t began=nova_iso_uptime_ms();
    while(!s->stopping && s->multi_run){
        if(s->multi_committed_cursor>=s->upstream_size)return AVERROR_EOF;
        nova_lite_slot *current=NULL;
        for(int i=0;i<NOVA_LITE_SLOTS;++i){
            nova_lite_slot *p=&e->slots[i];
            if(p->state!=NOVA_MULTI_SLOT_EMPTY &&
               s->multi_committed_cursor>=p->start &&
               s->multi_committed_cursor<p->start+p->length){
                current=p;break;
            }
        }
        if(current &&
           (current->state==NOVA_MULTI_SLOT_ACTIVE ||
            current->state==NOVA_MULTI_SLOT_READY) &&
           current->status==206 && current->range_ok &&
           current->encoding_ok){
            int offset=(int)(s->multi_committed_cursor-current->start);
            if(offset!=current->delivered)return NOVA_MULTI_FALLBACK;
            int n=current->page_head;
            int available=current->filled-current->delivered;
            if(available>0 && n>=0){
                nova_wh_page *page=&w->pages[n];
                int unread=page->length-page->consumed;
                if(unread<=0)return NOVA_MULTI_FALLBACK;
                /* Preserve page density: wait for a full 64 KiB page
                 * while an HTTP response is still delivering.  Publishing
                 * 16 KiB libcurl callbacks as separate pages would consume
                 * the physical page pool 4x faster than its byte budget. */
                if(out_page && page->length<(int)NOVA_WH_PAGE_BYTES &&
                   current->state==NOVA_MULTI_SLOT_ACTIVE &&
                   current->filled<current->length)
                    goto shared42_await_more;
                int take=out_page?unread:(unread<size?unread:size);
                if(out_page && unread>size)return NOVA_MULTI_FALLBACK;
                if(!out_page)memcpy(dst,nova_wh_page_ptr(w,n)+page->consumed,
                                    (size_t)take);
                current->delivered+=take;
                s->multi_committed_cursor+=take;
                if(s->mode==NOVA_MODE_FILE)s->file_cursor=s->multi_committed_cursor;
                e->committed_sample_bytes+=(uint64_t)take;
                if(out_page || page->consumed+take==page->length){
                    current->page_head=page->next;
                    if(current->page_head<0)current->page_tail=-1;
                    current->page_count--;
                    page->next=-1;
                    if(out_page){
                        /* NOVA_SHARED42_MKV_PAGE_VIEW_V1: preserve the
                         * consumed prefix, exposed by page_data/length.
                         * The remaining bytes transfer by descriptor only. */
                        page->state=NOVA_WH_RAW;
                        *out_page=n;
                    }else nova_wh_page_free(w,n);
                }else page->consumed+=take;
                if(current->state==NOVA_MULTI_SLOT_READY &&
                   current->delivered==current->length){
                    current->state=NOVA_MULTI_SLOT_EMPTY;
                    current->filled=0;
                    current->delivered=0;
                    current->page_head=current->page_tail=-1;
                    current->page_count=0;
                }else if(nova_lite_resume_paused(s)<0)
                    return NOVA_MULTI_FALLBACK;
                nova_lite_schedule(s);
                int64_t waited=nova_iso_uptime_ms()-began;
                nova_lite_telemetry(s,waited>INT32_MAX?INT32_MAX:(int)waited);
                return take;
            }
        }
        if(current && current->state==NOVA_MULTI_SLOT_ERROR)
            return NOVA_MULTI_FALLBACK;
shared42_await_more:
        nova_lite_schedule(s);
        /* This is the essential liveness edge. RAW may have released
         * pages while the current HTTP callback was paused and there
         * were no full staging pages left to deliver. */
        if(nova_lite_resume_paused(s)<0)return NOVA_MULTI_FALLBACK;
        int running=0;
        CURLMcode rc=curl_multi_perform(e->multi,&running);
        if(rc!=CURLM_OK)return NOVA_MULTI_FALLBACK;
        nova_lite_complete(s);
        int64_t tick=nova_iso_uptime_ms();
        if(tick-e->last_starve_tick_ms>=NOVA_LITE_WAIT_TRIGGER_MS &&
           tick-began>=NOVA_LITE_WAIT_TRIGGER_MS){
            e->last_starve_tick_ms=tick;
            nova_lite_telemetry(s,NOVA_LITE_WAIT_TRIGGER_MS);
        }
        if(s->stopping)return AVERROR_EXIT;
        if(running>0){
            int fds=0;
            rc=curl_multi_poll(e->multi,NULL,0,NOVA_LITE_POLL_MS,&fds);
            if(rc!=CURLM_OK)return NOVA_MULTI_FALLBACK;
        }else{
            if(e->running==0 && s->multi_next_offset>=s->upstream_size &&
               !current)return NOVA_MULTI_FALLBACK;
        }
    }
    return AVERROR_EXIT;
}
static int nova_multi_read(nova_session *s,uint8_t *dst,int size)
{
    return nova_multi_read_core(s,dst,size,NULL);
}
static int nova_multi_take_page(nova_session *s,int *page,int max_bytes)
{
    return nova_multi_read_core(s,NULL,max_bytes,page);
}

static int nova_multi_read_exact_at(nova_session *s,uint8_t *dst,
                                    int64_t target,int bytes)
{
    if(!s || !dst || bytes<=0 || target<0 ||
       s->upstream_size<=0 || target>s->upstream_size ||
       (int64_t)bytes>s->upstream_size-target)return -1;
    if(s->multi_active && s->multi_committed_cursor!=target)
        nova_multi_stop(s,"iso-lba-jump",0);
    if(!s->multi_active && !s->multi_disabled){
        if(nova_multi_start(s,target,1)<0)s->multi_disabled=1;
    }
    if(s->multi_active){
        int done=0;
        while(done<bytes && !s->stopping){
            int got=nova_multi_read(s,dst+done,bytes-done);
            if(got<=0)break;
            done+=got;
        }
        if(done==bytes)return done;
        nova_multi_stop(s,"iso-range-fallback",1);
        int rest=nova_upstream_read_exact_retry(s,dst+done,target+done,bytes-done);
        return rest==bytes-done?bytes:-1;
    }
    return nova_upstream_read_exact_retry(s,dst,target,bytes);
}

static void nova_multi_destroy(nova_session *s)
{
    if(!s || !s->multi_sync_ready)return;
    nova_multi_stop(s,"session-free",1);
    nova_lite_state *e=s->lite;
    if(e){
        for(int i=0;i<NOVA_LITE_SLOTS;++i){
            nova_lite_slot *p=&e->slots[i];
            if(p->headers)curl_slist_free_all(p->headers);
            if(p->easy)curl_easy_cleanup(p->easy);
        }
        if(e->multi)curl_multi_cleanup(e->multi);
        free(e->request_url);
        free(e->ca_pem);
        free(e);
        s->lite=NULL;
    }
    pthread_cond_destroy(&s->multi_cond);
    pthread_mutex_destroy(&s->multi_lock);
    s->multi_sync_ready=0;
}
