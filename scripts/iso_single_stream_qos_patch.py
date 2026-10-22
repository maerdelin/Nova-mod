#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


ISO_HELPERS = r'''
static long nova_iso_cpu_max_freq_khz(int cpu) {
    char path[160];
    snprintf(path, sizeof(path),
             "/sys/devices/system/cpu/cpu%d/cpufreq/cpuinfo_max_freq", cpu);
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    long khz = 0;
    if (fscanf(f, "%ld", &khz) != 1) khz = 0;
    fclose(f);
    return khz;
}

static void nova_iso_boost_thread(const char *role, int requested_nice) {
    cpu_set_t allowed, fast;
    CPU_ZERO(&allowed);
    CPU_ZERO(&fast);
    int fast0 = -1, fast1 = -1;
    long score0 = -1, score1 = -1;
    int get_aff_rc = sched_getaffinity(0, sizeof(allowed), &allowed);
    if (get_aff_rc == 0) {
        for (int cpu = 0; cpu < CPU_SETSIZE; cpu++) {
            if (!CPU_ISSET(cpu, &allowed)) continue;
            long score = nova_iso_cpu_max_freq_khz(cpu);
            if (score <= 0) score = cpu + 1;
            if (score > score0 || (score == score0 && cpu > fast0)) {
                score1 = score0; fast1 = fast0;
                score0 = score; fast0 = cpu;
            } else if (score > score1 || (score == score1 && cpu > fast1)) {
                score1 = score; fast1 = cpu;
            }
        }
        if (fast0 >= 0) CPU_SET(fast0, &fast);
        if (fast1 >= 0) CPU_SET(fast1, &fast);
    }

    int affinity_rc = -1, affinity_errno = 0;
    if (get_aff_rc == 0 && fast0 >= 0) {
        errno = 0;
        affinity_rc = sched_setaffinity(0, sizeof(fast), &fast);
        affinity_errno = affinity_rc ? errno : 0;
    }

    errno = 0;
    int nice_rc = setpriority(PRIO_PROCESS, 0, requested_nice);
    int nice_errno = nice_rc ? errno : 0;
    errno = 0;
    int actual_nice = getpriority(PRIO_PROCESS, 0);
    int get_nice_errno = errno;
    LOGI("IO_SCHED role=%s requestedNice=%d niceRc=%d niceErr=%d actualNice=%d getNiceErr=%d fastCpu0=%d fastCpu1=%d affinityRc=%d affinityErr=%d",
         role, requested_nice, nice_rc, nice_errno, actual_nice,
         get_nice_errno, fast0, fast1, affinity_rc, affinity_errno);
}'''


def apply(path: Path, report: Path | None = None) -> dict:
    text = path.read_text()
    if "NOVA_ISO_SINGLE_STREAM" in text:
        raise RuntimeError("ISO single-stream QoS patch already applied")

    text = once(
        text,
        "#include <sys/types.h>\n",
        "#include <sys/types.h>\n#include <sched.h>\n#include <sys/resource.h>\n",
        "ISO scheduling includes",
    )
    text = once(
        text,
        "    if (fd < 0) return -1;\n    struct sockaddr_in sa;",
        "    if (fd < 0) return -1;\n"
        "    int nova_sockbuf = 4 * 1024 * 1024;\n"
        "    setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &nova_sockbuf, sizeof(nova_sockbuf));\n"
        "    setsockopt(fd, SOL_SOCKET, SO_SNDBUF, &nova_sockbuf, sizeof(nova_sockbuf));\n"
        "    struct sockaddr_in sa;",
        "ISO loopback socket buffers",
    )
    text = once(
        text,
        "static int64_t mono_ms(void) {",
        ISO_HELPERS + "\nstatic int64_t mono_ms(void) {",
        "ISO scheduling helper",
    )
    text = once(
        text,
        "static void *client_main(void *opaque) {\n    client_task *task = (client_task *)opaque;",
        "static void *client_main(void *opaque) {\n"
        "    nova_iso_boost_thread(\"iso-title\", -8);\n"
        "    client_task *task = (client_task *)opaque;",
        "single continuous title stream scheduling",
    )
    text = once(
        text,
        "static void *server_main(void *opaque) {\n    iso_session *s = (iso_session *)opaque;",
        "static void *server_main(void *opaque) {\n"
        "    nova_iso_boost_thread(\"iso-server\", -4);\n"
        "    iso_session *s = (iso_session *)opaque;",
        "ISO accept thread scheduling",
    )
    text = once(
        text,
        "    s->input.playback_mode = 1;\n    LOGI(\"CACHE_MODE playback persistent_range=1 window=%d slots=%d\", CACHE_BYTES, CACHE_SLOTS);",
        "    for (int i = 0; i < CACHE_SLOTS; i++) {\n"
        "        if (!s->input.cache[i].data) {\n"
        "            s->input.cache[i].data = malloc(CACHE_BYTES);\n"
        "            if (!s->input.cache[i].data) {\n"
        "                LOGE(\"CACHE_PREALLOC_FAIL slot=%d\", i);\n"
        "                session_destroy(s);\n"
        "                return NULL;\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "    s->input.playback_mode = 1;\n"
        "    LOGI(\"NOVA_ISO_SINGLE_STREAM parallelRange=0 persistentRange=1 cachePrealloc=1 cacheBytes=%d slots=%d\", CACHE_BYTES, CACHE_SLOTS);\n"
        "    LOGI(\"CACHE_MODE playback persistent_range=1 window=%d slots=%d\", CACHE_BYTES, CACHE_SLOTS);",
        "preallocate retained ISO cache without parallel prefetch",
    )

    forbidden = (
        "PRE" + "FETCH_WORKERS",
        "iso_prefetch_" + "worker",
        "prefetch_" + "threads",
        "prefetch_" + "generation",
        "parallel_" + "range=1",
        "PREFETCH_" + "BEGIN worker=",
        "PREFETCH_" + "READY worker=",
        "PREFETCH_" + "DISCARD worker=",
    )
    present = [x for x in forbidden if x in text]
    if present:
        raise RuntimeError("parallel Range residue remains: " + repr(present))

    required = (
        'nova_iso_boost_thread("iso-title", -8)',
        'nova_iso_boost_thread("iso-server", -4)',
        "NOVA_ISO_SINGLE_STREAM",
        "parallelRange=0",
        "persistentRange=1",
        "CACHE_PREALLOC_FAIL",
        "sched_setaffinity",
        "cpuinfo_max_freq",
    )
    missing = [x for x in required if x not in text]
    if missing:
        raise RuntimeError("ISO single-stream postcondition missing: " + repr(missing))

    path.write_text(text)
    result = {
        "status": "PASS",
        "parallel_range_workers": 0,
        "single_persistent_upstream": True,
        "cache_bytes_existing_ceiling": 8 * 4 * 1024 * 1024,
        "cache_preallocated_before_playback": True,
        "title_thread_nice_requested": -8,
        "server_thread_nice_requested": -4,
        "cpu_policy": "two highest-frequency allowed CPUs",
        "loopback_socket_buffer_bytes_requested": 4 * 1024 * 1024,
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("iso_source", type=Path)
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    print(json.dumps(apply(a.iso_source, a.report), indent=2))


if __name__ == "__main__":
    main()
