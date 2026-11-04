#!/usr/bin/env python3
"""NOVA 1197: stop OFF diagnostic *collection*, not merely logcat output.

Run AFTER global_logs_native_patch.py and global_logs_native_coverage_patch.py.
Patch only source-anchored diagnostics-owned counters and timestamps in the
transport and LiteRange modules. Do not gate caching, networking, scheduling,
Seek, playback progress, or frame-render liveness.
"""
from __future__ import annotations
import argparse
from pathlib import Path


MARK = "NOVA_1197_OFF_DIAGNOSTIC_SAMPLING"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected 1 exact source anchor, found {n}")
    return text.replace(old, new, 1)


def patch_transport(text: str) -> str:
    changes = (
        ("++s->iso_meta_reads;",
         "if(nova_global_log_enabled()) ++s->iso_meta_reads;",
         "ISO metadata reads: diagnostics only"),
        ("++s->iso_meta_hits;",
         "if(nova_global_log_enabled()) ++s->iso_meta_hits;",
         "ISO metadata cache-hit counter: diagnostics only"),
        ("++s->iso_meta_misses;",
         "if(nova_global_log_enabled()) ++s->iso_meta_misses;",
         "ISO metadata cache-miss counter: diagnostics only"),
        ("s->iso_meta_fetched += (uint64_t)got;",
         "if(nova_global_log_enabled()) s->iso_meta_fetched += (uint64_t)got;",
         "ISO metadata fetched-byte counter: diagnostics only"),
        ("if (page_bytes > s->iso_meta_peak_window)\n"
         "                s->iso_meta_peak_window = page_bytes;",
         "if (nova_global_log_enabled() && page_bytes > s->iso_meta_peak_window)\n"
         "                s->iso_meta_peak_window = page_bytes;",
         "ISO peak-window counter: diagnostics only; preserve real cache window"),
        ("int64_t fetch_start_ms=nova_iso_uptime_ms();",
         "int64_t fetch_start_ms=nova_global_log_enabled()?nova_iso_uptime_ms():0;",
         "ISO metadata fetch diagnostic timestamp"),
        ("int64_t fetch_seek_ms=nova_iso_uptime_ms()-fetch_start_ms;",
         "int64_t fetch_seek_ms=fetch_start_ms && nova_global_log_enabled()?"
         "nova_iso_uptime_ms()-fetch_start_ms:0;",
         "ISO metadata seek diagnostic duration"),
        ("int64_t scan_start_ms = nova_iso_uptime_ms();",
         "int64_t scan_start_ms = nova_global_log_enabled()?nova_iso_uptime_ms():0;",
         "ISO title scan diagnostic timestamp"),
        ("int64_t select_start_ms = nova_iso_uptime_ms();",
         "int64_t select_start_ms = nova_global_log_enabled()?nova_iso_uptime_ms():0;",
         "ISO title selection diagnostic timestamp"),
        ("int64_t iso_start_ms = iso ? nova_iso_uptime_ms() : 0;",
         "int64_t iso_start_ms = (iso && nova_global_log_enabled()) ? nova_iso_uptime_ms() : 0;",
         "ISO overall diagnostic timestamp"),
    )
    for old, new, label in changes:
        text = replace_once(text, old, new, label)
    stage = "stage_start_ms = nova_iso_uptime_ms();"
    if text.count(stage) != 2:
        raise RuntimeError("ISO stage diagnostic timestamps: expected 2 sites")
    text = text.replace(stage, "stage_start_ms = nova_global_log_enabled()?nova_iso_uptime_ms():0;")
    # These are BUSINESS operations, never disable them.
    for anchor in (
        "entry->touched = ++s->iso_meta_tick;",
        "read_exact(s->upstream, staging, request)",
        "s->iso_meta_window_bytes*=2;",
        "if (select_main_title(s) < 0)",
        "__atomic_add_fetch(&s->startup_wire_bytes",
    ):
        if anchor not in text:
            raise RuntimeError("ISO business invariant missing: " + anchor)
    return text


def patch_literange(text: str) -> str:
    changes = (
        ("p->owner->received_sample_bytes+=(uint64_t)bytes;",
         "if(nova_global_log_enabled()) p->owner->received_sample_bytes+=(uint64_t)bytes;",
         "LiteRange diagnostic wire-byte counter"),
        ("e->committed_sample_bytes+=(uint64_t)take;",
         "if(nova_global_log_enabled()) e->committed_sample_bytes+=(uint64_t)take;",
         "LiteRange diagnostic delivered-byte counter"),
        ("if(waited_ms>=NOVA_LITE_WAIT_TRIGGER_MS){\n"
         "        if(e->starvation_count<1000)e->starvation_count++;\n"
         "    }",
         "if(nova_global_log_enabled() && waited_ms>=NOVA_LITE_WAIT_TRIGGER_MS){\n"
         "        if(e->starvation_count<1000)e->starvation_count++;\n"
         "    }",
         "LiteRange diagnostic-only starvation counter"),
        ("uint64_t delivered=e->committed_sample_bytes*1000ULL/\n"
         "                       (uint64_t)(now-e->last_sample_ms);\n"
         "    uint64_t received=e->received_sample_bytes*1000ULL/\n"
         "                      (uint64_t)(now-e->last_sample_ms);",
         "uint64_t delivered=0, received=0;\n"
         "    if(nova_global_log_enabled()){\n"
         "        delivered=e->committed_sample_bytes*1000ULL/\n"
         "                  (uint64_t)(now-e->last_sample_ms);\n"
         "        received=e->received_sample_bytes*1000ULL/\n"
         "                 (uint64_t)(now-e->last_sample_ms);\n"
         "    }",
         "LiteRange diagnostic-only Bps sampling"),
    )
    for old, new, label in changes:
        text = replace_once(text, old, new, label)
    # Keep the entire existing scheduler path and real media-byte progress.
    for anchor in (
        "nova_lite_telemetry(s,waited>INT32_MAX?INT32_MAX:(int)waited);",
        "if(target>0 && s->multi_active_lanes<2",
        "s->multi_active_lanes=2;",
        "nova_lite_schedule(s);",
        "s->multi_committed_cursor+=take;",
        "__atomic_add_fetch(&p->owner->session->startup_wire_bytes",
        "e->last_sample_ms=now;",
    ):
        if anchor not in text:
            raise RuntimeError("LiteRange business invariant missing: " + anchor)
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--lite", type=Path, required=True)
    args = parser.parse_args()
    t = args.transport.read_text()
    l = args.lite.read_text()
    if "#define LOGI(...) do { if(nova_global_log_enabled())" not in t:
        raise RuntimeError("Apply 1196 native log output guard BEFORE 1197 sampling patch")
    if "    if(nova_global_log_enabled()){\n    /* NOVA_60FPS_W2_IO_CPU_V1:" not in l:
        raise RuntimeError("Apply 1196 CPU/I/O sampling guard BEFORE 1197")
    t2 = patch_transport(t)
    l2 = patch_literange(l)
    args.transport.write_text(t2)
    args.lite.write_text(l2)
    print(MARK + "=PASS ISO diagnostics and LiteRange diagnostic counters/timers gated; business paths preserved")


if __name__ == "__main__":
    main()
