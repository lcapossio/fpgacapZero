#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Run cocotb replacements for the RTL simulation testbenches."""

from __future__ import annotations

import argparse
import json
import os
import re
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
    vhdl_top: str | None = None
    vhdl_parameters: dict[str, int] | None = None


ELA_TARGET = "ela"

_TRIG_COMPARE_SRC = (RTL / "trig_compare.v",)
_VHDL_PKG = (RTL / "vhdl" / "pkg" / "fcapz_pkg.vhd",)
_VHDL_UTIL_PKG = (RTL / "vhdl" / "pkg" / "fcapz_util_pkg.vhd",)
_VHDL_CORE_PKGS = (*_VHDL_PKG, *_VHDL_UTIL_PKG)
_VHDL_ELA_SRC = (
    RTL / "vhdl" / "pkg" / "fcapz_pkg.vhd",
    RTL / "vhdl" / "pkg" / "fcapz_util_pkg.vhd",
    RTL / "vhdl" / "core" / "fcapz_dpram.vhd",
    RTL / "vhdl" / "core" / "fcapz_ela.vhd",
)

TARGETS: tuple[Target, ...] = (
    Target("trig_compare_light", "trig_compare", _TRIG_COMPARE_SRC,
           "trig_compare_light", {"W": 8, "REL_COMPARE": 0},
           (RTL / "vhdl" / "core" / "trig_compare.vhd",)),
    Target("trig_compare_full", "trig_compare", _TRIG_COMPARE_SRC,
           "trig_compare_full", {"W": 8, "REL_COMPARE": 1},
           (RTL / "vhdl" / "core" / "trig_compare.vhd",)),
    Target(
        "jtag_burst_read",
        "jtag_burst_read",
        (RTL / "jtag_burst_read.v",),
        "jtag_burst_read_protocol",
        {"SAMPLE_W": 8, "TIMESTAMP_W": 32, "DEPTH": 1024, "BURST_W": 256, "SEG_DEPTH": 256},
        (*_VHDL_UTIL_PKG, RTL / "vhdl" / "core" / "jtag_burst_read.vhd"),
    ),
    Target(
        "jtag_pipe_iface",
        "jtag_pipe_iface",
        (RTL / "jtag_pipe_iface.v",),
        "jtag_pipe_iface_protocol",
        {"SAMPLE_W": 8, "TIMESTAMP_W": 32, "DEPTH": 1024, "BURST_W": 256, "SEG_DEPTH": 1024},
        (*_VHDL_UTIL_PKG, RTL / "vhdl" / "core" / "jtag_pipe_iface.vhd"),
    ),
    Target(
        "jtag_pipe_iface_segmented",
        "jtag_pipe_iface",
        (RTL / "jtag_pipe_iface.v",),
        "jtag_pipe_iface_segmented_alignment",
        {"SAMPLE_W": 8, "TIMESTAMP_W": 0, "DEPTH": 1024, "BURST_W": 256, "SEG_DEPTH": 256},
        (*_VHDL_UTIL_PKG, RTL / "vhdl" / "core" / "jtag_pipe_iface.vhd"),
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
        "fcapz_eio_wide",
        "fcapz_eio",
        (RTL / "fcapz_eio.v",),
        "fcapz_eio_registers",
        {"IN_W": 40, "OUT_W": 36},
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
        (*_VHDL_CORE_PKGS,
         RTL / "vhdl" / "core" / "fcapz_core_manager.vhd",
         TB_COCOTB / "fcapz_core_manager_cocotb_wrap.vhd"),
        "fcapz_core_manager_cocotb_wrap",
        {},
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
        (*_VHDL_CORE_PKGS,
         SIM / "bscane2_stub.vhd",
         RTL / "vhdl" / "core" / "reset_sync.vhd",
         RTL / "vhdl" / "core" / "fcapz_dpram.vhd",
         RTL / "vhdl" / "core" / "trig_compare.vhd",
         RTL / "vhdl" / "core" / "fcapz_ela.vhd",
         RTL / "vhdl" / "core" / "jtag_pipe_iface.vhd",
         RTL / "vhdl" / "core" / "jtag_reg_iface.vhd",
         RTL / "vhdl" / "core" / "jtag_burst_read.vhd",
         RTL / "vhdl" / "jtag_tap" / "jtag_tap_xilinx7.vhd",
         RTL / "vhdl" / "core" / "fcapz_eio.vhd",
         RTL / "vhdl" / "core" / "fcapz_regbus_mux.vhd",
         RTL / "vhdl" / "fcapz_ela_xilinx7.vhd"),
    ),
    Target(
        "fcapz_async_fifo_equiv",
        "fcapz_async_fifo_equiv_wrap",
        (TB_COCOTB / "fcapz_async_fifo_equiv_wrap.v",
         RTL / "fcapz_async_fifo.v",
         TB / "xpm_fifo_async_stub.v"),
        "fcapz_async_fifo_equiv",
        {"DATA_W": 8, "DEPTH": 16},
        (*_VHDL_UTIL_PKG,
         RTL / "vhdl" / "core" / "fcapz_async_fifo.vhd",
         SIM / "xpm_fifo_async_stub.vhd",
         TB_COCOTB / "fcapz_async_fifo_equiv_wrap.vhd"),
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
COVERAGE_TARGETS = {
    "fcapz_eio": ("eio", "EIO_COCOTB_COVERAGE_JSON", "EIO_COCOTB_RUN"),
    "fcapz_eio_wide": ("eio", "EIO_COCOTB_COVERAGE_JSON", "EIO_COCOTB_RUN"),
    "jtag_burst_read": (
        "jtag_burst_read",
        "JTAG_BURST_COCOTB_COVERAGE_JSON",
        "JTAG_BURST_COCOTB_RUN",
    ),
    "jtag_pipe_iface": (
        "jtag_pipe_iface",
        "JTAG_PIPE_COCOTB_COVERAGE_JSON",
        "JTAG_PIPE_COCOTB_RUN",
    ),
    "jtag_pipe_iface_segmented": (
        "jtag_pipe_iface",
        "JTAG_PIPE_COCOTB_COVERAGE_JSON",
        "JTAG_PIPE_COCOTB_RUN",
    ),
    "fcapz_async_fifo_equiv": (
        "fcapz_async_fifo_equiv",
        "ASYNC_FIFO_COCOTB_COVERAGE_JSON",
        "ASYNC_FIFO_COCOTB_RUN",
    ),
    "fcapz_ejtagaxi": (
        "fcapz_ejtagaxi",
        "EJTAG_AXI_COCOTB_COVERAGE_JSON",
        "EJTAG_AXI_COCOTB_RUN",
    ),
    "fcapz_ejtagaxi_reset_regression": (
        "fcapz_ejtagaxi",
        "EJTAG_AXI_COCOTB_COVERAGE_JSON",
        "EJTAG_AXI_COCOTB_RUN",
    ),
    "fcapz_ejtaguart": (
        "fcapz_ejtaguart",
        "EJTAG_UART_COCOTB_COVERAGE_JSON",
        "EJTAG_UART_COCOTB_RUN",
    ),
}
COVERAGE_GROUP_LABELS = {
    "eio": "EIO",
    "jtag_burst_read": "JTAG burst reader",
    "jtag_pipe_iface": "JTAG pipe interface",
    "fcapz_async_fifo_equiv": "async FIFO equivalence",
    "fcapz_ejtagaxi": "EJTAG-AXI",
    "fcapz_ejtaguart": "EJTAG-UART",
}


def merge_coverage(paths: list[Path], out: Path) -> dict[str, object] | None:
    merged: dict[str, int] = {}
    total_bins = 0
    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text())
        for name, count in payload["bins"].items():
            merged[name] = merged.get(name, 0) + int(count)
        total_bins = max(total_bins, int(payload["total_bins"]))

    if not total_bins:
        return None
    covered = sum(1 for count in merged.values() if count)
    payload = {
        "covered_bins": covered,
        "total_bins": total_bins,
        "percent": round((covered / total_bins) * 100.0, 2),
        "bins": merged,
    }
    out.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


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


def get_cocotb_runner(sim: str):
    try:
        from cocotb_tools.runner import get_runner
    except ModuleNotFoundError:
        from cocotb.runner import get_runner

    return get_runner(sim)


def cocotb_test_filter(testcases: str | tuple[str, ...]) -> str:
    cases = (testcases,) if isinstance(testcases, str) else testcases
    return "|".join(rf".*\.{re.escape(case)}$" for case in cases)


def run_target(target: Target, args: argparse.Namespace, hdl: str) -> tuple[str, Path] | None:
    sim = args.sim or ("icarus" if hdl == "verilog" else "ghdl")
    runner = get_cocotb_runner(sim)
    build_dir = BUILD_ROOT / f"{hdl}_{sim}" / target.name
    results_xml = build_dir / "results.xml"
    coverage_info = COVERAGE_TARGETS.get(target.name)
    coverage_json = build_dir / "functional_coverage.json" if coverage_info else None
    if str(TB_COCOTB) not in sys.path:
        sys.path.insert(0, str(TB_COCOTB))

    runner.build(
        sources=list(target.sources) if hdl == "verilog" else list(target.vhdl_sources),
        includes=[RTL],
        parameters=target.parameters if hdl == "verilog"
        else (target.vhdl_parameters if target.vhdl_parameters is not None else target.parameters),
        hdl_toplevel=target.top if hdl == "verilog" else (target.vhdl_top or target.top),
        build_dir=build_dir,
        clean=args.clean,
        always=True,
        waves=args.waves,
        verbose=args.verbose,
        timescale=("1ns", "1ps"),
        build_args=["-Wall"] if hdl == "verilog" else ["--std=08"],
    )
    extra_env = {
        "COCOTB_RESOLVE_X": "ZEROS",
        "FCAPZ_COCOTB_TARGET": target.name,
        "FCAPZ_COCOTB_HDL": hdl,
    }
    if coverage_json is not None:
        assert coverage_info is not None
        _, json_env_var, run_env_var = coverage_info
        extra_env.update({
            json_env_var: str(coverage_json),
            run_env_var: target.name,
        })

    runner.test(
        test_module="core_test",
        hdl_toplevel=target.top if hdl == "verilog" else (target.vhdl_top or target.top),
        hdl_toplevel_lang=hdl,
        test_filter=cocotb_test_filter(target.testcase),
        build_dir=build_dir,
        test_dir=build_dir if hdl == "vhdl" else TB_COCOTB,
        results_xml=results_xml,
        test_args=["--std=08"] if hdl == "vhdl" else [],
        waves=args.waves,
        verbose=args.verbose,
        extra_env=extra_env,
    )
    check_results(results_xml)
    print(f"cocotb {hdl} target passed: {target.name}")
    if coverage_info is None or coverage_json is None:
        return None
    return coverage_info[0], coverage_json


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
    parser.add_argument("--require-protocol-coverage", action="store_true",
                        help="fail unless all protocol functional coverage bins are hit")
    parser.add_argument("--require-eio-coverage", action="store_true",
                        dest="require_protocol_coverage",
                        help="legacy alias for --require-protocol-coverage")
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
        coverage_paths: dict[str, list[Path]] = {}
        expected_coverage_groups: set[str] = set()
        for name in requested:
            if name == ELA_TARGET:
                continue
            target = TARGET_BY_NAME[name]
            if target_supports_hdl(target, hdl):
                coverage_info = COVERAGE_TARGETS.get(name)
                if coverage_info is not None:
                    expected_coverage_groups.add(coverage_info[0])
                coverage_result = run_target(target, args, hdl)
                if coverage_result is not None:
                    group, coverage_path = coverage_result
                    coverage_paths.setdefault(group, []).append(coverage_path)
            elif explicit_targets:
                raise SystemExit(f"Target {name!r} has no {hdl} implementation in this branch")
            else:
                skipped.append(name)
        sim = args.sim or ("icarus" if hdl == "verilog" else "ghdl")
        for group in sorted(coverage_paths):
            coverage_merged = (
                BUILD_ROOT
                / f"{hdl}_{sim}"
                / f"{group}_functional_coverage_merged.json"
            )
            payload = merge_coverage(coverage_paths[group], coverage_merged)
            label = COVERAGE_GROUP_LABELS.get(group, group)
            if payload is not None:
                print(
                    f"Merged {label} functional coverage: "
                    f"{coverage_merged.relative_to(ROOT)}"
                )
                if (
                    args.require_protocol_coverage
                    and payload["covered_bins"] != payload["total_bins"]
                ):
                    raise SystemExit(
                        f"{label} functional coverage below 100%: "
                        f"{payload['covered_bins']}/{payload['total_bins']} bins"
                    )
            elif args.require_protocol_coverage:
                raise SystemExit(
                    f"{label} functional coverage was required, "
                    "but no report was written"
                )
        if args.require_protocol_coverage:
            missing_groups = expected_coverage_groups - set(coverage_paths)
            if missing_groups:
                labels = [
                    COVERAGE_GROUP_LABELS.get(group, group)
                    for group in sorted(missing_groups)
                ]
                raise SystemExit(
                    "Protocol functional coverage was required, but no reports "
                    f"were written for: {', '.join(labels)}"
                )
        if skipped and hdl == "vhdl":
            print(f"Skipped Verilog-only target(s) for VHDL run: {', '.join(skipped)}")

    print("cocotb regression complete")


if __name__ == "__main__":
    main()
