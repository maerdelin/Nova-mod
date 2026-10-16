#!/usr/bin/env bash
set -euo pipefail

OUT_ARG="${1:?output directory required}"
META="${2:?upstream metadata required}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "$OUT_ARG" = /* ]]; then OUT="$OUT_ARG"; else OUT="$ROOT/$OUT_ARG"; fi
WORK="$ROOT/work/kodi-buffer-v2-source"
SRC="$WORK/aos-AVP"

TAG="$(python3 - "$META" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))["tag"])
PY
)"
if [[ "$TAG" != "v6.5.5" ]]; then
  echo "Kodi-buffer V2 source patch is currently ported only to official v6.5.5; got $TAG" >&2
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

python3 "$ROOT/rebuffer/apply_avos_kodi_v2.py" "$SRC"

# v6.5.5 build glue misses native/libyuv in NATIVE_PKG_LIST; patch only build glue.
python3 - "$SRC/core.mk" <<'PY'
from pathlib import Path
import re,sys
p=Path(sys.argv[1]); s=p.read_text()
a=s.find('NATIVE_PKG_LIST :='); b=s.find('NATIVE_LIST :=')
if a<0 or b<0 or b<=a: raise SystemExit('Unable to locate NATIVE_PKG_LIST')
pkg=s[a:b]
if 'native/libyuv' not in pkg:
    m=re.search(r'(^\s*native/libnativehelper\s*$)',pkg,re.M)
    if not m: raise SystemExit('native/libnativehelper anchor missing')
    pos=a+m.start(1); s=s[:pos]+'\tnative/libyuv \\\n'+s[pos:]
if not re.search(r'^native_libyuv\s*:',s,re.M):
    m=re.search(r'^native_libnativehelper\s*:\s*native_build_native/libnativehelper\s*$',s,re.M)
    if not m: raise SystemExit('native_libnativehelper alias missing')
    s=s[:m.start()]+'native_libyuv: native_build_native/libyuv\n\n'+s[m.start():]
p.write_text(s)
PY

cd "$SRC/Video"
./gradlew --no-daemon aNR

mapfile -t APKS < <(find "$SRC/Video" -type f -name '*.apk' | sort)
test "${#APKS[@]}" -gt 0

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
  test -n "$found"
  test -s "$OUT/$abi/libavos.so"
  strings "$OUT/$abi/libavos.so" | grep -q 'NOVA_REBUFFER_START'
  strings "$OUT/$abi/libavos.so" | grep -q 'NOVA_CACHE_CONFIG'
  sha256sum "$OUT/$abi/libavos.so"
done

printf '%s\n' "$AVOS_SHA" > "$OUT/upstream-avos-sha.txt"
