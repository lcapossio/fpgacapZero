#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Build (and optionally program) the PolarFire SoC Discovery Kit example.

Runs Libero SoC in batch mode.  The project, reports and logs land under
``examples/mpfs_disco_kit/libero/`` (git-ignored).

Usage
-----
    python examples/mpfs_disco_kit/build.py              # build, ~3 min
    python examples/mpfs_disco_kit/build.py --program    # build, then program
    python examples/mpfs_disco_kit/build.py --program-only
    python examples/mpfs_disco_kit/build.py --libero PATH/TO/libero

Libero is found from ``--libero``, then ``PATH``, then ``$LIBERO_DIR`` /
``$ACTEL_SW_DIR``, then the usual install roots.  Synthesis needs a Synplify
licence: if Libero's licence server is not on the first ``LM_LICENSE_FILE``
entry, set ``SNPSLMD_LICENSE_FILE`` (for example ``1702@localhost``).

Programming uses the first FlashPro Libero finds.  While another program holds
the FlashPro's JTAG channel (OpenOCD, a bit-bang bridge), Libero stops with
"No programmer is connected"; stop that program first.

Exit code 0 on success, non-zero otherwise.
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
BUILD_DIR = HERE / "libero"
PROJECT = BUILD_DIR / "mpfs_disco_kit_fcapz" / "mpfs_disco_kit_fcapz.prjx"
LIBERO_EXE = "libero.exe" if sys.platform == "win32" else "libero"


def find_libero(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_dir():
            path = path / LIBERO_EXE
        if path.is_file():
            return path.resolve()
        raise RuntimeError(f"--libero is not a Libero executable or folder: {explicit}")

    found = shutil.which(LIBERO_EXE)
    if found:
        return Path(found).resolve()

    roots = [os.environ.get(v) for v in ("LIBERO_DIR", "ACTEL_SW_DIR")]
    for root in filter(None, roots):
        for sub in ("Designer/bin", "bin", "Libero_SoC/Designer/bin"):
            cand = Path(root) / sub / LIBERO_EXE
            if cand.is_file():
                return cand.resolve()

    if sys.platform == "win32":
        patterns = [
            f"{d}:/Microchip/Libero_SoC*/Libero_SoC/Designer/bin/{LIBERO_EXE}"
            for d in "CDE"
        ]
    else:
        patterns = [
            f"{r}/Libero_SoC*/Libero_SoC/Designer/bin/{LIBERO_EXE}"
            for r in ("/usr/local/microchip", "/opt/microchip", str(Path.home() / "microchip"))
        ]
    hits = sorted((h for p in patterns for h in glob.glob(p)), reverse=True)
    if hits:
        return Path(hits[0]).resolve()
    raise RuntimeError(
        f"{LIBERO_EXE} not found; pass --libero or put Libero's Designer/bin on PATH"
    )


def run_libero(libero: Path, script: str, args: list[str], log_name: str) -> int:
    BUILD_DIR.mkdir(exist_ok=True)
    log = BUILD_DIR / log_name
    cmd = [
        str(libero),
        f"SCRIPT:{HERE / script}",
        "SCRIPT_ARGS:" + " ".join([ROOT.as_posix(), *args]),
        f"LOGFILE:{log}",
    ]
    print(f"[build.py] {script} (log: {log.relative_to(ROOT).as_posix()})", flush=True)
    rc = subprocess.run(cmd, cwd=HERE, check=False).returncode
    if rc != 0:
        print(f"[build.py] Libero exited with code {rc}; see {log}", file=sys.stderr)
    return rc


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--libero", default=None, help="Libero executable or its bin folder")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--program", action="store_true", help="program the board after building")
    group.add_argument(
        "--program-only", action="store_true", help="program the last build without rebuilding"
    )
    args = parser.parse_args()

    try:
        libero = find_libero(args.libero)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not args.program_only:
        rc = run_libero(libero, "build_mpfs_disco_kit.tcl", [], "build.log")
        if rc != 0:
            return rc

    if args.program or args.program_only:
        if not PROJECT.is_file():
            print(f"error: no project to program at {PROJECT}; build first", file=sys.stderr)
            return 2
        rc = run_libero(libero, "program_mpfs_disco_kit.tcl", [], "program.log")
        if rc != 0:
            return rc

    print("[build.py] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
