/*
 * NOVA_1073_BLACKBOX_V1: process-lifetime ISO first-cause diagnostics.
 *
 * No CURL, libbluray, decoder, RAW buffer, user URL, credentials or media
 * packet is accessed by the observer. Every event is a bounded, fixed-size
 * lock-free-state sample plus a best-effort trylock into an in-memory ring.
 * No allocation occurs on a transport hot path, and no lock is held while
 * writing logs or traversing /proc.
 */
#include <dirent.h>
#include <sys/syscall.h>
#include <sys/types.h>

#define NOVA_BB_RING_LEN 8192
#define NOVA_BB_PHASES 6
#define NOVA_BB_HISTORY_MS 120000
#define NOVA_BB_STUCK_MS 5000

enum nova_bb_phase_id {
    NOVA_BB_BD=0, NOVA_BB_CURL=1, NOVA_BB_POLL=2,
    NOVA_BB_RAW=3, NOVA_BB_DEMUX=4, NOVA_BB_CLOSE=5
};
enum nova_bb_event_id {
    NOVA_BB_OPEN=1, NOVA_BB_READY=2, NOVA_BB_CLOSE_BEGIN=3,
    NOVA_BB_CLOSE_DONE=4, NOVA_BB_PUMP_JOIN=5,
    NOVA_BB_PUMP_JOINED=6, NOVA_BB_CALLS_WAIT=7,
    NOVA_BB_CALLS_DRAINED=8, NOVA_BB_REPLAY_ALLOC=9,
    NOVA_BB_REPLAY_FREE=10, NOVA_BB_META_ALLOC=11,
    NOVA_BB_META_FREE=12, NOVA_BB_WAREHOUSE=13,
    NOVA_BB_CBE_FAIL=14, NOVA_BB_CBE_OK=15,
    NOVA_BB_FFMPEG_ENOMEM=16, NOVA_BB_PAUSE=17,
    NOVA_BB_RESUME=18, NOVA_BB_REBASE=19,
    NOVA_BB_SLOW_PHASE=20, NOVA_BB_READ_FAIL=21,
    NOVA_BB_FIRST_FRAME=22, NOVA_BB_PUMP_START=23,
    NOVA_BB_PUMP_END=24, NOVA_BB_ALLOC_FAILURE=25
};
typedef struct nova_bb_entry {
    int64_t ms, a, b;
    uint64_t gen;
    int tid, kind;
} nova_bb_entry;
typedef struct nova_bb_phase {
    volatile int64_t since_ms;
    volatile int tid;
    volatile int64_t arg;
    volatile int64_t last_dump_ms;
} nova_bb_phase;
static nova_bb_entry g_bb_ring[NOVA_BB_RING_LEN];
static nova_bb_entry g_bb_frozen[NOVA_BB_RING_LEN];
static pthread_mutex_t g_bb_lock=PTHREAD_MUTEX_INITIALIZER;
static volatile uint64_t g_bb_head=0;
static volatile uint64_t g_bb_dropped=0;
static nova_bb_phase g_bb_phases[NOVA_BB_PHASES];
static volatile uint64_t g_bb_gen=0;
static volatile int g_bb_mode=-1;
static volatile int g_bb_first_fault=0;
static volatile int g_bb_freeze_pending=0;
static volatile int g_bb_armed=0;
static volatile int g_bb_watch_started=0;
static pthread_once_t g_bb_watch_once=PTHREAD_ONCE_INIT;

static int nova_bb_tid(void)
{
    return (int)syscall(SYS_gettid);
}
static void nova_bb_event(int kind,uint64_t gen,int64_t a,int64_t b)
{
    if(!__atomic_load_n(&g_bb_armed,__ATOMIC_ACQUIRE))return;
    if(pthread_mutex_trylock(&g_bb_lock)!=0){
        __atomic_add_fetch(&g_bb_dropped,1,__ATOMIC_RELAXED);
        return;
    }
    uint64_t seq=g_bb_head++;
    nova_bb_entry *e=&g_bb_ring[seq%NOVA_BB_RING_LEN];
    e->ms=nova_iso_uptime_ms();
    e->tid=nova_bb_tid();
    e->gen=gen;
    e->kind=kind;
    e->a=a;
    e->b=b;
    pthread_mutex_unlock(&g_bb_lock);
}
static void nova_bb_fault(int kind,uint64_t gen,int64_t a,int64_t b)
{
    nova_bb_event(kind,gen,a,b);
    int empty=0;
    if(__atomic_compare_exchange_n(&g_bb_first_fault,&empty,kind,0,
                                   __ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)){
        __atomic_store_n(&g_bb_freeze_pending,1,__ATOMIC_RELEASE);
        LOGE("NOVA_1073_BB_FIRST_ANOMALY kind=%d gen=%" PRIu64
             " amount=%" PRId64 " rc=%" PRId64 " tid=%d",
             kind,gen,a,b,nova_bb_tid());
    }
}
/* No other locks are acquired in a phase event, including from CURL callbacks.
 * The watcher can observe an open call that never returns. */
static void nova_bb_phase_start(int id,int64_t arg)
{
    if(id<0 || id>=NOVA_BB_PHASES ||
       !__atomic_load_n(&g_bb_armed,__ATOMIC_ACQUIRE))return;
    nova_bb_phase *p=&g_bb_phases[id];
    __atomic_store_n(&p->tid,nova_bb_tid(),__ATOMIC_RELAXED);
    __atomic_store_n(&p->arg,arg,__ATOMIC_RELAXED);
    int64_t now=nova_iso_uptime_ms();
    __atomic_store_n(&p->since_ms,now,__ATOMIC_RELEASE);
}
static void nova_bb_phase_finish(int id,int64_t arg)
{
    if(id<0 || id>=NOVA_BB_PHASES ||
       !__atomic_load_n(&g_bb_armed,__ATOMIC_ACQUIRE))return;
    nova_bb_phase *p=&g_bb_phases[id];
    int64_t began=__atomic_exchange_n(&p->since_ms,0,__ATOMIC_ACQ_REL);
    int64_t ms=nova_iso_uptime_ms()-began;
    if(began>0 && ms>=250)
        nova_bb_event(NOVA_BB_SLOW_PHASE,
              __atomic_load_n(&g_bb_gen,__ATOMIC_ACQUIRE),
              ((int64_t)id<<32)|(uint32_t)(ms>INT32_MAX?INT32_MAX:ms),arg);
}
static long nova_bb_proc_value(const char *path,const char *key)
{
    FILE *f=fopen(path,"r");
    if(!f)return -1;
    char line[256]; long value=-1;
    size_t n=strlen(key);
    while(fgets(line,sizeof(line),f)){
        if(strncmp(line,key,n)==0){
            if(sscanf(line+n,"%ld",&value)!=1)value=-1;
            break;
        }
    }
    fclose(f);
    return value;
}
static int nova_bb_fd_count(void)
{
    DIR *d=opendir("/proc/self/fd");
    if(!d)return -1;
    int count=0;
    struct dirent *ent;
    while((ent=readdir(d))!=NULL)
        if(ent->d_name[0]!='.')count++;
    closedir(d);
    return count>0?count-1:0; /* exclude the enumerator's own fd */
}
/* A *mapping-gap estimate*, not proof that Android malloc/mmap can use it.
 * Never reveal mapping addresses or private library/file paths in logs. */
static void nova_bb_map_gaps(int64_t *largest_kb,int *count)
{
    *largest_kb=-1;*count=-1;
    FILE *f=fopen("/proc/self/maps","r");
    if(!f)return;
    char line[768];
    unsigned long long prev=0,big=0;
    int n=0;
    while(fgets(line,sizeof(line),f)){
        unsigned long long start=0,end=0;
        if(sscanf(line,"%llx-%llx",&start,&end)!=2||end<start)
            continue;
        if(n>0 && start>prev && start-prev>big)
            big=start-prev;
        if(end>prev)prev=end;
        n++;
    }
    fclose(f);
    *largest_kb=(int64_t)(big/1024ULL);*count=n;
}
static void nova_bb_try_task_stack(int phase,int tid,int64_t age)
{
    if(tid<=0)return;
    char path[128], buf[320];
    snprintf(path,sizeof(path),"/proc/self/task/%d/wchan",tid);
    FILE *f=fopen(path,"r");
    if(f){
        if(!fgets(buf,sizeof(buf),f))snprintf(buf,sizeof(buf),"read_failed");
        fclose(f);
        size_t n=strlen(buf);
        while(n && (buf[n-1]=='\n'||buf[n-1]=='\r'))buf[--n]=0;
        LOGE("NOVA_1073_BB_THREAD_WCHAN phase=%d tid=%d ageMs=%" PRId64
             " wchan=%s",phase,tid,age,buf);
    }else{
        LOGE("NOVA_1073_BB_THREAD_WCHAN phase=%d tid=%d ageMs=%" PRId64
             " openErrno=%d",phase,tid,age,errno);
    }
    snprintf(path,sizeof(path),"/proc/self/task/%d/stack",tid);
    f=fopen(path,"r");
    if(f){
        int lines=0;
        while(lines<8 && fgets(buf,sizeof(buf),f)){
            size_t n=strlen(buf);
            while(n&&(buf[n-1]=='\n'||buf[n-1]=='\r'))buf[--n]=0;
            LOGE("NOVA_1073_BB_KERNEL_STACK phase=%d tid=%d %s",
                 phase,tid,buf);
            lines++;
        }
        fclose(f);
        LOGI("NOVA_1073_BB_STACK_NOTE kernel_stack_not_userspace_backtrace");
    }else{
        LOGE("NOVA_1073_BB_STACK_ACCESS phase=%d tid=%d errno=%d"
             " kernel_stack_unavailable=1",phase,tid,errno);
    }
    LOGI("NOVA_1073_BB_NATIVE_STACK_GUIDE pid=%d tid=%d"
         " adb_command='adb shell debuggerd -b %d'"
         " note=requires_debuggerd_permission_and_live_process",
         (int)getpid(),tid,(int)getpid());
}
static void nova_bb_freeze_history(int trigger)
{
    uint64_t count=0,head=0;
    pthread_mutex_lock(&g_bb_lock);
    head=g_bb_head;
    count=head<NOVA_BB_RING_LEN?head:NOVA_BB_RING_LEN;
    uint64_t first=head-count;
    for(uint64_t k=0;k<count;++k)
        g_bb_frozen[k]=g_bb_ring[(first+k)%NOVA_BB_RING_LEN];
    pthread_mutex_unlock(&g_bb_lock);
    int64_t cut=nova_iso_uptime_ms()-NOVA_BB_HISTORY_MS;
    int retained=0;
    for(uint64_t i=0;i<count;i++)
        if(g_bb_frozen[i].ms>=cut)retained++;
    LOGE("NOVA_1073_BB_FREEZE_BEGIN reason=%d entries=%d"
         " windowMs=%d dropped=%" PRIu64 " pid=%d",
         trigger,retained,NOVA_BB_HISTORY_MS,
         __atomic_load_n(&g_bb_dropped,__ATOMIC_RELAXED),(int)getpid());
    /* Print bounded structured evidence rather than exhausting logcat on
     * the failing device. The 120s ring remains resident and is not erased. */
    int printed=0, skipped=0;
    for(uint64_t i=0;i<count;i++){
        nova_bb_entry *e=&g_bb_frozen[i];
        if(e->ms<cut)continue;
        if(retained>1200 && (int)(retained-printed-skipped)>400 &&
           (int)(printed+skipped)%3!=0){
            skipped++;continue;
        }
        LOGE("NOVA_1073_BB_HISTORY tMs=%" PRId64 " gen=%" PRIu64
             " tid=%d event=%d a=%" PRId64 " b=%" PRId64,
             e->ms,e->gen,e->tid,e->kind,e->a,e->b);
        printed++;
    }
    LOGE("NOVA_1073_BB_FREEZE_END printed=%d reduced=%d"
         " retained=%d continues_recording=1",printed,skipped,retained);
}
static void *nova_bb_watchdog(void *unused)
{
    (void)unused;
    LOGI("NOVA_1073_BB_WATCHDOG_STARTED pid=%d periodMs=1000"
         " ring=%d windowMs=%d",(int)getpid(),NOVA_BB_RING_LEN,
         NOVA_BB_HISTORY_MS);
    while(1){
        struct timespec delay={.tv_sec=1,.tv_nsec=0};
        nanosleep(&delay,NULL);
        uint64_t gen=__atomic_load_n(&g_bb_gen,__ATOMIC_ACQUIRE);
        int64_t now=nova_iso_uptime_ms();
        long vm=nova_bb_proc_value("/proc/self/status","VmSize:");
        long peak=nova_bb_proc_value("/proc/self/status","VmPeak:");
        long rss=nova_bb_proc_value("/proc/self/status","VmRSS:");
        long data=nova_bb_proc_value("/proc/self/status","VmData:");
        long swap=nova_bb_proc_value("/proc/self/status","VmSwap:");
        long threads=nova_bb_proc_value("/proc/self/status","Threads:");
        long mem_avail=nova_bb_proc_value("/proc/meminfo","MemAvailable:");
        int64_t hole=-1;int maps=-1;
        nova_bb_map_gaps(&hole,&maps);
        int fds=nova_bb_fd_count();
        int64_t ages[NOVA_BB_PHASES];
        for(int i=0;i<NOVA_BB_PHASES;i++){
            int64_t since=__atomic_load_n(&g_bb_phases[i].since_ms,
                                          __ATOMIC_ACQUIRE);
            ages[i]=since>0 && now>=since?now-since:0;
        }
        LOGI("NOVA_1073_BB_RESOURCE ms=%" PRId64 " gen=%" PRIu64
             " mode=%d vmKB=%ld peakKB=%ld rssKB=%ld dataKB=%ld"
             " swapKB=%ld memAvailKB=%ld threads=%ld fd=%d"
             " maps=%d largestGapKB=%" PRId64
             " bdAge=%" PRId64 " curlAge=%" PRId64
             " pollAge=%" PRId64 " rawAge=%" PRId64
             " demuxAge=%" PRId64 " closeAge=%" PRId64
             " firstFault=%d",
             now,gen,__atomic_load_n(&g_bb_mode,__ATOMIC_ACQUIRE),
             vm,peak,rss,data,swap,mem_avail,threads,fds,maps,hole,
             ages[0],ages[1],ages[2],ages[3],ages[4],ages[5],
             __atomic_load_n(&g_bb_first_fault,__ATOMIC_ACQUIRE));
        nova_bb_event(NOVA_BB_WAREHOUSE,gen,
                      ((int64_t)(rss<0?0:rss)<<32)|(uint32_t)(fds<0?0:fds),
                      ((int64_t)(threads<0?0:threads)<<32)|
                       (uint32_t)(vm<0?0:vm));
        for(int i=0;i<NOVA_BB_PHASES;i++){
            nova_bb_phase *p=&g_bb_phases[i];
            int64_t last=__atomic_load_n(&p->last_dump_ms,__ATOMIC_RELAXED);
            if(ages[i]<NOVA_BB_STUCK_MS ||
               (last>0 && now-last<30000))continue;
            __atomic_store_n(&p->last_dump_ms,now,__ATOMIC_RELAXED);
            int tid=__atomic_load_n(&p->tid,__ATOMIC_ACQUIRE);
            int64_t arg=__atomic_load_n(&p->arg,__ATOMIC_RELAXED);
            LOGE("NOVA_1073_BB_PHASE_STUCK phase=%d tid=%d ageMs=%" PRId64
                 " arg=%" PRId64 " gen=%" PRIu64,
                 i,tid,ages[i],arg,gen);
            nova_bb_fault(NOVA_BB_SLOW_PHASE,gen,i,ages[i]);
            nova_bb_try_task_stack(i,tid,ages[i]);
        }
        int pending=__atomic_exchange_n(&g_bb_freeze_pending,0,
                                         __ATOMIC_ACQ_REL);
        if(pending)
            nova_bb_freeze_history(
                __atomic_load_n(&g_bb_first_fault,__ATOMIC_ACQUIRE));
    }
    return NULL;
}
static void nova_bb_start_thread(void)
{
    pthread_t watcher;
    int rc=pthread_create(&watcher,NULL,nova_bb_watchdog,NULL);
    if(!rc){
        pthread_detach(watcher); /* process-lifetime; no session pointers */
        __atomic_store_n(&g_bb_watch_started,1,__ATOMIC_RELEASE);
    }else
        LOGE("NOVA_1073_BB_WATCHDOG_START_FAIL rc=%d",rc);
}
static void nova_bb_arm(int mode)
{
    __atomic_store_n(&g_bb_armed,1,__ATOMIC_RELEASE);
    __atomic_store_n(&g_bb_mode,mode,__ATOMIC_RELEASE);
    pthread_once(&g_bb_watch_once,nova_bb_start_thread);
    nova_bb_event(NOVA_BB_OPEN,0,mode,0);
}
/* AVOS calls this through dlsym only on the current DirectTransport.
 * Kind 10/11 RAW; 20/21 CBE fail/success; 30 FFmpeg ENOMEM;
 * 40/41 av_read_frame begin/end. Never carries URLs or secrets. */
__attribute__((visibility("default")))
void nova_transport_diag_external(int kind,int64_t amount,int rc)
{
    if(!__atomic_load_n(&g_bb_armed,__ATOMIC_ACQUIRE))return;
    uint64_t gen=__atomic_load_n(&g_bb_gen,__ATOMIC_ACQUIRE);
    switch(kind){
    case 10:
        nova_bb_phase_start(NOVA_BB_RAW,amount);
        break;
    case 11:
        nova_bb_phase_finish(NOVA_BB_RAW,rc);
        break;
    case 20:
        nova_bb_fault(NOVA_BB_CBE_FAIL,gen,amount,rc);
        break;
    case 21:
        nova_bb_event(NOVA_BB_CBE_OK,gen,amount,rc);
        break;
    case 30:
        nova_bb_fault(NOVA_BB_FFMPEG_ENOMEM,gen,amount,rc);
        break;
    case 40:
        nova_bb_phase_start(NOVA_BB_DEMUX,amount);
        break;
    case 41:
        nova_bb_phase_finish(NOVA_BB_DEMUX,rc);
        break;
    default:break;
    }
}
