#!/usr/bin/env python3
"""NOVA 1119: preserve exact 64-bit file size after a video gains resume metadata.

This operates on the *actual decoded* latest official APK after v982's three
file-size UI binders are installed. It changes only:
  1) plain Video's DB cursor size read from getInt -> getLong;
  2) TV card's NonIndexedVideo-only restriction to include ordinary indexed Video.
Movie/Episode size reads already use getLong and their descriptive card text
is intentionally left intact. Seek, transport and progress bars are untouched.
"""
from pathlib import Path
import json

TAG = "NOVA_1119_RESUME_SIZE_64BIT_V1"
ROOT = "com/archos/mediacenter/video"
MAPPER = f"L{ROOT}/browser/adapters/mappers/VideoCursorMapper;"
VIDEO = f"L{ROOT}/browser/adapters/object/Video;"
NONINDEXED = f"L{ROOT}/browser/adapters/object/NonIndexedVideo;"
MOVIE = f"L{ROOT}/browser/adapters/object/Movie;"
EPISODE = f"L{ROOT}/browser/adapters/object/Episode;"
CARD_SKIP = ":nova_a18b0441c7_24"


def exactly_one(root: Path, subpath: str) -> Path:
    matches = list(root.glob(f"smali*/{subpath}"))
    if len(matches) != 1:
        raise RuntimeError(f"{TAG}: expected exactly one {subpath}, found {len(matches)}")
    return matches[0]


def following_statements(lines: list[str], start: int, max_span: int = 14) -> list[int]:
    return [i for i in range(start + 1, min(len(lines), start + max_span))
            if lines[i].strip() and not lines[i].lstrip().startswith("#")]


def repair_plain_video_cursor(src: str) -> str:
    """Fix the sole generic Video constructor, not unrelated integer columns."""
    if TAG in src:
        raise RuntimeError(f"{TAG}: mapper already patched")
    lines = src.splitlines(keepends=True)
    matches = []
    for i, line in enumerate(lines):
        if line.strip() != f"iget v0, v0, {MAPPER}->mSizeColumn:I":
            continue
        near = following_statements(lines, i)
        expected = [
            "invoke-interface {v1, v0}, Landroid/database/Cursor;->getInt(I)I",
            "move-result v0",
            "int-to-long v0, v0",
            "move-wide/from16 v20, v0",
        ]
        if [lines[j].strip() for j in near[:4]] == expected:
            matches.append(near)
    if len(matches) != 1:
        raise RuntimeError(f"{TAG}: generic Video Cursor.getInt size sequence ambiguous: {len(matches)}")
    indexes = matches[0]
    lines[indexes[0]] = lines[indexes[0]].replace("->getInt(I)I", "->getLong(I)J")
    lines[indexes[1]] = lines[indexes[1]].replace("move-result v0", "move-result-wide v0")
    # Remove the old sign extension, which would truncate the now 64-bit result.
    lines[indexes[2]] = f"    # {TAG}: exact cursor long, no int-to-long truncation\n"
    result = "".join(lines)
    if result.count(f"iget v0, v0, {MAPPER}->mSizeColumn:I") != 2:
        # Original method has exactly the Episode + ordinary Video v0 reads.
        raise RuntimeError(f"{TAG}: mapper 6.6.2 constructor topology changed")
    if result.count(f"{TAG}: exact cursor long") != 1:
        raise RuntimeError(f"{TAG}: patch marker missing")
    return result


def repair_tv_card_type_guard(src: str) -> str:
    """Include ordinary indexed Video; keep Movie/Episode descriptive text."""
    if TAG in src:
        raise RuntimeError(f"{TAG}: card already patched")
    lines = src.splitlines(keepends=True)
    found = []
    for i, line in enumerate(lines):
        if line.strip() != f"instance-of v3, p2, {NONINDEXED}":
            continue
        next_stmts = following_statements(lines, i, max_span=6)
        if next_stmts and lines[next_stmts[0]].strip() == f"if-eqz v3, {CARD_SKIP}":
            found.append((i, next_stmts[0]))
    if len(found) != 1:
        raise RuntimeError(f"{TAG}: TV card type gate ambiguous: {len(found)}")
    i, j = found[0]
    lines[i] = (
        f"    # {TAG}: show size for ordinary indexed and non-indexed files.\n"
        f"    # Preserve scraped movie and episode description text.\n"
        f"    instance-of v3, p2, {MOVIE}\n"
        f"    if-nez v3, {CARD_SKIP}\n"
        f"    instance-of v3, p2, {EPISODE}\n"
    )
    lines[j] = f"    if-nez v3, {CARD_SKIP}\n"
    result = "".join(lines)
    if f"instance-of v3, p2, {NONINDEXED}" in result:
        raise RuntimeError(f"{TAG}: restrictive class check remains")
    return result


def verify_three_ui_binders(root: Path) -> dict:
    entries = {
        "phone_tablet_list": "browser/presenter/VideoListPresenter.smali",
        "tv_poster_card": "leanback/presenter/PosterImageCardPresenter.smali",
        "tv_horizontal_list": "leanback/presenter/VideoListPresenter.smali",
    }
    counts = {}
    for key, path in entries.items():
        content = exactly_one(root, f"{ROOT}/{path}").read_text(encoding="utf-8")
        pattern = f"{VIDEO}->getSize()J"
        n = content.count(pattern)
        if n != 1 or "Landroid/text/format/Formatter;->formatFileSize" not in content:
            raise RuntimeError(f"{TAG}: {key} size path changed: {n} binds")
        counts[key] = n
    return counts


def patch(root: Path, report: Path | None = None) -> dict:
    mapper = exactly_one(root, f"{ROOT}/browser/adapters/mappers/VideoCursorMapper.smali")
    card = exactly_one(root, f"{ROOT}/leanback/presenter/PosterImageCardPresenter.smali")
    original_mapper = mapper.read_text(encoding="utf-8")
    original_card = card.read_text(encoding="utf-8")
    edited_mapper = repair_plain_video_cursor(original_mapper)
    edited_card = repair_tv_card_type_guard(original_card)
    verified = verify_three_ui_binders(root)
    # Commit both decoded files only if all original signatures and all 3
    # previously installed UI binders have been verified.
    mapper.write_text(edited_mapper, encoding="utf-8")
    card.write_text(edited_card, encoding="utf-8")
    result = {
        "status": "PASS",
        "tag": TAG,
        "root_cause": "plain Video Cursor.getInt(size) sign-extended to long for files >=2 GiB",
        "fixed_source": "plain Video now Cursor.getLong(size) + move-result-wide",
        "tv_card": "ordinary indexed Video included; Movie/Episode description preserved",
        "three_size_binders": verified,
        "native_transport_changed": False,
        "playback_seek_changed": False,
        "progress_bar_changed": False,
    }
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(TAG + "=PASS")
    return result


if __name__ == "__main__":
    import argparse
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("--decoded", type=Path, required=True)
    arg.add_argument("--report", type=Path)
    args = arg.parse_args()
    patch(args.decoded, args.report)
