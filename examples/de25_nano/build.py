#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Launch a Quartus batch build of the DE25-Nano reference design.

Usage
-----
    python examples/de25_nano/build.py
    python examples/de25_nano/build.py --variant manager
    python examples/de25_nano/build.py --quartus-sh PATH/TO/quartus_sh

The generated bitstream is written to:
    examples/de25_nano/output_files/de25_nano_fcapz.sof          (default)
    examples/de25_nano/output_files/de25_nano_manager_fcapz.sof  (--variant manager)

The ``manager`` variant puts two ELAs and two EIOs behind one core manager on
virtual JTAG instance 1 (de25_nano_manager_top.v).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE_DIR = ROOT / "examples" / "de25_nano"
VARIANTS = {
    "verilog": (EXAMPLE_DIR / "build_de25_nano.tcl", "de25_nano_fcapz.sof"),
    "manager": (EXAMPLE_DIR / "build_de25_nano_manager.tcl", "de25_nano_manager_fcapz.sof"),
}


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
    parser.add_argument(
        "--variant", choices=sorted(VARIANTS), default="verilog",
        help="Top-level to build (default: verilog)",
    )
    args = parser.parse_args()

    build_script, bitname = VARIANTS[args.variant]
    bitfile = EXAMPLE_DIR / "output_files" / bitname
    quartus_sh = find_quartus_sh(args.quartus_sh)
    cmd = [quartus_sh, "-t", str(build_script), str(ROOT)]
    print(f"[build.py] quartus_sh: {quartus_sh}")
    print(f"[build.py] cwd:        {ROOT}")
    print(f"[build.py] cmd:        {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=str(ROOT), check=False)
    if result.returncode != 0:
        print(f"[build.py] quartus_sh exited with code {result.returncode}", file=sys.stderr)
        return result.returncode
    if not bitfile.is_file():
        print(f"[build.py] build reported success but bitfile missing: {bitfile}", file=sys.stderr)
        return 4
    print(f"[build.py] success: {bitfile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
