#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Compile and run RTL simulations with iverilog + vvp.

Usage:
    python sim/run_sim.py            # run all testbenches
    python sim/run_sim.py fcapz_ela   # run specific testbench
    python sim/run_sim.py fcapz_eio
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RTL  = ROOT / "rtl"
TB   = ROOT / "tb"
SIM  = ROOT / "sim"

# Each entry: (tb_file, [rtl_sources])
TESTBENCHES = {
    "fcapz_ela": (
        TB / "fcapz_ela_tb.sv",
        [
            RTL / "fcapz_ela.v",
            RTL / "dpram.v",
            RTL / "trig_compare.v",
        ],
    ),
    "fcapz_eio": (
        TB / "fcapz_eio_tb.sv",
        [
            RTL / "fcapz_eio.v",
        ],
    ),
    "chan_mux": (
        TB / "chan_mux_tb.sv",
        [
            RTL / "fcapz_ela.v",
            RTL / "dpram.v",
            RTL / "trig_compare.v",
        ],
    ),
}


def run_cmd(cmd: list[str], label: str) -> bool:
    """Run a command, return True on success."""
    print(f"[sim] {label}: {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        print(f"[sim] FAILED: {label}")
        return False
    return True


def run_tb(name: str) -> bool:
    tb_file, rtl_sources = TESTBENCHES[name]
    out_vvp = SIM / f"{name}_tb.vvp"

    ok = run_cmd(
        ["iverilog", "-g2012", "-Wall",
         "-o", str(out_vvp),
         str(tb_file), *[str(s) for s in rtl_sources]],
        f"compile {name}",
    )
    if not ok:
        return False

    return run_cmd(["vvp", str(out_vvp)], f"simulate {name}")


def main() -> None:
    SIM.mkdir(parents=True, exist_ok=True)

    requested = sys.argv[1:]
    if requested:
        unknown = [n for n in requested if n not in TESTBENCHES]
        if unknown:
            print(f"Unknown testbench(es): {unknown}")
            print(f"Available: {list(TESTBENCHES)}")
            sys.exit(1)
        targets = requested
    else:
        targets = list(TESTBENCHES)

    failures = []
    for name in targets:
        print(f"\n{'='*60}")
        print(f" Running: {name}_tb")
        print(f"{'='*60}")
        if not run_tb(name):
            failures.append(name)

    print(f"\n{'='*60}")
    if failures:
        print(f"FAILED: {failures}")
        sys.exit(1)
    else:
        print(f"All {len(targets)} testbench(es) passed.")


if __name__ == "__main__":
    main()
