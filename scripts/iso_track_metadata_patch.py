#!/usr/bin/env python3
"""NOVA_ISO_TRACK_LANG_V1: restore Blu-ray playlist PID languages for ISO only.

Apply after native_rebuffer_patch.py, direct_transport_native_patch.py,
iso_index_seek_patch.py and mkv_bbc_cue_seek_patch.py. The existing
FFmpeg stream probe, parser, raw buffering, codec and seek paths are unchanged.
"""
import argparse
from pathlib import Path

MARKER = "NOVA_ISO_TRACK_APPLIED_V1"
ANCHOR = "\tif (_parse_format(s->etype, ff_p)) goto ErrorExit4;"

REPLACEMENT = r'''    /* NOVA_ISO_TRACK_LANG_V1: CLPI language -> FFmpeg AVStream metadata.
     * Run only for Blu-ray ISO proxy after FFmpeg discovers MPEG-TS PIDs,
     * and before _parse_format populates audio/subtitle menu properties.
     * Preserve FFmpeg languages if already set; never invent track titles. */
    if (strstr(s->src_query, "&nova_iso=1&") &&
        ff_p->raw.enabled && ff_p->raw.direct_transport &&
        ff_p->raw.transport_handle && ff_p->raw.transport_generation) {
        typedef int (*nova_iso_lang_lookup_fn)(uint64_t, int, int,
                                               char *, unsigned);
        nova_iso_lang_lookup_fn lookup = (nova_iso_lang_lookup_fn)dlsym(
            ff_p->raw.transport_handle, "nova_transport_iso_track_language");
        unsigned restored = 0, existing = 0, missing = 0;
        if (lookup) {
            for (unsigned track = 0; track < ff_p->fmt->nb_streams; ++track) {
                AVStream *st = ff_p->fmt->streams[track];
                if (!st || !st->codecpar) continue;
                int kind = st->codecpar->codec_type == AVMEDIA_TYPE_AUDIO ? 1 :
                    (st->codecpar->codec_type == AVMEDIA_TYPE_SUBTITLE ? 2 : 0);
                if (!kind) continue;
                char lang[4] = {0};
                if (lookup(ff_p->raw.transport_generation, st->id, kind,
                           lang, sizeof(lang))) {
                    AVDictionaryEntry *prev = av_dict_get(
                        st->metadata, "language", NULL, 0);
                    if (!prev || !prev->value || !prev->value[0] ||
                        !strcmp(prev->value, "und")) {
                        av_dict_set(&st->metadata, "language", lang, 0);
                        ++restored;
                        serprintf("NOVA_ISO_TRACK_APPLIED_V1: stream=%u pid=0x%x kind=%d lang=%s action=restore\n",
                                  track, st->id, kind, lang);
                    } else {
                        ++existing;
                        serprintf("NOVA_ISO_TRACK_APPLIED_V1: stream=%u pid=0x%x kind=%d clpi=%s ffmpeg=%s action=preserve\n",
                                  track, st->id, kind, lang, prev->value);
                    }
                } else {
                    ++missing;
                    serprintf("NOVA_ISO_TRACK_APPLIED_V1: stream=%u pid=0x%x kind=%d action=missing\n",
                              track, st->id, kind);
                }
            }
        }
        serprintf("NOVA_ISO_TRACK_SUMMARY_V1: lookup=%d restored=%u preserved=%u missing=%u\n",
                  lookup != NULL, restored, existing, missing);
    }
''' + ANCHOR


def transform(src):
    if src.count(ANCHOR) != 1:
        raise RuntimeError("ISO metadata hook missing or ambiguous")
    if MARKER in src:
        raise RuntimeError("ISO metadata hook already applied")
    if "nova_transport_iso_track_language" in src:
        raise RuntimeError("unexpected existing metadata bridge")
    if "NOVA_ISO_INDEX_SEEK_V3" not in src or "NOVA_MKV_BBC_CUE_SEEK_V1" not in src:
        raise RuntimeError("pin checks: the 704 ISO/MKV seek chain is absent")
    if "raw.transport_handle" not in src and "raw->transport_handle" not in src:
        raise RuntimeError("direct transport handle is not present")
    return src.replace(ANCHOR, REPLACEMENT, 1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--native", type=Path, required=True)
    args = p.parse_args()
    path = args.native / "Source/stream_parser_ffmpeg.c"
    old = path.read_text(encoding="utf-8")
    new = transform(old)
    assert new.replace(REPLACEMENT, ANCHOR, 1) == old
    path.write_text(new, encoding="utf-8")
    print("NOVA_ISO_TRACK_LANG_V1=PATCHED")


if __name__ == "__main__":
    main()
