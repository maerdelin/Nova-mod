#!/usr/bin/env python3
"""Link the official v6.6 subtitle engine/JNI sources into the rebuilt AVOS.

The upstream Android common.mk omits the new JNI implementation and engine
source group. The v6.6 UI calls SubtitleEngine.nativeCreate() on video open;
without the symbols it crashes. Fail closed if sources/layout differ.
"""
from pathlib import Path
import argparse

FILES = (
    "sub_engine.c",
    "sub_style.c",
    "sub_render_gl.c",
    "sub_engine_registry.c",
)
JNI = "Java_com_archos_mediacenter_video_player_SubtitleEngine_nativeCreate"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--native", type=Path, required=True)
    args = ap.parse_args()
    root = args.native
    common = root / "common.mk"
    ndk = root / "ndkbuild.mk"
    source = (root / "Source" / "jni_sub_engine.c").read_text()
    if JNI not in source:
        raise RuntimeError("Official SubtitleEngine JNI export disappeared")
    for name in FILES:
        if not (root / "Source" / name).is_file():
            raise RuntimeError("Missing official subtitle implementation " + name)
    text = common.read_text()
    sentinel = "# NOVA_V66_SUBTITLE_JNI_SOURCES"
    if sentinel in text:
        raise RuntimeError("Subtitle source patch applied twice")
    needle = "$(CSRC_STREAM_SUB) $(CSRC_AUDIO)"
    if text.count(needle) != 1:
        raise RuntimeError("AVOS common.mk CSRC aggregate changed")
    text = text.replace(needle, needle +
        "\n" + sentinel + "\nCSRC += " + " ".join(FILES) + "\n", 1)
    common.write_text(text)
    cfg = ndk.read_text()
    marker = "LOCAL_LDLIBS := -L$(TARGET_OUT) -lz \\\n"
    if cfg.count(marker) != 1:
        raise RuntimeError("AVOS Android linker layout changed")
    cfg = cfg.replace(marker,
        "LOCAL_LDLIBS := -L$(TARGET_OUT) -lz -lEGL -lGLESv2 -landroid -ljnigraphics \\\n", 1)
    ndk.write_text(cfg)
    jni = root / "jni" / "libavosjni" / "ndkbuild.mk"
    jsrc = jni.read_text()
    old_src = ("LOCAL_SRC_FILES := \\\n\tlibavos.c \\\n\tavos_media_player.c \\\n\tavos_media_metadata_retriever.c")
    if jsrc.count(old_src) != 1:
        raise RuntimeError("Official v6.6 libavosjni source list changed")
    new_src = old_src + " \\\n\t../../Source/jni_sub_engine.c \\\n\t../../Source/jni_font_name_parser.c"
    jsrc = jsrc.replace(old_src, new_src, 1)
    inc = "LOCAL_C_INCLUDES := \\\n\t$(AVOS_DIR)/public"
    if jsrc.count(inc) != 1:
        raise RuntimeError("Official JNI include layout changed")
    jsrc = jsrc.replace(inc, inc + " \\\n\t$(AVOS_DIR)/Include", 1)
    ld = "LOCAL_LDLIBS:= -L$(TARGET_OUT) -llog -landroid"
    if jsrc.count(ld) != 1:
        raise RuntimeError("Official JNI linker line changed")
    jsrc = jsrc.replace(ld, ld + " -ljnigraphics", 1)
    jni.write_text(jsrc)
    print("NOVA_V66_SUBTITLE_ENGINE_JNI_SOURCE_PORT=PASS core=" + " ".join(FILES) + " jni=jni_sub_engine.c,jni_font_name_parser.c")

if __name__ == "__main__":
    main()
