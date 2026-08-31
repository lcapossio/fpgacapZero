#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Launch a Vivado batch build of the Arty A7 VexRiscv design.

Before Vivado runs, this fetches the pinned VexRiscv core and compiles the
firmware into examples/arty_a7/vex/fw/fw.mem (loaded by vex_cpu.v via
$readmemh). Requires a RISC-V GCC toolchain on PATH (or $RISCV_PREFIX) and,
on the first run only, network access to fetch the core.

    RISCV_PREFIX=riscv64-unknown-elf- python examples/arty_a7/build_arty_vex.py
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
VEX_DIR = EXAMPLE_DIR / "vex"
TCL_SCRIPT = EXAMPLE_DIR / "build_arty_vex.tcl"
BITFILE = EXAMPLE_DIR / "arty_a7_vex_top.bit"


def _load(name: str, path: Path):
    """Import a module by file path (the vex helpers are not on sys.path)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_sources(out_dir: Path) -> None:
    """Fetch the VexRiscv core and build the firmware image (pre-Vivado)."""
    get_deps = _load("vex_get_deps", VEX_DIR / "get_deps.py")
    build_fw = _load("vex_build_fw", VEX_DIR / "fw" / "build_fw.py")
    get_deps.fetch_vexriscv()
    build_fw.build_firmware(out_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vivado", default=None, help="Path to vivado executable")
    parser.add_argument(
        "--log-dir",
        default=str(ROOT / "vivado" / "logs"),
        help="Directory for vivado_vex_build.log and vivado_vex_build.jou",
    )
    args = parser.parse_args()

    vivado = find_vivado(args.vivado)
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Fetch the core + build fw.mem before Vivado so $readmemh has an image.
    prepare_sources(log_dir)

    cleanup_orphans()

    log_file = log_dir / "vivado_vex_build.log"
    jou_file = log_dir / "vivado_vex_build.jou"

    cmd = [
        vivado, "-mode", "batch",
        "-source", str(TCL_SCRIPT),
        "-log", str(log_file),
        "-journal", str(jou_file),
    ]
    print(f"[build_arty_vex.py] vivado: {vivado}")
    print(f"[build_arty_vex.py] log:    {log_file}")
    print(f"[build_arty_vex.py] cwd:    {ROOT}")

    env = os.environ.copy()
    result = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)
    if result.returncode != 0:
        print(
            f"[build_arty_vex.py] vivado exited with code {result.returncode}; "
            f"see {log_file}",
            file=sys.stderr,
        )
        return result.returncode

    if not BITFILE.is_file():
        print(
            f"[build_arty_vex.py] build reported success but bitfile missing: {BITFILE}",
            file=sys.stderr,
        )
        return 4

    print(f"[build_arty_vex.py] success: {BITFILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
