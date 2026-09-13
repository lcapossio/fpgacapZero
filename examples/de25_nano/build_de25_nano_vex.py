#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Launch a Quartus batch build of the DE25-Nano VexRiscv design.

Before Quartus runs, this fetches the pinned VexRiscv core and compiles the
firmware into examples/de25_nano/vex/fw/fw.mem (loaded by vex_cpu.v via
$readmemh). Requires a RISC-V GCC toolchain on PATH (or $RISCV_PREFIX) and,
on the first run only, network access to fetch the core.

Usage
-----
    RISCV_PREFIX=riscv64-unknown-elf- python examples/de25_nano/build_de25_nano_vex.py
    python examples/de25_nano/build_de25_nano_vex.py --quartus-sh PATH/TO/quartus_sh

The generated bitstream is written to:
    examples/de25_nano/output_files/de25_nano_vex_fcapz.sof
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE_DIR = ROOT / "examples" / "de25_nano"
VEX_DIR = EXAMPLE_DIR / "vex"
BUILD_SCRIPT = EXAMPLE_DIR / "build_de25_nano_vex.tcl"
BITFILE = EXAMPLE_DIR / "output_files" / "de25_nano_vex_fcapz.sof"


def _load(name: str, path: Path):
    """Import a module by file path (the vex helpers are not on sys.path)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_sources() -> None:
    """Fetch the VexRiscv core and build the firmware image (pre-Quartus)."""
    get_deps = _load("vex_get_deps", VEX_DIR / "get_deps.py")
    build_fw = _load("vex_build_fw", VEX_DIR / "fw" / "build_fw.py")
    get_deps.fetch_vexriscv()
    build_fw.build_firmware()


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

    # Fetch the core + build fw.mem before Quartus so $readmemh has an image.
    prepare_sources()

    quartus_sh = find_quartus_sh(args.quartus_sh)
    cmd = [quartus_sh, "-t", str(BUILD_SCRIPT), str(ROOT)]
    print(f"[build_de25_nano_vex.py] quartus_sh: {quartus_sh}")
    print(f"[build_de25_nano_vex.py] cwd:        {ROOT}")
    print(f"[build_de25_nano_vex.py] cmd:        {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=str(ROOT), check=False)
    if result.returncode != 0:
        print(f"[build_de25_nano_vex.py] quartus_sh exited with code {result.returncode}",
              file=sys.stderr)
        return result.returncode
    if not BITFILE.is_file():
        print(f"[build_de25_nano_vex.py] build reported success but bitfile missing: {BITFILE}",
              file=sys.stderr)
        return 4
    print(f"[build_de25_nano_vex.py] success: {BITFILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
