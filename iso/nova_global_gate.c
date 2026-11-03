/* NOVA_GLOBAL_LOGS_TOGGLE_V1: shared, persistent on-device logs authority.
 * Java writes the same MAP_SHARED byte. The only idle diagnostic overhead is
 * one atomic byte read; no polling, property checks, or background workers.
 * One-time mmap initialization is process-local and never touches media data.
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

/* Initialized before normal app startup in CustomApplication.attachBaseContext.
 * A missing/unreadable gate fails CLOSED rather than overriding user OFF. */
static volatile unsigned char *nova_logs_shared_byte = NULL;
static pthread_once_t nova_logs_mapping_once = PTHREAD_ONCE_INIT;
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
    pthread_once(&nova_logs_mapping_once,nova_logs_mapping_init);
    volatile unsigned char *p=__atomic_load_n(&nova_logs_shared_byte,
                                               __ATOMIC_ACQUIRE);
    if(!p)return 0;
    return __atomic_load_n(p,__ATOMIC_ACQUIRE)!=0;
}
#endif
