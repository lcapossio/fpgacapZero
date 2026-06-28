#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Run the cocotb bench for fcapz_axi_mon (AXI monitor, P1)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from _runner_utils import check_results, relaunch_in_wsl, running_in_wsl

ROOT = Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"
TB_COCOTB = ROOT / "tb" / "cocotb"
BUILD_ROOT = ROOT / "build" / "cocotb_axi_mon"

VERILOG_SOURCES = [
    RTL / "reset_sync.v",
    RTL / "dpram.v",
    RTL / "trig_compare.v",
    RTL / "fcapz_ela.v",
    RTL / "fcapz_axi_mon.v",
]

# AXI4-Lite 32/32 -> SAMPLE_W 152. Small depth, no pipe/timestamps to keep the
# bench's register-window readback simple and deterministic.
PARAMETERS = {
    # PROTO is a string parameter (defaults to "AXI4LITE" in the module); it
    # can't be set via an iverilog command-line defparam, so leave it default.
    "ADDR_W": 32,
    "DATA_W": 32,
    "DEPTH": 16,
    "TRIG_STAGES": 1,
    "STOR_QUAL": 0,
    "NUM_SEGMENTS": 1,
    "TIMESTAMP_W": 0,
    "INPUT_PIPE": 0,
    "DECIM_EN": 0,
    "EXT_TRIG_EN": 0,
    "REL_COMPARE": 0,
    "DUAL_COMPARE": 1,
    "USER1_DATA_EN": 1,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sim", default="icarus")
    parser.add_argument("--runner", choices=("auto", "native", "wsl"), default="auto")
    parser.add_argument("--testcase", action="append", default=[])
    parser.add_argument("--waves", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if os.name == "nt" and not running_in_wsl() and args.runner in ("auto", "wsl"):
        raise SystemExit(relaunch_in_wsl(ROOT, sys.argv))

    try:
        from cocotb_tools.runner import get_runner  # cocotb >= 2.0
    except ModuleNotFoundError:
        try:
            from cocotb.runner import get_runner  # cocotb 1.x
        except ModuleNotFoundError as exc:
            raise SystemExit("cocotb is not installed in this Python environment") from exc

    if str(TB_COCOTB) not in sys.path:
        sys.path.insert(0, str(TB_COCOTB))

    runner = get_runner(args.sim)
    build_dir = BUILD_ROOT / args.sim
    results_xml = build_dir / "results.xml"

    runner.build(
        verilog_sources=VERILOG_SOURCES,
        includes=[RTL],
        parameters=PARAMETERS,
        hdl_toplevel="fcapz_axi_mon",
        build_dir=build_dir,
        clean=args.clean,
        always=True,
        waves=args.waves,
        verbose=args.verbose,
        timescale=("1ns", "1ps"),
        build_args=["-Wall"],
    )
    runner.test(
        test_module="axi_mon_test",
        hdl_toplevel="fcapz_axi_mon",
        hdl_toplevel_lang="verilog",
        testcase=tuple(args.testcase) if args.testcase else (),
        build_dir=build_dir,
        test_dir=TB_COCOTB,
        results_xml=results_xml,
        waves=args.waves,
        verbose=args.verbose,
        extra_env={"COCOTB_RESOLVE_X": "ZEROS"},
    )
    check_results(results_xml)
    print(f"cocotb AXI monitor bench complete: {build_dir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
