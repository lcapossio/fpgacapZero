#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Run Verilator lint checks for RTL issues that iverilog can miss.

The iverilog pass in sim/run_sim.py remains the broad elaboration and
simulation gate. This script adds Verilator's stricter procedural-driver
analysis, including MULTIDRIVEN warnings for one reg assigned by more than
one always block.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"
SIM = ROOT / "sim"


@dataclass(frozen=True)
class LintTarget:
    name: str
    top: str
    sources: tuple[Path, ...]


TARGETS = (
    LintTarget(
        name="fcapz_ela",
        top="fcapz_ela",
        sources=(
            RTL / "reset_sync.v",
            RTL / "dpram.v",
            RTL / "trig_compare.v",
            RTL / "fcapz_ela.v",
        ),
    ),
    LintTarget(
        name="fcapz_ela_gowin",
        top="fcapz_ela_gowin",
        sources=(
            SIM / "gw_jtag_stub.v",
            RTL / "reset_sync.v",
            RTL / "dpram.v",
            RTL / "trig_compare.v",
            RTL / "fcapz_ela.v",
            RTL / "jtag_reg_iface.v",
            RTL / "jtag_burst_read.v",
            RTL / "fcapz_eio.v",
            RTL / "fcapz_regbus_mux.v",
            RTL / "jtag_tap" / "jtag_tap_gowin.v",
            RTL / "fcapz_ela_gowin.v",
        ),
    ),
    LintTarget(
        name="fcapz_eio_gowin",
        top="fcapz_eio_gowin",
        sources=(
            SIM / "gw_jtag_stub.v",
            RTL / "reset_sync.v",
            RTL / "jtag_reg_iface.v",
            RTL / "fcapz_eio.v",
            RTL / "jtag_tap" / "jtag_tap_gowin.v",
            RTL / "fcapz_eio_gowin.v",
        ),
    ),
)

COMMON_FLAGS = (
    "--lint-only",
    "-Wall",
    "-Wno-DECLFILENAME",
    "-Wno-GENUNNAMED",
    "-Wno-UNUSEDSIGNAL",
    "-Wno-UNDRIVEN",
    "-Wno-WIDTHTRUNC",
    "-Wno-WIDTHEXPAND",
    "-Wno-UNSIGNED",
    "-Wno-BLKSEQ",
)


def run_cmd(cmd: list[str], label: str, *, expect_ok: bool = True) -> bool:
    print(f"[verilator] {label}: {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    output = result.stdout + result.stderr
    if output:
        print(output, end="" if output.endswith("\n") else "\n")

    ok = result.returncode == 0
    if ok != expect_ok:
        expectation = "succeed" if expect_ok else "fail"
        print(f"[verilator] FAILED: expected {label} to {expectation}")
        return False
    return True


def command_for(target: LintTarget) -> list[str]:
    return [
        "verilator",
        *COMMON_FLAGS,
        "-I" + str(RTL),
        "-I" + str(RTL / "jtag_tap"),
        "--top-module",
        target.top,
        *[str(src) for src in target.sources],
    ]


def run_lint() -> bool:
    ok = True
    for target in TARGETS:
        if not run_cmd(command_for(target), f"lint {target.name}"):
            ok = False
    return ok


def run_self_test() -> bool:
    bad = LintTarget(
        name="verilator_multidriven_bad",
        top="verilator_multidriven_bad",
        sources=(SIM / "verilator_multidriven_bad.v",),
    )
    cmd = command_for(bad)
    print(f"[verilator] self-test: {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    output = result.stdout + result.stderr
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    if result.returncode == 0 or "MULTIDRIVEN" not in output:
        print("[verilator] FAILED: self-test did not trip MULTIDRIVEN")
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="also prove Verilator fails an intentional MULTIDRIVEN fixture",
    )
    args = parser.parse_args()

    if shutil.which("verilator") is None:
        print("verilator not found on PATH", file=sys.stderr)
        sys.exit(127)

    ok = run_lint()
    if args.self_test:
        ok = run_self_test() and ok

    if not ok:
        sys.exit(1)
    suffix = " and MULTIDRIVEN self-test" if args.self_test else ""
    print(f"Verilator RTL lint passed for {len(TARGETS)} target(s){suffix}.")


if __name__ == "__main__":
    main()
