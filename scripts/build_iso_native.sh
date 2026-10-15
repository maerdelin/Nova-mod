#!/usr/bin/env bash
set -euo pipefail

OUT="${1:?output directory required}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$ROOT/work/iso-third-party"
SRC="$WORK/libbluray"
PIN="448f896091634ab84776a3d062f0e1826e13ac6c"
API=23

rm -rf "$OUT" "$WORK"
mkdir -p "$OUT" "$WORK"

git clone --quiet https://github.com/zhongflyTeam/libbluray.git "$SRC"
git -C "$SRC" checkout --quiet "$PIN"
git -C "$SRC" submodule update --init --recursive --quiet

NDK_ROOT="${ANDROID_NDK_ROOT:-${ANDROID_NDK_HOME:-}}"
if [[ -z "$NDK_ROOT" || ! -d "$NDK_ROOT/toolchains/llvm/prebuilt/linux-x86_64" ]]; then
  NDK_ROOT="$ANDROID_HOME/ndk/$(ls "$ANDROID_HOME/ndk" | sort -V | tail -n 1)"
fi
TOOL="$NDK_ROOT/toolchains/llvm/prebuilt/linux-x86_64"
[[ -d "$TOOL" ]] || { echo "Android NDK toolchain not found" >&2; exit 1; }

build_one() {
  local abi="$1" triple="$2" family="$3" cpu="$4"
  local b="$WORK/build-$abi"
  local cross="$WORK/cross-$abi.ini"
  local cc="$TOOL/bin/${triple}${API}-clang"

  cat > "$cross" <<EOF
[binaries]
c = '$cc'
ar = '$TOOL/bin/llvm-ar'
strip = '$TOOL/bin/llvm-strip'

[host_machine]
system = 'android'
cpu_family = '$family'
cpu = '$cpu'
endian = 'little'

[properties]
needs_exe_wrapper = true
EOF

  meson setup "$b" "$SRC" --cross-file "$cross" --default-library=static \
    -Dbdj_jar=disabled -Dfreetype=disabled -Dfontconfig=disabled -Dlibxml2=disabled \
    -Denable_tools=false -Denable_devtools=false -Denable_examples=false -Denable_docs=false
  ninja -C "$b"

  local bluray udf
  bluray="$(find "$b" -type f -name 'libbluray.a' | head -n 1)"
  udf="$(find "$b" -type f -name 'libudfread.a' | head -n 1)"
  [[ -f "$bluray" && -f "$udf" ]] || {
    echo "Static libbluray/libudfread archives not found for $abi" >&2
    find "$b" -name '*.a' -print >&2
    exit 1
  }

  mkdir -p "$OUT/$abi"
  "$cc" -shared -fPIC -O2 -fvisibility=hidden \
    -I"$SRC/src" -I"$SRC/src/libbluray" \
    "$ROOT/iso/nova_iso.c" \
    -Wl,--start-group "$bluray" "$udf" -Wl,--end-group \
    -llog -ldl -lm -lz -latomic \
    -Wl,-z,relro,-z,now \
    -o "$OUT/$abi/libnova_iso.so"
  "$TOOL/bin/llvm-strip" --strip-unneeded "$OUT/$abi/libnova_iso.so"
  file "$OUT/$abi/libnova_iso.so"
}

build_one arm64-v8a aarch64-linux-android aarch64 aarch64
build_one armeabi-v7a armv7a-linux-androideabi arm armv7
build_one x86 i686-linux-android x86 i686
build_one x86_64 x86_64-linux-android x86_64 x86_64

find "$OUT" -type f -name 'libnova_iso.so' -print -exec sha256sum {} \;
