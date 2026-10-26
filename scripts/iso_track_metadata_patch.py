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
        /* NOVA_ISO_CODEC_AUDIT_V2: read-only comparison of the two
         * independent codec sources. Do not infer Atmos from TrueHD alone. */
        typedef int (*nova_iso_codec_fn)(uint64_t,int,int);
        nova_iso_codec_fn bd_codec = (nova_iso_codec_fn)dlsym(
            ff_p->raw.transport_handle, "nova_transport_iso_track_codec");
        unsigned restored = 0, existing = 0, missing = 0;
        if (lookup) {
            for (unsigned track = 0; track < ff_p->fmt->nb_streams; ++track) {
                AVStream *st = ff_p->fmt->streams[track];
                if (!st || !st->codecpar) continue;
                int kind = st->codecpar->codec_type == AVMEDIA_TYPE_AUDIO ? 1 :
                    (st->codecpar->codec_type == AVMEDIA_TYPE_SUBTITLE ? 2 : 0);
                if (!kind) continue;
                if (kind == 1) {
                    int bd = bd_codec ? bd_codec(
                        ff_p->raw.transport_generation, st->id, kind) : -1;
                    int ff_id = st->codecpar->codec_id;
                    int profile = st->codecpar->profile;
                    int match = -1;
                    switch(bd) {
                    case 0x81: match = ff_id == AV_CODEC_ID_AC3; break;
                    case 0x82:
                    case 0x85:
                    case 0x86: match = ff_id == AV_CODEC_ID_DTS; break;
                    case 0x83: match = ff_id == AV_CODEC_ID_TRUEHD; break;
                    case 0x84: match = ff_id == AV_CODEC_ID_EAC3; break;
                    }
                    const AVCodecDescriptor *desc =
                        avcodec_descriptor_get(ff_id);
                    int atmos_confirmed =
                        ff_id == AV_CODEC_ID_TRUEHD &&
                        profile == AV_PROFILE_TRUEHD_ATMOS;
                    /* Hint to _parse_format only when Blu-ray and FFmpeg agree.
                     * BD 0x86 => DTS-HD MA, 0x85 => DTS-HD HRA.
                     * TrueHD alone never grants the Atmos label. */
                    if (match == 1 && (bd == 0x85 || bd == 0x86)) {
                        av_dict_set(&st->metadata, "nova_iso_codec_type",
                                    bd == 0x86 ? "dts_hd_ma" : "dts_hd",
                                    0);
                    }
                    if (match == 1 && atmos_confirmed)
                        av_dict_set(&st->metadata, "nova_iso_atmos", "truehd", 0);

                    serprintf("NOVA_ISO_CODEC_AUDIT_V2: track=%u pid=0x%x bd=0x%x ff=%s profile=%d match=%d truehd_atmos=%d\n",
                        track, st->id, bd, desc ? desc->name : "unknown",
                        profile, match, atmos_confirmed);
                    if (match == 0)
                        serprintf("NOVA_ISO_CODEC_MISMATCH_V2: track=%u pid=0x%x bd=0x%x ff=%s\n",
                            track, st->id, bd, desc ? desc->name : "unknown");
                }
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
    # Applied only to FFmpeg stream tracks whose metadata is stamped above.
    # This is the regular AVOS codec enum, not a cosmetic menu-only renaming.
    audio_anchor = "audio->stream        = i;"
    audio_replacement = r'''/* NOVA_ISO_CODEC_LABEL_V2: only validated ISO PID metadata is
                 * allowed to refine FFmpeg DTS core -> Blu-ray DTS-HD type.
                 * Existing MKV/MP4/ISO seek, codec and buffer paths unchanged. */
                AVDictionaryEntry *nova_bd_codec = av_dict_get(
                    st->metadata, "nova_iso_codec_type", NULL, 0);
                if (codecpar->codec_id == AV_CODEC_ID_DTS && nova_bd_codec) {
                    if (!strcmp(nova_bd_codec->value, "dts_hd_ma"))
                        audio->format = WAVE_FORMAT_DTS_HD_MA;
                    else if (!strcmp(nova_bd_codec->value, "dts_hd"))
                        audio->format = WAVE_FORMAT_DTS_HD;
                    serprintf("NOVA_ISO_CODEC_LABEL_V2: stream=%d pid=0x%x format=0x%x tag=%s\n",
                              i, st->id, audio->format, nova_bd_codec->value);
                }
                /* Atmos is not a separate base codec. Preserve TrueHD codec;
                 * advertise only an FFmpeg-confirmed Atmos profile via name. */
                AVDictionaryEntry *nova_atmos = av_dict_get(
                    st->metadata, "nova_iso_atmos", NULL, 0);
                if (codecpar->codec_id == AV_CODEC_ID_TRUEHD && nova_atmos &&
                    (!title || !title->value || !title->value[0])) {
                    strnZcpy(audio->name, "Dolby Atmos", AV_NAME_LEN);
                    serprintf("NOVA_ISO_TRUEHD_ATMOS_V2: stream=%d pid=0x%x confirmed=1\n",
                              i, st->id);
                }
                ''' + audio_anchor
    if src.count(audio_anchor) != 1:
        raise RuntimeError("ISO codec audio format hook missing or ambiguous")
    src = src.replace(audio_anchor, audio_replacement, 1)
    return src.replace(ANCHOR, REPLACEMENT, 1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--native", type=Path, required=True)
    args = p.parse_args()
    path = args.native / "Source/stream_parser_ffmpeg.c"
    old = path.read_text(encoding="utf-8")
    new = transform(old)
    assert new.count("NOVA_ISO_CODEC_LABEL_V2") == 1
    assert new.count("NOVA_ISO_TRACK_APPLIED_V1") >= 2
    path.write_text(new, encoding="utf-8")
    print("NOVA_ISO_TRACK_LANG_V1=PATCHED")


if __name__ == "__main__":
    main()
