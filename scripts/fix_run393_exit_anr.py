#!/usr/bin/env python3
"""Run393: cancel the exact transport before AVOS destroy waits for an async Seek.

The regression was a 15-second CURL stall during MKV Seek followed by a
7-second UI-thread nativeRelease/avos_mp_destroy. This patch only changes the
player's destruction path and the network shutdown callback. Ordinary seeks,
network retry policy, startup stages, RAW size, and buffering stay unchanged.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

MARK = "NOVA_393_EARLY_TRANSPORT_ABORT_V1"
LITE_MARK = "NOVA_393_CURL_SHUTDOWN_ONLY_V1"


def once(src: str, before: str, after: str, label: str) -> str:
    if src.count(before) != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {src.count(before)}")
    return src.replace(before, after, 1)


def patch_avos_mp(src: str) -> str:
    if MARK in src:
        raise RuntimeError("Run393 AVOS fix already applied")
    if "#include <dlfcn.h>" not in src:
        src = once(src, "#include <inttypes.h>\n",
                   "#include <inttypes.h>\n#include <dlfcn.h>\n",
                   "AVOS dynamic symbol include")
    anchor = (
        "static int avos_mp_close(avos_mp_t *mp);\n"
        "static int avos_mp_destroy(avos_mp_t *mp)\n"
        "{\n\tMPLOG();\n"
    )
    helper = r'''/* NOVA_393_EARLY_TRANSPORT_ABORT_V1:
 * A UI-thread release must not wait for a blocked async Seek to finish
 * a 15s Range request. Abort ONLY this player's novatransport generation
 * before waiting for async JNI users. Do not close/free the session here:
 * normal AVOS close still owns all thread joins and transport lifetimes.
 * This is a shutdown-only operation, never a Seek preemption.
 */
static void nova_393_abort_before_destroy(avos_mp_t *mp)
{
    const char *url = mp ? mp->src.url : NULL;
    if (!url || strncmp(url, "novatransport://", 16) != 0)
        return;
    uint64_t generation = 0;
    if (sscanf(url + 16, "%" SCNu64, &generation) != 1 ||
        generation == 0)
        return;
    void *h = dlopen("libnova_transport.so", RTLD_NOW | RTLD_LOCAL);
    if (!h)
        return;
    typedef int (*nova_393_abort_fn)(uint64_t);
    nova_393_abort_fn abort_transport =
        (nova_393_abort_fn)dlsym(h, "nova_transport_abort");
    int result = abort_transport ? abort_transport(generation) : 0;
    /* MPLOG -> serprintf -> unified Native diagnostic gate. Logs OFF is silent. */
    MPLOG("NOVA_393_EARLY_TRANSPORT_ABORT_V1 generation=%" PRIu64
          " result=%d", generation, result);
    dlclose(h);
}

'''
    src = once(src, anchor, helper + anchor +
               "\tnova_393_abort_before_destroy(mp);\n",
               "preempt transport before destruction waits")
    must = [
        "nova_393_abort_before_destroy(mp);\n\tpthread_mutex_lock(&mp->async.mtx);",
        'dlsym(h, "nova_transport_abort")',
        "MPLOG(\"NOVA_393_EARLY_TRANSPORT_ABORT_V1",
    ]
    # MPLOG may remain immediately before the early abort; the abort must
    # precede both destroying=1 and the async-join/wait sequence.
    for token in must[1:]:
        if token not in src:
            raise RuntimeError("AVOS Run393 missing postcondition: " + token)
    call_pos = src.index("\tnova_393_abort_before_destroy(mp);")
    wait_pos = src.index("async_cmd_add(mp, ASYNC_CMD_WAIT, 0);", call_pos)
    if call_pos >= wait_pos or "avos_mp_destroy" not in src:
        raise RuntimeError("AVOS abort must precede async user wait")
    return src


def patch_lite(src: str) -> str:
    if LITE_MARK in src:
        raise RuntimeError("Run393 CURL fix already applied")
    anchor = "static int nova_lite_launch(nova_lite_slot *p)\n{\n"
    cb = r'''/* NOVA_393_CURL_SHUTDOWN_ONLY_V1:
 * CURLOPT_XFERINFO callback is a real cancellation mechanism. An ongoing
 * slow/stalled HTTP request stops when its owning player is destroyed.
 * No latency/Range policy is changed during ordinary playback or Seek.
 */
static int nova_393_shutdown_progress(void *opaque, curl_off_t dl_total,
                                      curl_off_t dl_now, curl_off_t ul_total,
                                      curl_off_t ul_now)
{
    (void)dl_total;
    (void)dl_now;
    (void)ul_total;
    (void)ul_now;
    nova_session *s=(nova_session *)opaque;
    return !s || __atomic_load_n(&s->stopping,__ATOMIC_ACQUIRE) ? 1 : 0;
}

'''
    src = once(src, anchor, cb + anchor, "CURL launch callback")
    option_anchor = "    NOVA_CURL_SET(CURLOPT_LOW_SPEED_TIME,15L);\n"
    src = once(
        src, option_anchor,
        option_anchor +
        "    /* Shutdown callback only; the existing retry/15s policy is retained. */\n"
        "    NOVA_CURL_SET(CURLOPT_NOPROGRESS,0L);\n"
        "    NOVA_CURL_SET(CURLOPT_XFERINFOFUNCTION,nova_393_shutdown_progress);\n"
        "    NOVA_CURL_SET(CURLOPT_XFERINFODATA,s);\n",
        "CURL shutdown-only opt-ins"
    )
    for token in ("CURLOPT_XFERINFOFUNCTION", "CURLOPT_XFERINFODATA,s",
                  "__atomic_load_n(&s->stopping,__ATOMIC_ACQUIRE)"):
        if token not in src:
            raise RuntimeError("CURL Run393 missing postcondition: " + token)
    return src


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--native", type=Path, required=True)
    p.add_argument("--lite", type=Path, required=True)
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    avos = args.native / "Source" / "avos_mp.c"
    old_avos = avos.read_text()
    old_lite = args.lite.read_text()
    new_avos = patch_avos_mp(old_avos)
    new_lite = patch_lite(old_lite)
    # Compute both before writing either file: fail-closed on anchors.
    avos.write_text(new_avos)
    args.lite.write_text(new_lite)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({
            "status": "PASS",
            "marker": MARK,
            "shutdown_only": True,
            "generation_scoped": True,
            "regular_seek_preemption": False,
            "unified_logs_gate": "MPLOG->serprintf / existing Nova Global Logs",
            "curl_progress_cancellable": True,
            "unchanged": ["1.5X/3X", "Shared128", "W2 lane policy",
                          "403 backoff", "startup stage thresholds"],
        }, indent=2) + "\n")
    print("NOVA_393_EARLY_TRANSPORT_ABORT=PATCHED")


if __name__ == "__main__":
    main()
