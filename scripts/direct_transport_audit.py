# direct transport architecture audit

from pathlib import Path
import argparse, json, zipfile

ROOT=Path(__file__).resolve().parents[1]

REMOVED_RUNTIME_SOURCES=(
    "iso/nova_iso.c",
    "scripts/build_iso_native.sh",
    "scripts/iso_patch.py",
    "scripts/iso_finalize.py",
    "scripts/iso_single_stream_qos_patch.py",
    "scripts/stream_throughput_patch.py",
    "scripts/webdav_connect_retry_patch.py",
    "scripts/webdav_midstream_resume_patch.py",
    "scripts/main_transport_audit.py",
)

def source_check(require_removed=False):
    transport=(ROOT/"iso/nova_transport.c").read_text()
    native=(ROOT/"scripts/direct_transport_native_patch.py").read_text()
    apply=(ROOT/"scripts/direct_transport_apply.py").read_text()
    workflow=(ROOT/".github/workflows/nova-video-player-mod.yml").read_text()

    for x in (
        "nova_transport_read", "nova_transport_seek", "nova_transport_size",
        "nova_transport_abort", "bd_open_stream", "avio_open2",
    ):
        if x not in transport:
            raise RuntimeError("direct transport invariant missing: "+x)

    for x in (
        "socket(", "listen(", "accept(", "connect_loopback",
        "127.0.0.1", "localhost", "CACHE_SLOTS", "CACHE_BYTES",
    ):
        if x in transport:
            raise RuntimeError("legacy proxy/cache residue: "+x)

    for x in (
        "novatransport://", "NOVA_DIRECT_SOURCE_OPEN",
        "libnova_transport.so", "nova_transport_read", "nova_transport_abort",
    ):
        if x not in native:
            raise RuntimeError("AVOS direct source invariant missing: "+x)

    base=(ROOT/"scripts/native_rebuffer_patch.py").read_text()
    for x in (
        "const int requested_nice = -8",
        'nova_playback_yield_sched("decode", 8)',
        'nova_playback_yield_sched("parser", 5)',
    ):
        if x not in base:
            raise RuntimeError("priority baseline changed: "+x)
