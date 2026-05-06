#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Launch a Vivado batch build of the Arty A7 mixed-language VHDL-core design."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from build import cleanup_orphans, find_vivado


ROOT = Path(__file__).resolve().parent.parent.parent
TCL_SCRIPT = ROOT / "examples" / "arty_a7" / "build_arty_vhdl.tcl"
BITFILE = ROOT / "examples" / "arty_a7" / "arty_a7_top_vhdl.bit"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vivado", default=None, help="Path to vivado executable")
    parser.add_argument(
        "--log-dir",
        default=str(ROOT / "vivado" / "logs"),
        help="Directory for vivado_vhdl_build.log and vivado_vhdl_build.jou",
    )
    args = parser.parse_args()

    vivado = find_vivado(args.vivado)
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    cleanup_orphans()

    log_file = log_dir / "vivado_vhdl_build.log"
    jou_file = log_dir / "vivado_vhdl_build.jou"

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
    print(f"[build_vhdl.py] vivado: {vivado}")
    print(f"[build_vhdl.py] log:    {log_file}")
    print(f"[build_vhdl.py] cwd:    {ROOT}")
    print(f"[build_vhdl.py] cmd:    {' '.join(cmd)}")

    env = os.environ.copy()
    result = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)
    if result.returncode != 0:
        print(
            f"[build_vhdl.py] vivado exited with code {result.returncode}; see {log_file}",
            file=sys.stderr,
        )
        return result.returncode

    if not BITFILE.is_file():
        print(
            f"[build_vhdl.py] build reported success but bitfile missing: {BITFILE}",
            file=sys.stderr,
        )
        return 4

    print(f"[build_vhdl.py] success: {BITFILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
