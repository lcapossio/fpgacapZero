#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Run shared cocotb ELA core tests against Verilog or VHDL implementations."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"
TB_COCOTB = ROOT / "tb" / "cocotb"
BUILD_ROOT = ROOT / "build" / "cocotb_ela"

VERILOG_SOURCES = [
    RTL / "reset_sync.v",
    RTL / "fcapz_ela.v",
    RTL / "dpram.v",
    RTL / "trig_compare.v",
]

BASE_PARAMETERS = {
    "SAMPLE_W": 8,
    "DEPTH": 16,
    "TRIG_STAGES": 1,
    "STOR_QUAL": 0,
    "NUM_CHANNELS": 1,
    "INPUT_PIPE": 0,
    "DECIM_EN": 0,
    "EXT_TRIG_EN": 0,
    "TIMESTAMP_W": 0,
    "NUM_SEGMENTS": 1,
    "PROBE_MUX_W": 0,
    "STARTUP_ARM": 0,
    "DEFAULT_TRIG_EXT": 0,
    "REL_COMPARE": 0,
    "DUAL_COMPARE": 1,
    "USER1_DATA_EN": 1,
}


@dataclass(frozen=True)
class CocotbTarget:
    name: str
    parameters: dict[str, int] = field(default_factory=dict)
    testcases: tuple[str, ...] = ()

    @property
    def merged_parameters(self) -> dict[str, int]:
        return {**BASE_PARAMETERS, **self.parameters}


TARGETS: tuple[CocotbTarget, ...] = (
    CocotbTarget(
        "base",
        {"DECIM_EN": 1, "EXT_TRIG_EN": 1},
        (
            "identity_registers",
            "features_registers",
            "register_roundtrip",
            "value_capture",
            "edge_capture",
            "overflow_and_reset",
            "decimation_and_external_trigger",
            "decimation_zero_and_every4",
            "external_trigger_disabled",
            "trigger_out_pulse",
            "trigger_delay_startup_and_holdoff",
            "burst_start_register",
        ),
    ),
    CocotbTarget("timestamp32", {"DECIM_EN": 1, "TIMESTAMP_W": 32}, ("timestamp_capture", "timestamp_decimation_gap")),
    CocotbTarget("timestamp48", {"TIMESTAMP_W": 48}, ("timestamp_48_upper_word",)),
    CocotbTarget("segments4", {"NUM_SEGMENTS": 4}, ("segmented_capture",)),
    CocotbTarget("probe_mux", {"PROBE_MUX_W": 32}, ("probe_mux_slice_selection",)),
    CocotbTarget(
        "input_pipe",
        {"DEPTH": 1024, "DECIM_EN": 1, "EXT_TRIG_EN": 1, "TIMESTAMP_W": 32, "NUM_SEGMENTS": 4, "INPUT_PIPE": 1},
        ("input_pipe_captures", "input_pipe_holdoff_late_ext_pulse"),
    ),
    CocotbTarget("full_depth", {"DEPTH": 8}, ("full_depth_capture",)),
    CocotbTarget("decim_anchor", {"DECIM_EN": 1}, ("decimated_trigger_anchor", "early_pretrigger_waits_for_fill")),
    CocotbTarget("sequencer", {"TRIG_STAGES": 2}, ("sequencer_count_target_one",)),
    CocotbTarget("wide48", {"SAMPLE_W": 48, "DEPTH": 8}, ("wide_sample_readback",)),
    CocotbTarget(
        "segmented_ext_rearm",
        {"DEPTH": 1024, "EXT_TRIG_EN": 1, "TIMESTAMP_W": 32, "NUM_SEGMENTS": 4, "INPUT_PIPE": 1},
        ("segmented_single_pulse_stalls", "segmented_rearm_pulses_complete"),
    ),
    CocotbTarget(
        "rolling_prehistory",
        {"EXT_TRIG_EN": 1, "INPUT_PIPE": 1},
        ("rolling_prehistory_and_rearm",),
    ),
    CocotbTarget(
        "config_min",
        {"TRIG_STAGES": 1, "STOR_QUAL": 0, "DECIM_EN": 0, "EXT_TRIG_EN": 0, "DUAL_COMPARE": 0},
        ("config_minimal",),
    ),
    CocotbTarget("config_nouser1", {"USER1_DATA_EN": 0}, ("config_user1_disabled",)),
    CocotbTarget(
        "config_rel",
        {"TRIG_STAGES": 2, "INPUT_PIPE": 1, "REL_COMPARE": 1, "DUAL_COMPARE": 0},
        ("config_rel_compare",),
    ),
    CocotbTarget(
        "config_combo",
        {"TRIG_STAGES": 2, "STOR_QUAL": 1, "INPUT_PIPE": 1, "NUM_SEGMENTS": 4, "REL_COMPARE": 1, "DUAL_COMPARE": 1},
        ("config_combo_sq_segments",),
    ),
)

SMOKE_TARGETS = (TARGETS[0],)


def windows_to_wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        return resolved.as_posix()
    rest = resolved.as_posix().split(":/", 1)[1]
    return f"/mnt/{drive}/{rest}"


def running_in_wsl() -> bool:
    return "microsoft" in platform.release().lower()


def relaunch_in_wsl(argv: list[str]) -> int:
    script_args = [windows_to_wsl_path(ROOT / argv[0]), *argv[1:]]
    script = "cd {} && python3 {}".format(
        shlex.quote(windows_to_wsl_path(ROOT)),
        " ".join(shlex.quote(arg) for arg in script_args),
    )
    return subprocess.call(["wsl.exe", "-e", "bash", "-lc", script], cwd=ROOT)


def parse_parameter(text: str) -> tuple[str, int]:
    if "=" not in text:
        raise argparse.ArgumentTypeError("parameter must be NAME=VALUE")
    name, value = text.split("=", 1)
    try:
        return name, int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer parameter value: {text}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hdl", choices=("verilog", "vhdl"), default="verilog")
    parser.add_argument("--suite", choices=("all", "smoke", "manual"), default="all")
    parser.add_argument("--sim", default=None)
    parser.add_argument("--runner", choices=("auto", "native", "wsl"), default="auto")
    parser.add_argument("--top", default="fcapz_ela")
    parser.add_argument("--test-module", default="ela_core_test")
    parser.add_argument("--testcase", action="append", default=[])
    parser.add_argument("--vhdl-source", action="append", type=Path, default=[])
    parser.add_argument("--parameter", action="append", type=parse_parameter, default=[])
    parser.add_argument("--waves", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


def resolve_sources(args: argparse.Namespace) -> tuple[list[Path], list[Path]]:
    if args.hdl == "verilog":
        return VERILOG_SOURCES, []

    vhdl_sources = args.vhdl_source
    if not vhdl_sources:
        default_core = RTL / "vhdl" / "core" / "fcapz_ela.vhd"
        if default_core.exists():
            vhdl_sources = [default_core]
        else:
            raise SystemExit(
                "No VHDL core source was found. Pass --vhdl-source for the VHDL "
                "implementation to run the same cocotb tests against VHDL."
            )
    return [], vhdl_sources


def selected_targets(args: argparse.Namespace) -> tuple[CocotbTarget, ...]:
    overrides = dict(args.parameter)
    if args.suite == "manual":
        return (
            CocotbTarget(
                "manual",
                overrides,
                tuple(args.testcase) if args.testcase else ("identity_registers", "value_capture"),
            ),
        )
    if args.parameter or args.testcase:
        raise SystemExit("--parameter and --testcase are only supported with --suite manual")
    return TARGETS if args.suite == "all" else SMOKE_TARGETS


def check_results(results_xml: Path) -> None:
    results = ET.parse(results_xml).getroot()
    failures = len(list(results.iter("failure")))
    errors = len(list(results.iter("error")))
    if failures or errors:
        raise SystemExit(f"cocotb reported failures={failures} errors={errors}: {results_xml}")


def merge_coverage(build_dir: Path, targets: tuple[CocotbTarget, ...]) -> Path:
    merged: dict[str, int] = {}
    total_bins = 0
    for target in targets:
        coverage_path = build_dir / target.name / "functional_coverage.json"
        if not coverage_path.exists():
            continue
        payload = json.loads(coverage_path.read_text())
        for name, count in payload["bins"].items():
            merged[name] = merged.get(name, 0) + int(count)
        total_bins = max(total_bins, int(payload["total_bins"]))

    covered = sum(1 for count in merged.values() if count)
    out = build_dir / "functional_coverage_merged.json"
    out.write_text(
        json.dumps(
            {
                "covered_bins": covered,
                "total_bins": total_bins,
                "percent": round((covered / total_bins) * 100.0, 2) if total_bins else 0.0,
                "bins": merged,
            },
            indent=2,
        )
        + "\n"
    )
    return out


def main() -> None:
    args = parse_args()
    if os.name == "nt" and not running_in_wsl() and args.runner in ("auto", "wsl"):
        raise SystemExit(relaunch_in_wsl(sys.argv))

    try:
        from cocotb.runner import get_runner
    except ModuleNotFoundError as exc:
        raise SystemExit("cocotb is not installed in this Python environment") from exc

    sim = args.sim or ("icarus" if args.hdl == "verilog" else "ghdl")
    verilog_sources, vhdl_sources = resolve_sources(args)
    targets = selected_targets(args)
    build_dir = BUILD_ROOT / f"{args.hdl}_{sim}_{args.suite}"
    runner = get_runner(sim)

    for target in targets:
        target_dir = build_dir / target.name
        results_xml = target_dir / "results.xml"
        coverage_json = target_dir / "functional_coverage.json"
        parameters = target.merged_parameters

        runner.build(
            verilog_sources=verilog_sources,
            vhdl_sources=vhdl_sources,
            includes=[RTL],
            parameters=parameters,
            hdl_toplevel=args.top,
            build_dir=target_dir,
            clean=args.clean,
            always=True,
            waves=args.waves,
            verbose=args.verbose,
            timescale=("1ns", "1ps"),
            build_args=["-Wall"] if args.hdl == "verilog" else [],
        )
        runner.test(
            test_module=args.test_module,
            hdl_toplevel=args.top,
            hdl_toplevel_lang=args.hdl,
            testcase=target.testcases,
            build_dir=target_dir,
            test_dir=TB_COCOTB,
            results_xml=results_xml,
            waves=args.waves,
            verbose=args.verbose,
            extra_env={
                "COCOTB_RESOLVE_X": "ZEROS",
                "ELA_COCOTB_COVERAGE_JSON": str(coverage_json),
                "ELA_COCOTB_RUN": target.name,
                **{f"ELA_PARAM_{name}": str(value) for name, value in parameters.items()},
            },
        )
        check_results(results_xml)

    merged = merge_coverage(build_dir, targets)
    print(f"cocotb ELA {args.hdl} suite complete: {build_dir.relative_to(ROOT)}")
    print(f"Merged functional coverage: {merged.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
