#!/usr/bin/env python3
from pathlib import Path

def apply(root: Path) -> int:
    matches = list(root.glob("smali*/com/archos/filecorelibrary/NovaBufferGuard.smali"))
    if len(matches) != 1:
        raise RuntimeError(f"NovaBufferGuard: expected 1 generated file, got {len(matches)}")
    path = matches[0]
    lines = path.read_text().splitlines()
    out = []
    removed = 0
    for line in lines:
        if "->logState(" in line and "invoke-static" in line:
            removed += 1
            continue
        out.append(line)
    if removed != 1:
        raise RuntimeError(f"NovaBufferGuard: expected to remove 1 diagnostic call, got {removed}")
    path.write_text("\n".join(out) + "\n")
    return removed
