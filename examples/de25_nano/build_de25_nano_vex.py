#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Launch a Quartus batch build of the DE25-Nano VexRiscv design.

Before Quartus runs, this verifies the vendored VexRiscv core (checked in under
third_party/vexriscv/, no network needed) and compiles the firmware into
examples/de25_nano/vex/fw/fw.mem (loaded by vex_cpu.v via $readmemh). Requires a
RISC-V GCC toolchain on PATH (or $RISCV_PREFIX).

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
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE_DIR = ROOT / "examples" / "de25_nano"
VEX_DIR = EXAMPLE_DIR / "vex"                       # board-local: main.c
COMMON_VEX = ROOT / "examples" / "common" / "vexriscv"  # shared CPU subsystem
BUILD_SCRIPT = EXAMPLE_DIR / "build_de25_nano_vex.tcl"
BITFILE = EXAMPLE_DIR / "output_files" / "de25_nano_vex_fcapz.sof"
DEBUG_BITFILE = EXAMPLE_DIR / "output_files" / "de25_nano_vex_debug_fcapz.sof"


def _load(name: str, path: Path):
    """Import a module by file path (the vex helpers are not on sys.path)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_sources(debug: bool = False) -> None:
    """Verify the vendored VexRiscv core and build the firmware (pre-Quartus)."""
    get_deps = _load("vex_get_deps", COMMON_VEX / "get_deps.py")
    build_fw = _load("vex_build_fw", COMMON_VEX / "fw" / "build_fw.py")
    if debug:
        get_deps.fetch_vexriscv_debug()
    else:
        get_deps.fetch_vexriscv()
    build_fw.build_firmware(VEX_DIR / "fw")


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
        "--debug",
        action="store_true",
        help="Build the CPU-debug variant (VexRiscv_EmbeddedJtag + sld_virtual_jtag "
        "index-6 tunnel, DEBUG_EN=1) -> de25_nano_vex_debug_fcapz.sof",
    )
    args = parser.parse_args()
    bitfile = DEBUG_BITFILE if args.debug else BITFILE

    # Fetch the core + build fw.mem before Quartus so $readmemh has an image.
    prepare_sources(debug=args.debug)

    quartus_sh = find_quartus_sh(args.quartus_sh)
    env = os.environ.copy()
    if args.debug:
        env["FCAPZ_VEX_DEBUG"] = "1"
    cmd = [quartus_sh, "-t", str(BUILD_SCRIPT), str(ROOT)]
    print(f"[build_de25_nano_vex.py] variant:    {'debug' if args.debug else 'default'}")
    print(f"[build_de25_nano_vex.py] quartus_sh: {quartus_sh}")
    print(f"[build_de25_nano_vex.py] cwd:        {ROOT}")
    print(f"[build_de25_nano_vex.py] cmd:        {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=str(ROOT), check=False, env=env)
    if result.returncode != 0:
        print(f"[build_de25_nano_vex.py] quartus_sh exited with code {result.returncode}",
              file=sys.stderr)
        return result.returncode
    if not bitfile.is_file():
        print(f"[build_de25_nano_vex.py] build reported success but bitfile missing: {bitfile}",
              file=sys.stderr)
        return 4
    print(f"[build_de25_nano_vex.py] success: {bitfile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
