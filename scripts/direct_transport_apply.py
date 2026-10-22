# direct transport APK integration

from __future__ import annotations
import argparse, re, shutil, subprocess
from pathlib import Path

METHOD_RE = re.compile(r'^\.method [^\n]+\n.*?^\.end method', re.M | re.S)
AWAIT_RE = re.compile(
    r'^(?P<indent>\s*)invoke-static(?:/range)? \{(?P<regs>[^}]+)\}, '
    r'Lcom/archos/filecorelibrary/NetworkInitialization;->awaitReadyForSmb'
    r'\(Landroid/net/Uri;Landroid/content/Context;\)V\s*$',
    re.M,
)

def one(paths, label):
    xs=list(paths)
    if len(xs)!=1:
        raise RuntimeError(f"{label}: expected one, got {len(xs)}")
    return xs[0]

def run(*args):
    subprocess.run([str(x) for x in args], check=True)

def next_smali(root):
    nums=[1]
    for p in root.glob("smali_classes*"):
        try:
            nums.append(int(p.name.replace("smali_classes","")))
        except ValueError:
            pass
    return root/f"smali_classes{max(nums)+1}"
