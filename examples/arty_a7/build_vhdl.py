#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Launch a Vivado batch build of the Arty A7 mixed-language VHDL-core design.

The VHDL top now instantiates the open-source VexRiscv shared-bus subsystem
(Verilog) where the MicroBlaze wrapper used to sit, so -- like build_arty_vex.py
-- this verifies the vendored core and builds the firmware image (vex/fw/fw.mem,
$readmemh into the CPU BRAM) before Vivado. Needs a RISC-V GCC toolchain on PATH
(or $RISCV_PREFIX).

    RISCV_PREFIX=riscv64-unknown-elf- python examples/arty_a7/build_vhdl.py
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from build import cleanup_orphans, find_vivado


ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE_DIR = ROOT / "examples" / "arty_a7"
VEX_DIR = EXAMPLE_DIR / "vex"                       # board-local: main.c, vex_sys.v
COMMON_VEX = ROOT / "examples" / "common" / "vexriscv"  # shared CPU subsystem
TCL_SCRIPT = EXAMPLE_DIR / "build_arty_vhdl.tcl"
BITFILE = EXAMPLE_DIR / "arty_a7_top_vhdl.bit"
DEBUG_BITFILE = EXAMPLE_DIR / "arty_a7_top_vhdl_debug.bit"


def _load(name: str, path: Path):
    """Import a module by file path (the vex helpers are not on sys.path)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_sources(out_dir: Path, debug: bool = False) -> None:
    """Verify the vendored VexRiscv core and build the firmware (pre-Vivado)."""
    get_deps = _load("vex_get_deps", COMMON_VEX / "get_deps.py")
    build_fw = _load("vex_build_fw", COMMON_VEX / "fw" / "build_fw.py")
    if debug:
        get_deps.fetch_vexriscv_debug()
    else:
        get_deps.fetch_vexriscv()
    build_fw.build_firmware(VEX_DIR / "fw", out_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vivado", default=None, help="Path to vivado executable")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Build the mixed-language CPU-debug variant (DEBUG_EN=1) -> "
        "arty_a7_top_vhdl_debug.bit",
    )
    parser.add_argument(
        "--log-dir",
        default=str(ROOT / "vivado" / "logs"),
        help="Directory for vivado_vhdl_build.log and vivado_vhdl_build.jou",
    )
    args = parser.parse_args()

    vivado = find_vivado(args.vivado)
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    bitfile = DEBUG_BITFILE if args.debug else BITFILE

    # Fetch the core + build fw.mem before Vivado so $readmemh has an image.
    prepare_sources(log_dir, debug=args.debug)

    cleanup_orphans()

    tag = "vhdl_debug" if args.debug else "vhdl"
    log_file = log_dir / f"vivado_{tag}_build.log"
    jou_file = log_dir / f"vivado_{tag}_build.jou"

    cmd = [
        vivado,
        "-mode",
        "batch",
        "-source",
        str(TCL_SCRIPT),
        "-log",
        str(log_file),
        "-journal",
        str(jou_file),
    ]
    print(f"[build_vhdl.py] variant: {'debug' if args.debug else 'default'}")
    print(f"[build_vhdl.py] vivado: {vivado}")
    print(f"[build_vhdl.py] log:    {log_file}")
    print(f"[build_vhdl.py] cwd:    {ROOT}")
    print(f"[build_vhdl.py] cmd:    {' '.join(cmd)}")

    env = os.environ.copy()
    if args.debug:
        env["FCAPZ_VEX_DEBUG"] = "1"
    result = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)
    if result.returncode != 0:
        print(
            f"[build_vhdl.py] vivado exited with code {result.returncode}; see {log_file}",
            file=sys.stderr,
        )
        return result.returncode

    if not bitfile.is_file():
        print(
            f"[build_vhdl.py] build reported success but bitfile missing: {bitfile}",
            file=sys.stderr,
        )
        return 4

    print(f"[build_vhdl.py] success: {bitfile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
