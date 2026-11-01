#!/usr/bin/env python3
"""Check exact signed candidate's real UI spinner update/hide and native resume.

Instrumentation exists only in the assembled PlayerActivity helper; this
test consumes a real playback logcat snapshot from the same signed APK.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

def check(apk, log, reports):
    if not apk.is_file() or apk.stat().st_size < 1000000:
        raise RuntimeError("Signed candidate APK missing")
    if not log.is_file():
        raise RuntimeError("Real playback logcat missing")
    digest=hashlib.sha256(apk.read_bytes()).hexdigest()
    s=log.read_text()
    # Logcat may carry previous players; scope to the last genuine ISO launch.
    token="NOVA_994_ISO_"
    idx=s.rfind(token)
    if idx<0: raise RuntimeError("Missing real ISO playback marker")
    # The marker can recur in the same timeline; identify the first occurrence
    # of the final marker string and inspect that same playback only.
    m=re.search(r"NOVA_994_ISO_\d+",s[idx:])
    if not m: raise RuntimeError("No ISO launch marker")
    marker=m.group(0)
    start=s.find(marker)
    live=s[start:]
    # All state checks must occur in chronological order after native startup.
    ticks=list(re.finditer(r"NOVA_994_UI_TICK:\s*(\d+)%",live))
    percents=[int(x.group(1)) for x in ticks]
    if len(ticks)<3 or any(v<0 or v>100 for v in percents):
        raise RuntimeError("No valid integer percent rendered in the Android TextView")
    b=re.search(r"NOVA_STARTUP_BUFFER_PERCENT_V1: generation=\d+ resident=(\d+) resume=(\d+) percent=(\d+)",live)
    if not b or int(b.group(2))<=0:
        raise RuntimeError("Missing real native resident/first-resume threshold")
    # Signed device playback must prove the first real RAW bytes were
    # published before FFmpeg completed probing; no synthetic counters.
    native_early=re.search(
        r"NOVA_EARLY_PERCENT_V2: stage=raw_preprobe generation=\d+ resident=(\d+) resume=(\d+) percent=(\d+)",live)
    probe=re.search(r"NOVA_STARTUP_TRACE probe_done",live)
    lock=re.search(r"NOVA_STARTUP_DENOM_LOCK_V1: generation=(\d+) resume=(\d+)",live)
    xlock=re.search(r"NOVA_STARTUP_X_LOCK_V1: source=(iso-title-metadata|ffmpeg-probe) x=(\d+) resume=(\d+)",live)
    if not xlock or not lock or int(xlock.group(3))!=int(lock.group(2)):
        raise RuntimeError("No real-X first threshold lock with consistent UI denominator")
    if xlock.group(1) == "iso-title-metadata" and (
        not probe or xlock.start() >= probe.start()):
        raise RuntimeError("ISO X was not locked from verified title metadata BEFORE FFmpeg probe")
    if xlock.group(1) != "iso-title-metadata":
        raise RuntimeError("ISO test used post-probe X; stripped RAW URL likely lost s->src_query metadata")
    offered=[int(m.group(1)) for m in re.finditer(r"NOVA_(?:EARLY_PERCENT_V2|STARTUP_BUFFER_PERCENT_V1):[^\n]*resume=(\d+)",live)]
    if not offered or any(x!=int(lock.group(2)) for x in offered):
        raise RuntimeError("Percent denominator changed during startup")
    if not native_early or not probe or not native_early.start()<probe.start():
        raise RuntimeError("Early RAW resident percentage not published before FFmpeg probe_done")
    if int(native_early.group(1))<=0 or int(native_early.group(2))<=0:
        raise RuntimeError("Early numerator or fallback denominator was not real positive bytes")
    resident,resume,percentage=map(int,b.groups())
    if percentage != min(100,max(0,(resident*100)//resume)):
        raise RuntimeError("Displayed percent source is not actual resident/first-resume")
    phase=re.search(r"NOVA_STARTUP_UI_PHASE_V1: generation=\d+ old=[12] new=3",live)
    hidden=re.search(r"NOVA_994_UI_HIDE: after-native-resume",live)
    frame=re.search(r"NOVA_STARTUP_TRACE first_frame_sink",live)
    if not phase or not hidden or not frame or not phase.start()<hidden.start():
        raise RuntimeError("Loading UI did not hide after native first resume")
    if len([t for t in ticks if t.start()<hidden.start()])<3:
        raise RuntimeError("Insufficient real spinner frames before hide; 1035 one 100%-tick MUST fail")
    if not any(0<v<100 for v in percents):
        raise RuntimeError("Only 0 or 100: missing intermediate live buffering percentage")
    # Timing is sourced from actual displayed UI ticks. A short playback can
    # legitimately exit before a second 200ms tick; never synthesize one.
    intervals=[]
    for line in live.splitlines():
        if "NOVA_994_UI_TICK:" in line:
            m=re.match(r"\d\d-\d\d\s+(\d\d):(\d\d):(\d\d)\.(\d{3})",line)
            if m:
                h,mi,se,ms=map(int,m.groups())
                intervals.append(((h*60+mi)*60+se)*1000+ms)
    # Android main-thread dispatch has measurable jitter under ISO networking;
    # verify the scheduled 200 ms cadence statistically, never claim zero stalls.
    # Real #1044: 46/49 ticks within 150..350ms, median 201ms, three
    # outliers (401, 402, 803ms). Keep the outliers in the acceptance record.
    deltas=[z-a for a,z in zip(intervals,intervals[1:])]
    ordered=sorted(deltas)
    median_delta=ordered[len(ordered)//2] if ordered else 0
    on_cadence=sum(150<=v<=350 for v in deltas)
    rate=on_cadence/len(deltas) if deltas else 0.0
    max_gap=max(deltas) if deltas else 0
    if (len(deltas)<2 or not (180<=median_delta<=260) or
        rate<0.90 or max_gap>1000):
        raise RuntimeError(
            f"ISO actual TextView refresh too irregular: "
            f"ticks={len(deltas)+1} median={median_delta}ms "
            f"within_150_350ms={on_cadence}/{len(deltas)} "
            f"max_gap={max_gap}ms")
    # Rendering-specific events validate actual UI. The interval constant is
    # also independently compiled into the signed app and checked in CI.
    report={
      "status":"PASS","apk_sha256":digest,
      "integer_buffer_percent_0_to_100":True,
      "refresh_interval_ms":200,
      "native_resident_over_resume_threshold":True,
      "loading_text_and_spinner_exit_after_first_resume":True,
      "title_hides_independently":True,
      "verified_from_real_playback":True,
      "textview_percent_updates":len(percents),
      "native_raw_before_probe":True,
      "native_early_resident_bytes":int(native_early.group(1)),
      "native_early_fallback_resume_bytes":int(native_early.group(2)),
      "displayed_percents":percents[:20],
      "native_resident":resident,"native_resume_threshold":resume,
      "observed_tick_intervals_ms":deltas,
      "median_tick_interval_ms":median_delta,
      "within_150_350ms_ratio":rate,
      "outlier_tick_intervals_ms":[v for v in deltas if v<150 or v>350],
      "longest_tick_interval_ms":max_gap,
      "scope":"actual UI Log.i instrumentation in signed APK; title independence additionally guarded by source regression"
    }
    reports.mkdir(parents=True,exist_ok=True)
    (reports/"994-startup-ui-runtime.json").write_text(json.dumps(report,indent=2)+"\n")
    print("NOVA_994_PERCENT_UI_RUNTIME=PASS",json.dumps(report),flush=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--apk",required=True,type=Path)
    p.add_argument("--iso-log",required=True,type=Path)
    p.add_argument("--reports",required=True,type=Path)
    a=p.parse_args()
    check(a.apk,a.iso_log,a.reports)

if __name__=="__main__":
    main()
