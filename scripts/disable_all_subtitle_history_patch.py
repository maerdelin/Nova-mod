#!/usr/bin/env python3
"""RUN649+ clean subtitle baseline: disable ALL historical subtitle caching.

PGS, DVD/VobSub, text/ASS and every other internal subtitle type:
  * no history packet is stored or rescanned;
  * switching only flushes active subtitle queue and waits for NEW packets;
  * currently selected subtitle packets still enter sq as before;
  * audio/video demux, all RAW128/Seek and other playback logic untouched.
The empty sub_cache object is retained solely for existing logging and cleanup.
This patch runs AFTER the prior PGS-only bypass patch.
"""
import argparse
import json
from pathlib import Path

START = "// Subtitle history must not fill the A/V queue budget or force a media seek."
STOP = "extern int stream_drive_wake_sleep;"
PGS_START = "\t\t/* NOVA_PGS_HISTORY_BYPASS_AB_V1: one-variable A/B experiment.\n"
SELECTED = "\t\tif (s->subtitle->valid && !s->subtitle->ext && stream == s->subtitle->stream) {\n"
CHECKER = r"""/* NOVA_SUB_HISTORY_DISABLED_ALL_V1: historical replay has no producer.
 * The empty sub_cache queue remains initialized for old diagnostic counters.
 * Live selected-track decoding is unaffected.
 */
static SUB_PROPERTIES *_subtitle_props_for_stream(STREAM *s, int stream)
{
    for (int i = 0; i < ff_p->av.subs_max; ++i) {
        SUB_PROPERTIES *sub = &ff_p->av.sub[i];
        if (sub->valid && sub->stream == stream)
            return sub;
    }
    return NULL;
}

static int _reset_subtitle(STREAM *s)
{
    /* Only clear the old selected track. Fresh packets for the newly
     * selected track will enter sq through the unmodified parser route.
     * No history replay, metadata scan or audio/video seek is performed. */
    _flush_packets(&ff_p->sq, "SUB_SWITCH");
    DBGS serprintf("NOVA_SUB_HISTORY_DISABLED_ALL_V1: stream=%d fresh_only=1\n",
                   s->subtitle->stream);
    return 0;
}

"""

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--native",type=Path,required=True)
    ap.add_argument("--report",type=Path)
    args=ap.parse_args()
    f=args.native/"Source/stream_parser_ffmpeg.c"
    original=f.read_text(encoding="utf-8")
    assert original.count(START)==1, "Subtitle cache region must be unique"
    assert original.count(STOP)==1, "Subtitle cache end must be unique"
    assert original.count(PGS_START)==1, "PGS bypass must run first"
    assert original.count(SELECTED)==1, "Live subtitle routing must be present"
    assert original.count("_cache_subtitle_packet(s, &packet);")==1
    assert original.count("NOVA_SUB_HISTORY_DISABLED_ALL_V1")==0

    lo=original.index(START)
    hi=original.index(STOP,lo)
    assert lo < hi and hi-lo > 4000, "Cache code region unexpectedly small"
    s=original[:lo]+CHECKER+original[hi:]

    # Remove the ENTIRE old PGS-only branch (and its historical call).
    lo=s.index(PGS_START)
    hi=s.index(SELECTED,lo)
    assert 100 < hi-lo < 1000, "PGS bypass branch unexpectedly changed"
    assert "_cache_subtitle_packet(s, &packet);" in s[lo:hi]
    s=s[:lo]+s[hi:]

    # Exact source-level proof: NO history writer, recovery scanner,
    # replay walk, or cache heap node survives compilation.
    forbidden=(
        "_cache_subtitle_packet", "_subtitle_recovery_point",
        "_subtitle_packet_expired", "_pgs_recovery_packet",
        "_subtitle_switch_time", "_drop_cached_subtitle_stream",
        "_remove_cached_subtitle", "SUB_CACHE_MAX_BYTES",
        "SUB_CACHE_MAX_PACKETS", "SUB_CACHE_HISTORY_MS",
        "ff_p->sub_cache.list.first", "_add_packet(&ff_p->sub_cache",
    )
    for word in forbidden:
        assert word not in s, "Historical subtitle path remains: "+word

    assert s.count(SELECTED)==1
    assert s.count("_flush_packets(&ff_p->sq, \"SUB_SWITCH\")")==1
    assert s.count("NOVA_SUB_HISTORY_DISABLED_ALL_V1")==2
    assert s.count("sub_cache;")==1
    f.write_text(s,encoding="utf-8")
    report={
      "feature":"NOVA_SUB_HISTORY_DISABLED_ALL_V1",
      "subtitle_history_enabled":False,
      "types":"all internal tracks including PGS, ASS/text and DVD",
      "cache_packet_insertion_paths":0,
      "cache_replay_on_switch":False,
      "selected_track_packet_delivery":"original path unchanged",
      "cache_queue":"retained empty for diagnostics only",
      "unsupported":"instant redisplay of the prior subtitle line",
      "source":str(f),
    }
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print("NOVA_SUB_HISTORY_DISABLED_ALL_V1=PATCHED all_history_writers=0")

if __name__=="__main__":
    main()
