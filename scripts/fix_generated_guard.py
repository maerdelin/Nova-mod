#!/usr/bin/env python3
from pathlib import Path

def apply(root: Path) -> int:
    matches = list(root.glob("smali*/com/archos/filecorelibrary/NovaBufferGuard.smali"))
    if len(matches) != 1:
        raise RuntimeError(f"NovaBufferGuard: expected 1 generated file, got {len(matches)}")
    text = matches[0].read_text()
    obsolete = "->logState(IJJZ)V"
    if obsolete in text:
        raise RuntimeError("NovaBufferGuard still contains obsolete six-register STATE logger")
    if "->logState(IJZ)V" not in text:
        raise RuntimeError("NovaBufferGuard compact STATE logger is missing")
    return 0
