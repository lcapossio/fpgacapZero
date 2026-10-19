#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
"""Launch a Vivado batch build of the Kria KV260 reference design.

    python examples/kv260/build.py
    python examples/kv260/build.py --vivado PATH/TO/vivado
    python examples/kv260/build.py --log-dir vivado/logs

The project is created under ``vivado/fpgacapZero_kv260/`` and the bitstream
is copied to ``examples/kv260/kv260_top.bit``.  The build fails if timing is
not met.  The full Vivado log is written to ``<log_dir>/vivado_kv260.log``.
Exit code 0 on success, non-zero otherwise.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TCL_SCRIPT = ROOT / "examples" / "kv260" / "build_kv260.tcl"
BITFILE = ROOT / "examples" / "kv260" / "kv260_top.bit"


def _arty_build_helpers():
    # Reuse the Arty launcher's Vivado lookup and orphan-helper cleanup.
    path = ROOT / "examples" / "arty_a7" / "build.py"
    spec = importlib.util.spec_from_file_location("_fcapz_arty_build", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--vivado", default=None, help="Path to vivado executable")
    parser.add_argument(
        "--log-dir",
        default=str(ROOT / "vivado" / "logs"),
        help="Directory for vivado_kv260.log and vivado_kv260.jou",
    )
    args = parser.parse_args()

    helpers = _arty_build_helpers()
    vivado = helpers.find_vivado(args.vivado)
    helpers.cleanup_orphans()

    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "vivado_kv260.log"
    jou_file = log_dir / "vivado_kv260.jou"

    cmd = [
        vivado,
        "-mode", "batch",
        "-source", str(TCL_SCRIPT),
        "-log", str(log_file),
        "-journal", str(jou_file),
    ]
    print(f"[build.py] vivado: {vivado}")
    print(f"[build.py] log:    {log_file}")
    try:
        result = subprocess.run(cmd, cwd=str(ROOT), check=False)
    except FileNotFoundError as exc:
        print(f"error: failed to launch vivado: {exc}", file=sys.stderr)
        return 2
    if result.returncode != 0:
        print(f"[build.py] vivado exited with {result.returncode}", file=sys.stderr)
        return result.returncode
    if not BITFILE.is_file():
        print(f"error: bitstream not produced: {BITFILE}", file=sys.stderr)
        return 1
    print(f"[build.py] bitstream: {BITFILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
