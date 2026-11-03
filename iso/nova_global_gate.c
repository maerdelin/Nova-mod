/* NOVA_GLOBAL_LOGS_TOGGLE_V2: persistent shared in-app diagnostic authority.
 * The fast path is a single mapped byte read, including the OFF state.
 * A failed early map is retried at most once per second on a caller thread;
 * there is no permanent polling worker or I/O after a successful map.
 * A missing/unreadable file always fails closed, never overriding user OFF.
 */
#ifndef NOVA_GLOBAL_LOG_IMPL
#define NOVA_GLOBAL_LOG_IMPL
#include <sys/types.h>
#include <sys/mman.h>
#include <fcntl.h>
#include <unistd.h>
#include <pthread.h>
#include <stdio.h>
#include <stdint.h>
#include <time.h>

static volatile unsigned char *nova_logs_shared_byte = NULL;
static pthread_mutex_t nova_logs_mapping_mutex = PTHREAD_MUTEX_INITIALIZER;
static unsigned long long nova_logs_retry_after_ms = 0;

/* Must be called with nova_logs_mapping_mutex held. */
static void nova_logs_mapping_init(void) {
    char path[192];
    unsigned user_id = (unsigned)getuid()/100000u;
    int n=snprintf(path,sizeof(path),
        "/data/user/%u/org.courville.nova/files/nova_logs_enabled.bin",
        user_id);
    if(n<=0 || (size_t)n>=sizeof(path))return;
    int fd=open(path,O_RDONLY|O_CLOEXEC);
    if(fd<0)return;
    void *p=mmap(NULL,4096,PROT_READ,MAP_SHARED,fd,0);
    close(fd);
    if(p==MAP_FAILED)return;
    __atomic_store_n(&nova_logs_shared_byte,
        (volatile unsigned char *)p,__ATOMIC_RELEASE);
}

__attribute__((visibility("default")))
int nova_global_log_enabled(void) {
    volatile unsigned char *p=__atomic_load_n(&nova_logs_shared_byte,
                                               __ATOMIC_ACQUIRE);
    if(!p) {
        struct timespec now;
        if(clock_gettime(CLOCK_MONOTONIC,&now)==0) {
            unsigned long long ms=(unsigned long long)now.tv_sec*1000ull+
                                  (unsigned long long)now.tv_nsec/1000000ull;
            if(pthread_mutex_trylock(&nova_logs_mapping_mutex)==0) {
                p=__atomic_load_n(&nova_logs_shared_byte,__ATOMIC_ACQUIRE);
                if(!p && ms>=nova_logs_retry_after_ms) {
                    nova_logs_retry_after_ms=ms+1000ull;
                    nova_logs_mapping_init();
                }
                pthread_mutex_unlock(&nova_logs_mapping_mutex);
            }
        }
        p=__atomic_load_n(&nova_logs_shared_byte,__ATOMIC_ACQUIRE);
    }
    if(!p)return 0;
    return __atomic_load_n(p,__ATOMIC_ACQUIRE)!=0;
}
#endif
