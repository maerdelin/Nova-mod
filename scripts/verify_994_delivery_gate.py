#!/usr/bin/env python3
"""NOVA 994 fail-closed five-goal delivery gate.

There is a fundamental difference between producing a test APK and releasing
an accepted APK. This gate must pass before any installable APK artifact from
the 994 validation branch is exposed. Missing evidence is always a failure.

The evidence must be generated from the exact signed build-under-test, not
copied from earlier runs or synthesized from source-string checks.
"""
import argparse
import hashlib
import json
from pathlib import Path


def validated(path: Path, label: str, expected_sha: str) -> dict:
    if not path.is_file():
        raise AssertionError(f"994 {label}: real signed-APK acceptance evidence absent: {path}")
    payload = json.loads(path.read_text())
    assert payload.get("status") == "PASS", f"994 {label}: {path} has no PASS result"
    assert payload.get("apk_sha256") == expected_sha, (
        f"994 {label}: evidence belongs to another APK, or has no SHA-256"
    )
    return payload


def check(apk: Path, report_dir: Path) -> dict:
    if not apk.is_file() or apk.stat().st_size < 1_000_000:
        raise AssertionError("994 signed APK not present")
    digest = hashlib.sha256(apk.read_bytes()).hexdigest()
    iso = validated(report_dir / "994-iso-device" / "994-iso-startup.json",
                    "ISO real runtime", digest)
    assert iso.get("real_first_frame") is True, "994 ISO: actual first frame not verified"
    assert iso.get("w2_during_metadata") is True, "994 #1: real W2/meta overlap absent"
    assert iso.get("curl_multi_perform_before_meta_end") is True, "994 #1: W2 not driven while scanning"
    assert iso.get("two_lanes") is True, "994 #4: dual-lane not verified"
    assert iso.get("startup_prefix_replay") is True, "994 #3: initial replay absent"
    assert iso.get("iso_lba_jump_count") == 0, "994 #3: iso-lba-jump still resets W2"
    assert iso.get("w2_before_first_frame") is True, "994 #4: W2 must precede first frame"
    assert iso.get("owner_handoff") is True, "994 ISO: parallel thread handoff absent"

    mkv = validated(report_dir / "994-mkv-startup-compare.json",
                    "MKV real startup benchmark", digest)
    assert mkv.get("same_media_and_network_conditions") is True, (
        "994 #2: MKV baseline and candidate were not compared under the same conditions"
    )
    assert mkv.get("mkv_stream_probe_and_seek_regression") is True, (
        "994 #2: seek, audio, subtitle, attachments are not regression-tested"
    )
    old = mkv.get("baseline_median_startup_ms")
    new = mkv.get("candidate_median_startup_ms")
    assert isinstance(old, (int, float)) and isinstance(new, (int, float))
    assert old > new >= 0, "994 #2: actual MKV startup scan not faster than #993"

    ui = validated(report_dir / "994-startup-ui-runtime.json",
                   "percent spinner visual/runtime", digest)
    assert ui.get("integer_buffer_percent_0_to_100") is True
    assert ui.get("refresh_interval_ms") == 500
    assert ui.get("native_resident_over_resume_threshold") is True
    assert ui.get("loading_text_and_spinner_exit_after_first_resume") is True
    assert ui.get("title_hides_independently") is True
    assert ui.get("verified_from_real_playback") is True, (
        "994 #5: static Smali test alone cannot replace real visual acceptance"
    )
    return {"status": "PASS", "apk_sha256": digest,
            "goals": ["ISO-parallel", "MKV-faster", "ISO-no-rebase",
                      "early-dual-lane", "500ms-percent-loading-overlay"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    args = parser.parse_args()
    result = check(args.apk, args.reports)
    output = args.reports / "994-five-goal-release-gate.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    print("NOVA_994_ALL_FIVE_RUNTIME_ACCEPTANCE=PASS", result)


if __name__ == "__main__":
    main()
