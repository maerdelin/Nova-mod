#!/usr/bin/env bash
set -euo pipefail

OUT="$1"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$ROOT/work/transport-third-party"
SRC="$WORK/libbluray"
PIN="448f896091634ab84776a3d062f0e1826e13ac6c"
API=23

rm -rf "$OUT" "$WORK"
mkdir -p "$OUT" "$WORK"

git clone --quiet https://github.com/zhongflyTeam/libbluray.git "$SRC"
git -C "$SRC" checkout --quiet "$PIN"
git -C "$SRC" submodule update --init --recursive --quiet
# Read-only time-to-byte navigation index: modify ONLY pinned libbluray.
python3 "$ROOT/scripts/libbluray_iso_index_patch.py" "$SRC/src/libbluray/bluray.c"
grep -Fq 'NOVA_BD_READONLY_TIME_INDEX_V3' "$SRC/src/libbluray/bluray.c"


git clone --quiet --depth 1 --branch curl-8_16_0 https://github.com/curl/curl.git "$WORK/curl-src"
git clone --quiet --depth 1 --branch openssl-3.5.4 https://github.com/openssl/openssl.git "$WORK/openssl-src"

NDK_ROOT="$ANDROID_NDK_ROOT"
if [[ -z "$NDK_ROOT" ]]; then NDK_ROOT="$ANDROID_NDK_HOME"; fi
if [[ -z "$NDK_ROOT" || ! -d "$NDK_ROOT/toolchains/llvm/prebuilt/linux-x86_64" ]]; then
  NDK_ROOT="$ANDROID_HOME/ndk/$(ls "$ANDROID_HOME/ndk" | sort -V | tail -n 1)"
fi
TOOL="$NDK_ROOT/toolchains/llvm/prebuilt/linux-x86_64"
[[ -d "$TOOL" ]] || { echo "Android NDK toolchain not found" >&2; exit 1; }

build_one() {
  local abi="$1" triple="$2" family="$3" cpu="$4"
  local b="$WORK/build-$abi"
  local cross="$WORK/cross-$abi.ini"
  local cc="$TOOL/bin/$triple$API-clang"
  local ff="$ROOT/native-src/native/prebuilt/ffmpeg/dist-full-$abi"

  [[ -f "$ff/include/libavformat/avio.h" ]] || {
    echo "FFmpeg headers missing for $abi: $ff" >&2
    exit 1
  }

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
  [[ -f "$bluray" && -f "$udf" ]] || exit 1


  # LiteRange4 uses the already-running RAW128 thread and a native curl Multi
  # event loop. Build the TLS backend and curl for the exact target ABI.
  local ssl="$WORK/openssl-$abi"
  local curl_src="$WORK/curl-src"
  local curl_build="$WORK/curl-build-$abi"
  local toolchain="$NDK_ROOT/build/cmake/android.toolchain.cmake"
  local arch=""
  case "$abi" in
    arm64-v8a) arch="android-arm64" ;;
    armeabi-v7a) arch="android-arm" ;;
    x86) arch="android-x86" ;;
    x86_64) arch="android-x86_64" ;;
  esac
  mkdir -p "$ssl"
  (
    cd "$ROOT/work/transport-third-party/openssl-src"
    export ANDROID_NDK_HOME="$NDK_ROOT"
    export PATH="$TOOL/bin:$PATH"
    ./Configure "$arch" no-shared no-tests no-apps no-engine \
      --prefix="$ssl" --openssldir="$ssl/ssl" --libdir=lib -D__ANDROID_API__="$API"
    make -j4
    make install_sw
    make clean
  )
  cmake -S "$curl_src" -B "$curl_build" \
    -DCMAKE_TOOLCHAIN_FILE="$toolchain" \
    -DANDROID_ABI="$abi" -DANDROID_PLATFORM="android-$API" \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=OFF -DBUILD_CURL_EXE=OFF -DBUILD_TESTING=OFF \
    -DCURL_USE_OPENSSL=ON -DOPENSSL_ROOT_DIR="$ssl" \
    -DOPENSSL_INCLUDE_DIR="$ssl/include" \
    -DOPENSSL_SSL_LIBRARY="$ssl/lib/libssl.a" \
    -DOPENSSL_CRYPTO_LIBRARY="$ssl/lib/libcrypto.a" \
    -DCURL_ZLIB=OFF -DCURL_USE_LIBPSL=OFF -DUSE_NGHTTP2=OFF \
    -DUSE_LIBIDN2=OFF -DCURL_BROTLI=OFF -DCURL_ZSTD=OFF \
    -DCURL_DISABLE_LDAP=ON -DCURL_DISABLE_LDAPS=ON \
    -DCURL_DISABLE_FTP=ON -DCURL_DISABLE_TELNET=ON -DCURL_DISABLE_TFTP=ON \
    -DCURL_DISABLE_DICT=ON -DCURL_DISABLE_GOPHER=ON \
    -DCURL_DISABLE_IMAP=ON -DCURL_DISABLE_POP3=ON -DCURL_DISABLE_SMTP=ON \
    -DCURL_DISABLE_RTSP=ON -DCURL_DISABLE_MQTT=ON \
    -DCURL_DISABLE_WEBSOCKETS=ON -DCURL_DISABLE_PROXY=ON
  cmake --build "$curl_build" -j4
  local curl_a
  curl_a="$(find "$curl_build" -name libcurl.a | head -n1)"
  [[ -s "$curl_a" ]] || { echo "missing curl static archive: $abi" >&2; exit 1; }

  mkdir -p "$OUT/$abi"
  "$cc" -shared -fPIC -O2 -fvisibility=hidden \
    -I"$SRC/src" -I"$SRC/src/libbluray" -I"$ff/include" \
    -I"$curl_src/include" -I"$ssl/include" \
    "$ROOT/iso/nova_transport.c" "$curl_a" "$ssl/lib/libssl.a" "$ssl/lib/libcrypto.a" \
    -Wl,--start-group "$bluray" "$udf" -Wl,--end-group \
    -L"$ff/lib" -lavformat -lavutil \
    -llog -ldl -lm -lz -latomic \
    -Wl,-z,relro,-z,now \
    -o "$OUT/$abi/libnova_transport.so"
  "$TOOL/bin/llvm-strip" --strip-unneeded "$OUT/$abi/libnova_transport.so"
  "$TOOL/bin/llvm-readelf" -d "$OUT/$abi/libnova_transport.so" | \
    sed -n 's/.*Shared library: \[\(.*\)\]/NEEDED \1/p'
}

build_one arm64-v8a aarch64-linux-android aarch64 aarch64
build_one armeabi-v7a armv7a-linux-androideabi arm armv7
build_one x86 i686-linux-android x86 i686
build_one x86_64 x86_64-linux-android x86_64 x86_64

find "$OUT" -type f -name 'libnova_transport.so' -print -exec sha256sum {} \;
