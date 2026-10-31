#!/usr/bin/env python3
"""Compile and exercise the REAL Shared42 pressure gate extracted from source.

The test includes the actual function body (not a Python reimplementation),
then asserts W2 head remains runnable while speculative lane is throttled
only at high RAW page ownership. Also preserves the normal fast W2 path.
"""
import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
INC = (ROOT / "iso" / "nova_literange4.inc").read_text()


def extract(name):
    m = re.search(r"static int " + re.escape(name) + r"\([^;]+?\)\s*\{", INC, re.S)
    if not m:
        raise AssertionError(f"Missing production function {name}")
    level = 1
    i = m.end()
    while level:
        if i >= len(INC):
            raise AssertionError("Unclosed native function")
        if INC[i] == "{":
            level += 1
        if INC[i] == "}":
            level -= 1
        i += 1
    return INC[m.start():i]


class RealNativePressureGate(unittest.TestCase):
    def test_production_c_gate_under_actual_page_ownership(self):
        gate = extract("nova_lite_can_stage")
        self.assertIn("NOVA_W2_RAW_PRESSURE_GUARD_V1", INC)
        self.assertIn("NOVA_WH_RAW_PAGES", gate)
        self.assertIn("p->start>e->session->multi_committed_cursor", gate)
        self.assertIn("limit>(int)NOVA_W2_FUTURE_SOFT_PAGES", gate)
        source = r"""
#include <stdint.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#define LOGI(...) ((void)0)
#define NOVA_WH_PAGE_BYTES (64u * 1024u)
#define NOVA_WH_TOTAL_BYTES (128u * 1024u * 1024u)
#define NOVA_WH_STAGE_BYTES (42u * 1024u * 1024u)
#define NOVA_WH_RAW_BYTES (86u * 1024u * 1024u)
#define NOVA_WH_HEAD_BYTES (6u * 1024u * 1024u)
#define NOVA_WH_FUTURE_BYTES (36u * 1024u * 1024u)
#define NOVA_WH_PAGES (NOVA_WH_TOTAL_BYTES/NOVA_WH_PAGE_BYTES)
#define NOVA_WH_STAGE_PAGES (NOVA_WH_STAGE_BYTES/NOVA_WH_PAGE_BYTES)
#define NOVA_WH_HEAD_PAGES (NOVA_WH_HEAD_BYTES/NOVA_WH_PAGE_BYTES)
#define NOVA_WH_FUTURE_PAGES (NOVA_WH_FUTURE_BYTES/NOVA_WH_PAGE_BYTES)
#define NOVA_WH_RAW_PAGES (NOVA_WH_RAW_BYTES/NOVA_WH_PAGE_BYTES)
#define NOVA_LITE_SLOTS 2
#define NOVA_W2_RAW_HIGH_PAGES ((NOVA_WH_RAW_PAGES*4)/5)
#define NOVA_W2_FUTURE_SOFT_PAGES (8u*1024u*1024u/NOVA_WH_PAGE_BYTES)
static int64_t nova_iso_uptime_ms(void) { return 987654321; }
typedef struct nova_shared_warehouse {
    pthread_mutex_t lock;
    int free_count;
} nova_shared_warehouse;
typedef struct nova_session {
    nova_shared_warehouse *warehouse;
    int64_t multi_committed_cursor;
} nova_session;
struct nova_lite_state;
typedef struct nova_lite_slot {
    struct nova_lite_state *owner;
    int64_t start;
    int page_count;
} nova_lite_slot;
typedef struct nova_lite_state {
    nova_session *session;
    nova_lite_slot slots[NOVA_LITE_SLOTS];
    int64_t last_raw_pressure_log_ms;
} nova_lite_state;
static int nova_lite_staged_pages(nova_lite_state *e) {
    return e->slots[0].page_count+e->slots[1].page_count;
}
""" + gate + r"""
static int check(nova_lite_state *e, int raw, int head, int future, int extra,
                 int use_future) {
    e->slots[0].page_count=head;
    e->slots[1].page_count=future;
    e->session->warehouse->free_count=NOVA_WH_PAGES-raw-head-future;
    nova_lite_slot *p=use_future?&e->slots[1]:&e->slots[0];
    if(e->session->warehouse->free_count<0) return -3;
    return nova_lite_can_stage(p,extra);
}
int main(void){
    nova_shared_warehouse w={0};
    if(pthread_mutex_init(&w.lock,NULL))return 20;
    nova_session s={.warehouse=&w,.multi_committed_cursor=0};
    nova_lite_state e={.session=&s};
    e.slots[0].owner=&e; e.slots[0].start=0;
    e.slots[1].owner=&e; e.slots[1].start=4096;
    /* Low RAW: W2 keeps its original 36 MiB future window. */
    if(check(&e,400,12,250,1,1)!=1)return 1;
    /* RAW >=80%: future lane may fill exactly 8 MiB. */
    if(check(&e,1101,12,127,1,1)!=1)return 2;
    if(check(&e,1101,12,128,1,1)!=0)return 3;
    /* HEAD 6 MiB guarantee is retained even under RAW pressure. */
    if(check(&e,1101,95,128,1,0)!=1)return 4;
    if(check(&e,1101,96,128,1,0)!=0)return 5;
    /* Once RAW falls below threshold, future can resume past 8 MiB. */
    if(check(&e,1000,12,128,1,1)!=1)return 6;
    /* Exact 128 MiB ownership limit must not be exceeded. */
    if(check(&e,1376,0,672,1,1)!=0)return 7;
    pthread_mutex_destroy(&w.lock);
    puts("NOVA_60FPS_W2_RAW_PRESSURE_NATIVE_PASS");
    return 0;
}
"""
        with tempfile.TemporaryDirectory() as work:
            src = pathlib.Path(work)/"gate.c"
            exe = pathlib.Path(work)/"gate"
            src.write_text(source)
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra",
                            "-Werror", "-pthread", str(src), "-o", str(exe)],
                           check=True, capture_output=True, text=True)
            check = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
            self.assertIn("NOVA_60FPS_W2_RAW_PRESSURE_NATIVE_PASS", check.stdout)

    def test_second_lane_still_enabled_and_seek_guards_intact(self):
        self.assertIn("s->multi_active_lanes=2;", INC)
        self.assertIn("NOVA_LITERANGE4_PAIR_ENABLE", INC)
        self.assertIn("nova_lite_schedule(s);", INC)
        self.assertIn("NOVA_MULTI_SEEK_GUARD", INC)
        self.assertIn("#define NOVA_LITE_SLOTS 2", INC)
        self.assertIn("curl_multi_perform(e->multi,&running)", INC)


if __name__=="__main__":
    unittest.main()
