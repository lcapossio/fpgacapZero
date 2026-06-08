#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Run cocotb replacements for the RTL simulation testbenches."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from _runner_utils import check_results, relaunch_in_wsl, running_in_wsl

ROOT = Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"
SIM = ROOT / "sim"
TB = ROOT / "tb"
TB_COCOTB = ROOT / "tb" / "cocotb"
BUILD_ROOT = ROOT / "build" / "cocotb"


@dataclass(frozen=True)
class Target:
    name: str
    top: str
    sources: tuple[Path, ...]
    testcase: str
    parameters: dict[str, int] = field(default_factory=dict)
    vhdl_sources: tuple[Path, ...] = ()


ELA_TARGET = "ela"

_TRIG_COMPARE_SRC = (RTL / "trig_compare.v",)
_VHDL_PKG = (RTL / "vhdl" / "pkg" / "fcapz_pkg.vhd",)
_VHDL_ELA_SRC = (
    RTL / "vhdl" / "pkg" / "fcapz_pkg.vhd",
    RTL / "vhdl" / "pkg" / "fcapz_util_pkg.vhd",
    RTL / "vhdl" / "core" / "fcapz_dpram.vhd",
    RTL / "vhdl" / "core" / "fcapz_ela.vhd",
)

TARGETS: tuple[Target, ...] = (
    Target("trig_compare_light", "trig_compare", _TRIG_COMPARE_SRC,
           "trig_compare_light", {"W": 8, "REL_COMPARE": 0}),
    Target("trig_compare_full", "trig_compare", _TRIG_COMPARE_SRC,
           "trig_compare_full", {"W": 8, "REL_COMPARE": 1}),
    Target(
        "jtag_burst_read",
        "jtag_burst_read",
        (RTL / "jtag_burst_read.v",),
        "jtag_burst_read_protocol",
        {"SAMPLE_W": 8, "TIMESTAMP_W": 32, "DEPTH": 1024, "BURST_W": 256, "SEG_DEPTH": 256},
    ),
    Target(
        "jtag_pipe_iface",
        "jtag_pipe_iface",
        (RTL / "jtag_pipe_iface.v",),
        "jtag_pipe_iface_protocol",
        {"SAMPLE_W": 8, "TIMESTAMP_W": 32, "DEPTH": 1024, "BURST_W": 256, "SEG_DEPTH": 1024},
    ),
    Target(
        "jtag_pipe_iface_segmented",
        "jtag_pipe_iface",
        (RTL / "jtag_pipe_iface.v",),
        "jtag_pipe_iface_segmented_alignment",
        {"SAMPLE_W": 8, "TIMESTAMP_W": 0, "DEPTH": 1024, "BURST_W": 256, "SEG_DEPTH": 256},
    ),
    Target(
        "fcapz_eio",
        "fcapz_eio",
        (RTL / "fcapz_eio.v",),
        "fcapz_eio_registers",
        {"IN_W": 16, "OUT_W": 12},
        (*_VHDL_PKG, RTL / "vhdl" / "core" / "fcapz_eio.vhd"),
    ),
    Target(
        "fcapz_core_manager",
        "fcapz_core_manager",
        (RTL / "fcapz_core_manager.v",),
        "fcapz_core_manager_mux",
        {
            "NUM_SLOTS": 3,
            "SAMPLE_W": 8,
            "TIMESTAMP_W": 4,
            "DEPTH": 16,
            "SLOT_CORE_IDS": 0x494F_4C41_4C41,
            "SLOT_HAS_BURST": 0b011,
        },
    ),
    Target(
        "chan_mux",
        "fcapz_ela",
        (RTL / "reset_sync.v", RTL / "fcapz_ela.v", RTL / "dpram.v", RTL / "trig_compare.v"),
        "fcapz_ela_channel_mux",
        {"SAMPLE_W": 8, "DEPTH": 16, "NUM_CHANNELS": 3},
        _VHDL_ELA_SRC,
    ),
    Target(
        "fcapz_ela_xilinx7_single_chain",
        "fcapz_ela_xilinx7",
        (
            SIM / "bscane2_stub.v",
            RTL / "reset_sync.v",
            RTL / "dpram.v",
            RTL / "trig_compare.v",
            RTL / "fcapz_ela.v",
            RTL / "jtag_pipe_iface.v",
            RTL / "jtag_reg_iface.v",
            RTL / "jtag_burst_read.v",
            RTL / "jtag_tap" / "jtag_tap_xilinx7.v",
            RTL / "fcapz_eio.v",
            RTL / "fcapz_regbus_mux.v",
            RTL / "fcapz_ela_xilinx7.v",
        ),
        "fcapz_ela_xilinx7_single_chain",
        {
            "SAMPLE_W": 8,
            "DEPTH": 64,
            "TRIG_STAGES": 1,
            "STOR_QUAL": 0,
            "INPUT_PIPE": 0,
            "NUM_CHANNELS": 1,
            "DECIM_EN": 0,
            "EXT_TRIG_EN": 0,
            "TIMESTAMP_W": 0,
            "NUM_SEGMENTS": 1,
            "STARTUP_ARM": 0,
            "BURST_EN": 1,
            "SINGLE_CHAIN_BURST": 1,
            "CTRL_CHAIN": 1,
            "DATA_CHAIN": 2,
            "REL_COMPARE": 0,
            "DUAL_COMPARE": 0,
            "USER1_DATA_EN": 1,
        },
    ),
    Target(
        "fcapz_async_fifo_equiv",
        "fcapz_async_fifo_equiv_wrap",
        (TB_COCOTB / "fcapz_async_fifo_equiv_wrap.v",
         RTL / "fcapz_async_fifo.v",
         TB / "xpm_fifo_async_stub.v"),
        "fcapz_async_fifo_equiv",
        {"DATA_W": 8, "DEPTH": 16},
    ),
    Target(
        "fcapz_ejtagaxi",
        "fcapz_ejtagaxi",
        (
            RTL / "fcapz_async_fifo.v",
            RTL / "fcapz_ejtagaxi.v",
        ),
        "fcapz_ejtagaxi_protocol",
        {"FIFO_DEPTH": 16},
        (
            RTL / "vhdl" / "pkg" / "fcapz_pkg.vhd",
            RTL / "vhdl" / "pkg" / "fcapz_util_pkg.vhd",
            RTL / "vhdl" / "core" / "fcapz_async_fifo.vhd",
            RTL / "vhdl" / "core" / "fcapz_ejtagaxi.vhd",
        ),
    ),
    Target(
        "fcapz_ejtagaxi_reset_regression",
        "fcapz_ejtagaxi",
        (
            RTL / "fcapz_async_fifo.v",
            RTL / "fcapz_ejtagaxi.v",
        ),
        "fcapz_ejtagaxi_reset_regression",
        {"DEBUG_EN": 0, "FIFO_DEPTH": 16, "CMD_FIFO_DEPTH": 32,
         "RESP_FIFO_DEPTH": 32, "USE_BEHAV_ASYNC_FIFO": 1},
        (
            RTL / "vhdl" / "pkg" / "fcapz_pkg.vhd",
            RTL / "vhdl" / "pkg" / "fcapz_util_pkg.vhd",
            RTL / "vhdl" / "core" / "fcapz_async_fifo.vhd",
            RTL / "vhdl" / "core" / "fcapz_ejtagaxi.vhd",
        ),
    ),
    Target(
        "fcapz_ejtaguart",
        "fcapz_ejtaguart",
        (RTL / "fcapz_async_fifo.v", RTL / "fcapz_ejtaguart.v"),
        "fcapz_ejtaguart_protocol",
        {"CLK_HZ": 10_000_000, "BAUD_RATE": 100_000,
         "TX_FIFO_DEPTH": 16, "RX_FIFO_DEPTH": 16, "PARITY": 0},
        (
            RTL / "vhdl" / "pkg" / "fcapz_pkg.vhd",
            RTL / "vhdl" / "pkg" / "fcapz_util_pkg.vhd",
            RTL / "vhdl" / "core" / "fcapz_async_fifo.vhd",
            RTL / "vhdl" / "core" / "fcapz_ejtaguart.vhd",
        ),
    ),
)

TARGET_BY_NAME = {target.name: target for target in TARGETS}
DEFAULT_TARGETS = tuple(target.name for target in TARGETS)


def run_ela(args: argparse.Namespace, hdl: str) -> None:
    cmd = [
        sys.executable,
        str(ROOT / "sim" / "run_cocotb_ela.py"),
        "--runner",
        "native",
        "--hdl",
        hdl,
        "--suite",
        "all",
    ]
    if args.clean:
        cmd.append("--clean")
    subprocess.check_call(cmd, cwd=ROOT)


def target_supports_hdl(target: Target, hdl: str) -> bool:
    return hdl == "verilog" or bool(target.vhdl_sources)


def run_target(target: Target, args: argparse.Namespace, hdl: str) -> None:
    from cocotb.runner import get_runner

    sim = args.sim or ("icarus" if hdl == "verilog" else "ghdl")
    runner = get_runner(sim)
    build_dir = BUILD_ROOT / f"{hdl}_{sim}" / target.name
    results_xml = build_dir / "results.xml"
    if str(TB_COCOTB) not in sys.path:
        sys.path.insert(0, str(TB_COCOTB))

    runner.build(
        verilog_sources=list(target.sources) if hdl == "verilog" else [],
        vhdl_sources=list(target.vhdl_sources) if hdl == "vhdl" else [],
        includes=[RTL],
        parameters=target.parameters,
        hdl_toplevel=target.top,
        build_dir=build_dir,
        clean=args.clean,
        always=True,
        waves=args.waves,
        verbose=args.verbose,
        timescale=("1ns", "1ps"),
        build_args=["-Wall"] if hdl == "verilog" else ["--std=08"],
    )
    runner.test(
        test_module="core_test",
        hdl_toplevel=target.top,
        hdl_toplevel_lang=hdl,
        testcase=(target.testcase,),
        build_dir=build_dir,
        test_dir=build_dir if hdl == "vhdl" else TB_COCOTB,
        results_xml=results_xml,
        test_args=["--std=08"] if hdl == "vhdl" else [],
        waves=args.waves,
        verbose=args.verbose,
        extra_env={
            "COCOTB_RESOLVE_X": "ZEROS",
            "FCAPZ_COCOTB_TARGET": target.name,
            "FCAPZ_COCOTB_HDL": hdl,
        },
    )
    check_results(results_xml)
    print(f"cocotb {hdl} target passed: {target.name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="*", help=f"target name(s), or {ELA_TARGET}")
    parser.add_argument("--runner", choices=("auto", "native", "wsl"), default="auto")
    parser.add_argument("--hdl", choices=("verilog", "vhdl", "both"), default="verilog")
    parser.add_argument("--sim", choices=("icarus", "ghdl"), default=None,
                        help="cocotb simulator backend; defaults to Icarus for Verilog "
                             "and GHDL for VHDL")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--waves", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--skip-ela", action="store_true",
                        help="run only non-ELA cocotb replacements")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if os.name == "nt" and not running_in_wsl() and args.runner in ("auto", "wsl"):
        raise SystemExit(relaunch_in_wsl(ROOT, sys.argv))

    requested = tuple(args.target) if args.target else DEFAULT_TARGETS
    unknown = [name for name in requested if name not in TARGET_BY_NAME and name != ELA_TARGET]
    if unknown:
        available = [ELA_TARGET, *TARGET_BY_NAME]
        raise SystemExit(f"Unknown target(s): {unknown}. Available: {available}")

    hdls = ("verilog", "vhdl") if args.hdl == "both" else (args.hdl,)
    explicit_targets = bool(args.target)

    for hdl in hdls:
        if args.sim is not None and ((hdl == "verilog") != (args.sim == "icarus")):
            raise SystemExit(f"--sim {args.sim} is not supported for --hdl {hdl}")
        if (not args.target or ELA_TARGET in requested) and not args.skip_ela:
            run_ela(args, hdl)

        skipped: list[str] = []
        for name in requested:
            if name == ELA_TARGET:
                continue
            target = TARGET_BY_NAME[name]
            if target_supports_hdl(target, hdl):
                run_target(target, args, hdl)
            elif explicit_targets:
                raise SystemExit(f"Target {name!r} has no {hdl} implementation in this branch")
            else:
                skipped.append(name)
        if skipped and hdl == "vhdl":
            print(f"Skipped Verilog-only target(s) for VHDL run: {', '.join(skipped)}")

    print("cocotb regression complete")


if __name__ == "__main__":
    main()
