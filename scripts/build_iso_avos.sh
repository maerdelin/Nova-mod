#!/usr/bin/env bash
set -euo pipefail

OUT="${1:?output directory required}"
META="${2:?upstream metadata required}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$ROOT/work/iso-avos-source"
SRC="$WORK/aos-AVP"

TAG="$(python3 - "$META" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))["tag"])
PY
)"
if [[ "$TAG" != "v6.5.5" ]]; then
  echo "ISO-aware avos patch is ported only to official v6.5.5, got $TAG" >&2
  exit 1
fi

rm -rf "$OUT" "$WORK"
mkdir -p "$OUT" "$WORK"

git clone --quiet --depth 1 --branch "$TAG" https://github.com/nova-video-player/aos-AVP.git "$SRC"
git -C "$SRC" submodule update --init --recursive --jobs 6 --depth 1

AVOS_SHA="$(git -C "$SRC/native/avos" rev-parse HEAD)"
EXPECTED_AVOS_SHA="c34a05cd070f5aa89c0a26a73d7130d1fdfcd08a"
if [[ "$AVOS_SHA" != "$EXPECTED_AVOS_SHA" ]]; then
  echo "Unexpected v6.5.5 aos-avos SHA: $AVOS_SHA" >&2
  exit 1
fi

# Patch v6.5.5 build glue only: MediaLib calls native_libyuv but this tag's
# core.mk accidentally omits libyuv from NATIVE_PKG_LIST and the alias target.
python3 - "$SRC/core.mk" <<'PY'
from pathlib import Path
import re, sys

p=Path(sys.argv[1])
s=p.read_text()

pkg_start=s.find('NATIVE_PKG_LIST :=')
pkg_end=s.find('NATIVE_LIST :=')
if pkg_start < 0 or pkg_end < 0 or pkg_end <= pkg_start:
    raise SystemExit('Unable to locate NATIVE_PKG_LIST section')

pkg=s[pkg_start:pkg_end]
if 'native/libyuv' not in pkg:
    m=re.search(r'(^\s*native/libnativehelper\s*$)', pkg, re.M)
    if not m:
        raise SystemExit('Unable to locate native/libnativehelper entry in NATIVE_PKG_LIST')
    abs_start=pkg_start+m.start(1)
    s=s[:abs_start] + '\tnative/libyuv \\\n' + s[abs_start:]

if not re.search(r'^native_libyuv\s*:', s, re.M):
    m=re.search(r'^native_libnativehelper\s*:\s*native_build_native/libnativehelper\s*$', s, re.M)
    if not m:
        raise SystemExit('Unable to locate native_libnativehelper alias target')
    s=s[:m.start()] + 'native_libyuv: native_build_native/libyuv\n\n' + s[m.start():]

pkg_start=s.find('NATIVE_PKG_LIST :=')
pkg_end=s.find('NATIVE_LIST :=')
pkg=s[pkg_start:pkg_end]
if 'native/libyuv' not in pkg:
    raise SystemExit('Failed to add native/libyuv to NATIVE_PKG_LIST')
if not re.search(r'^native_libyuv\s*:\s*native_build_native/libyuv\s*$', s, re.M):
    raise SystemExit('Failed to add native_libyuv alias target')

p.write_text(s)
PY

python3 - "$SRC/native/avos/Source/stream_parser_ffmpeg.c" <<'PY'
from pathlib import Path
import sys

p=Path(sys.argv[1])
s=p.read_text()
old='''	// For thumbnails: use minimal probing to speed up processing
	if (ff_p->flags & STREAM_PARSER_THUMB) {
		av_dict_set(&ff_p->fmt_opts, "probesize", "500000", 0);      // 500KB instead of 10MB
		av_dict_set(&ff_p->fmt_opts, "analyzeduration", "1000000", 0);  // 1 second max
	} else {
		av_dict_set(&ff_p->fmt_opts, "probesize", "10000000", 0);
	}
'''
new='''	// For thumbnails: use minimal probing to speed up processing.
	// Blu-ray ISO proxy streams are already resolved by libbluray. Avoid the
	// expensive generic MPEG-TS deep probe and end-of-file PTS duration scan.
	// Every non-ISO URL retains the official Nova settings below.
	const int nova_iso_proxy = strstr(s->src_query, "nova_iso=1") != NULL;
	if (ff_p->flags & STREAM_PARSER_THUMB) {
		av_dict_set(&ff_p->fmt_opts, "probesize", "500000", 0);      // 500KB instead of 10MB
		av_dict_set(&ff_p->fmt_opts, "analyzeduration", "1000000", 0);  // 1 second max
	} else if (nova_iso_proxy) {
		av_dict_set(&ff_p->fmt_opts, "probesize", "2000000", 0);
		av_dict_set(&ff_p->fmt_opts, "analyzeduration", "1500000", 0);
		av_dict_set(&ff_p->fmt_opts, "skip_estimate_duration_from_pts", "1", 0);
		serprintf("FFMPEG: Nova ISO fast probe enabled\\n");
	} else {
		av_dict_set(&ff_p->fmt_opts, "probesize", "10000000", 0);
	}
'''
count=s.count(old)
if count != 1:
    raise SystemExit(f'Expected exact v6.5.5 probe block once, found {count}')
p.write_text(s.replace(old,new))
PY

cd "$SRC/Video"
./gradlew --no-daemon aNR

mapfile -t APKS < <(find "$SRC/Video" -type f -name '*.apk' | sort)
if [[ "${#APKS[@]}" -eq 0 ]]; then
  echo "No APK produced by official Gradle build" >&2
  exit 1
fi

for abi in arm64-v8a armeabi-v7a x86 x86_64; do
  mkdir -p "$OUT/$abi"
  found=""
  for apk in "${APKS[@]}"; do
    if unzip -Z1 "$apk" | grep -qx "lib/$abi/libavos.so"; then
      unzip -p "$apk" "lib/$abi/libavos.so" > "$OUT/$abi/libavos.so"
      found="$apk"
      break
    fi
  done
  if [[ -z "$found" || ! -s "$OUT/$abi/libavos.so" ]]; then
    echo "Unable to extract rebuilt libavos.so for $abi" >&2
    printf '%s\n' "${APKS[@]}" >&2
    exit 1
  fi
  strings "$OUT/$abi/libavos.so" | grep -qx 'nova_iso=1'
  strings "$OUT/$abi/libavos.so" | grep -qx 'skip_estimate_duration_from_pts'
  strings "$OUT/$abi/libavos.so" | grep -qx '10000000'
  file "$OUT/$abi/libavos.so"
  sha256sum "$OUT/$abi/libavos.so"
done

printf '%s\n' "$AVOS_SHA" > "$OUT/upstream-avos-sha.txt"
