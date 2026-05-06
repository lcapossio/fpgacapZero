#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Compile and run VHDL simulations with GHDL."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RTL_VHDL = ROOT / "rtl" / "vhdl"
TB_VHDL = ROOT / "tb" / "vhdl"
SIM = ROOT / "sim"
WORK = SIM / "ghdl"


TESTBENCHES = {
    "fcapz_eio": (
        "fcapz_eio_tb",
        [
            RTL_VHDL / "pkg" / "fcapz_pkg.vhd",
            RTL_VHDL / "core" / "fcapz_eio.vhd",
            TB_VHDL / "fcapz_eio_tb.vhd",
        ],
    ),
    "fcapz_ela": (
        "fcapz_ela_tb",
        [
            RTL_VHDL / "pkg" / "fcapz_pkg.vhd",
            RTL_VHDL / "pkg" / "fcapz_util_pkg.vhd",
            RTL_VHDL / "core" / "fcapz_dpram.vhd",
            RTL_VHDL / "core" / "fcapz_ela.vhd",
            TB_VHDL / "fcapz_ela_tb.vhd",
        ],
    ),
}

DEFAULT_TESTBENCHES = ["fcapz_eio", "fcapz_ela"]


def run_cmd(cmd: list[str], label: str) -> bool:
    print(f"[vhdl-sim] {label}: {' '.join(str(c) for c in cmd)}", flush=True)
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        print(f"[vhdl-sim] FAILED: {label}")
        return False
    return True


def clean_workdir() -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True, exist_ok=True)


def run_tb(name: str) -> bool:
    entity, sources = TESTBENCHES[name]

    for source in sources:
        if not run_cmd(
            ["ghdl", "-a", "--std=08", f"--workdir={WORK}", str(source)],
            f"analyze {source.relative_to(ROOT)}",
        ):
            return False

    if not run_cmd(["ghdl", "-e", "--std=08", f"--workdir={WORK}", entity], f"elaborate {entity}"):
        return False

    return run_cmd(["ghdl", "-r", "--std=08", f"--workdir={WORK}", entity], f"simulate {entity}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("testbench", nargs="*", help="VHDL testbench name(s) to run")
    args = parser.parse_args()

    if shutil.which("ghdl") is None:
        print("ghdl not found on PATH; install GHDL to run VHDL simulations")
        sys.exit(1)

    requested = args.testbench or DEFAULT_TESTBENCHES
    unknown = [name for name in requested if name not in TESTBENCHES]
    if unknown:
        print(f"Unknown VHDL testbench(es): {unknown}")
        print(f"Available: {list(TESTBENCHES)}")
        sys.exit(1)

    clean_workdir()
    failures = []
    for name in requested:
        print(f"\n{'=' * 60}")
        print(f" Running VHDL: {name}")
        print(f"{'=' * 60}")
        if not run_tb(name):
            failures.append(name)

    print(f"\n{'=' * 60}")
    if failures:
        print(f"FAILED: {failures}")
        sys.exit(1)
    print(f"All {len(requested)} VHDL testbench(es) passed.")


if __name__ == "__main__":
    main()
