#!/usr/bin/env bash
# Replays the ACTUAL 1133 native source modifications on the same pinned AVOS
# revision, but NEVER builds native libraries nor an APK.
set -euo pipefail
mkdir -p native-src/native reports
git clone -q https://github.com/nova-video-player/aos-avos.git native-src/native/avos
git -C native-src/native/avos checkout -q --detach d4abfdf075d4f7bfdee9a47cb2c02067f92f47cd
n=native-src/native/avos
python3 scripts/v66_subtitle_jni_patch.py --native "$n"
python3 scripts/subtitle_1074_async_exit_patch.py --native "$n"
python3 scripts/native_rebuffer_patch.py "$n" --allow-unpinned-head --report reports/native-rebuffer.json
python3 scripts/direct_transport_native_patch.py "$n" --report reports/direct-transport-native.json
python3 scripts/shared42_native_patch.py --native "$n"
python3 scripts/shared42_pool_audit_v2_patch.py --transport iso/nova_transport.c
python3 scripts/playback_completion_patch.py "$n" --report reports/playback-completion-native.json
python3 scripts/main655_ts_eof_lead_gate.py --native "$n" --report reports/main655-ts-eof-leadgate.json
python3 scripts/ts_bitrate_patch.py "$n" --report reports/ts-bitrate.json
python3 scripts/ts_resume_fallback_patch.py "$n" --report reports/ts-resume-fallback.json
python3 scripts/iso_fast_probe_patch.py "$n" --report reports/iso-fast-probe.json
python3 scripts/iso_seek_ui_patch.py --native "$n" --report reports/iso-timeline.json
python3 scripts/av_diag_patch.py --native "$n" --report reports/av-diagnostics.json
python3 scripts/startup_freeze_trace_patch.py --native "$n" --report reports/startup-freeze-trace.json
python3 scripts/final_freeze_forensics_patch.py --native "$n" --report reports/final-freeze-forensics.json
python3 scripts/pgs_history_bypass_ab_patch.py --native "$n" --report reports/pgs-history-bypass-ab.json
python3 scripts/mp4_seek_slow_read_grace_patch.py --native "$n" --report reports/mp4-seek-slow-read-grace.json
python3 scripts/disable_all_subtitle_history_patch.py --native "$n" --report reports/all-subtitle-history-disabled.json
python3 scripts/late_stall_self_heal_patch.py --native "$n" --report reports/late-render-recovery.json
python3 scripts/seek_sfdec2_frame_return_patch.py --native "$n"
python3 scripts/seek_engine_diag_patch.py --native "$n"
python3 scripts/seek_stall_forensics_v2_patch.py --native "$n"
python3 scripts/seek_codec_pool_diag_patch.py --native "$n"
python3 scripts/iso_index_seek_patch.py --native "$n" --transport iso/nova_transport.c
python3 scripts/mkv_bbc_cue_seek_patch.py --native "$n"
python3 scripts/iso_track_metadata_patch.py --native "$n"
python3 scripts/startup_bbc_seek_fix_patch.py --native "$n" --report reports/startup-bbc-seek-fix.json
python3 scripts/precise_seek_patch.py --native "$n" --report reports/precise-seek.json
python3 scripts/startup_boot_raw_diag.py --native "$n"
python3 scripts/startup_onepass_speed_patch.py --native "$n"
python3 scripts/startup_staged_decode_patch.py --native "$n"
python3 scripts/iso_hw_cbe_reliability_patch.py --native "$n"
python3 scripts/iso_1073_avos_patch.py --native "$n"
python3 scripts/global_logs_native_patch.py --native "$n" --transport iso/nova_transport.c
for f in "$n/Include/log.h" "$n/Source/log_android.c" "$n/Source/stream_video.c" "$n/Source/codec_sfdec2.c" "$n/Source/stream_parser_ffmpeg.c" iso/nova_transport.c iso/nova_diag_gate.c iso/nova_iso_blackbox.inc; do test -s "$f"; done
mkdir -p out/native-source
tar -czf out/native-source/avos-patched-source.tar.gz -C native-src/native avos/Include/log.h avos/Source/log_android.c avos/Source/stream_video.c avos/Source/stream_parser_ffmpeg.c avos/Source/codec_sfdec2.c avos/Source/stream_sink_audio.c
tar -czf out/native-source/transport-patched-source.tar.gz iso/nova_transport.c iso/nova_diag_gate.c iso/nova_iso_blackbox.inc iso/nova_literange4.inc
echo 'NOVA_GLOBAL_LOGS_FULL_NATIVE_SOURCE_REPLAY=PASS; NO APK COMPILED'
