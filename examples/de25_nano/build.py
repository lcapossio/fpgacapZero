#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Launch a Quartus batch build of the DE25-Nano reference design.

Usage
-----
    python examples/de25_nano/build.py
    python examples/de25_nano/build.py --quartus-sh PATH/TO/quartus_sh

The generated bitstream is written to:
    examples/de25_nano/output_files/de25_nano_fcapz.sof
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE_DIR = ROOT / "examples" / "de25_nano"
BUILD_SCRIPT = EXAMPLE_DIR / "build_de25_nano.tcl"
BITFILE = EXAMPLE_DIR / "output_files" / "de25_nano_fcapz.sof"


def find_quartus_sh(explicit: str | None) -> str:
    if explicit:
        return explicit
    found = shutil.which("quartus_sh") or shutil.which("quartus_sh.exe")
    if not found:
        raise RuntimeError("quartus_sh not on PATH; pass --quartus-sh")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--quartus-sh", default=None, help="Path to quartus_sh executable")
    args = parser.parse_args()

    quartus_sh = find_quartus_sh(args.quartus_sh)
    cmd = [quartus_sh, "-t", str(BUILD_SCRIPT), str(ROOT)]
    print(f"[build.py] quartus_sh: {quartus_sh}")
    print(f"[build.py] cwd:        {ROOT}")
    print(f"[build.py] cmd:        {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=str(ROOT), check=False)
    if result.returncode != 0:
        print(f"[build.py] quartus_sh exited with code {result.returncode}", file=sys.stderr)
        return result.returncode
    if not BITFILE.is_file():
        print(f"[build.py] build reported success but bitfile missing: {BITFILE}", file=sys.stderr)
        return 4
    print(f"[build.py] success: {BITFILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
