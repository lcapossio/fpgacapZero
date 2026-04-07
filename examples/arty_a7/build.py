#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Launch a Vivado batch build of the Arty A7 reference design.

This is the only supported entry point for building the bitstream — it does
not invoke any shell primitive (no ``rm``) and relies on Vivado's own
``-force`` flag to recreate the project directory.  All build artefacts land
under ``vivado/fpgacapZero_arty/`` and ``examples/arty_a7/arty_a7_top.bit``.

Usage
-----
    python examples/arty_a7/build.py              # default, ~10-15 min
    python examples/arty_a7/build.py --vivado PATH/TO/vivado
    python examples/arty_a7/build.py --log-dir no_commit

Exit code 0 on success, non-zero otherwise.  The full Vivado log is written
to ``<log_dir>/vivado_build.log`` and the journal to
``<log_dir>/vivado_build.jou``.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TCL_SCRIPT = ROOT / "examples" / "arty_a7" / "build_arty.tcl"
BITFILE = ROOT / "examples" / "arty_a7" / "arty_a7_top.bit"


def find_vivado(explicit: str | None) -> str:
    if explicit:
        return explicit
    found = shutil.which("vivado")
    if not found:
        raise RuntimeError(
            "vivado not on PATH; pass --vivado or source Vivado's settings script"
        )
    return found


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--vivado", default=None, help="Path to vivado executable")
    parser.add_argument(
        "--log-dir",
        default=str(ROOT / "no_commit"),
        help="Directory for vivado_build.log and vivado_build.jou",
    )
    args = parser.parse_args()

    vivado = find_vivado(args.vivado)
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "vivado_build.log"
    jou_file = log_dir / "vivado_build.jou"

    if not TCL_SCRIPT.is_file():
        print(f"error: tcl script not found: {TCL_SCRIPT}", file=sys.stderr)
        return 2

    cmd = [
        vivado,
        "-mode", "batch",
        "-source", str(TCL_SCRIPT),
        "-log", str(log_file),
        "-journal", str(jou_file),
    ]
    print(f"[build.py] vivado: {vivado}")
    print(f"[build.py] log:    {log_file}")
    print(f"[build.py] cwd:    {ROOT}")
    print(f"[build.py] cmd:    {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, cwd=str(ROOT), check=False)
    except FileNotFoundError as exc:
        print(f"error: failed to launch vivado: {exc}", file=sys.stderr)
        return 3

    if result.returncode != 0:
        print(
            f"[build.py] vivado exited with code {result.returncode}; "
            f"see {log_file}",
            file=sys.stderr,
        )
        return result.returncode

    if not BITFILE.is_file():
        print(
            f"[build.py] build reported success but bitfile missing: {BITFILE}",
            file=sys.stderr,
        )
        return 4

    print(f"[build.py] success: {BITFILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
