#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Run the Verilog ELA testbenches under Verilator with coverage enabled.

The Icarus runner remains the fast compatibility simulation gate. This script
uses Verilator as a simulation engine for the ELA benches and emits merged code
and functional coverage data for the original Verilog core.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from _runner_utils import windows_to_wsl_path

ROOT = Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"
TB = ROOT / "tb"

DEFAULT_BUILD = ROOT / "build" / "verilator_ela_coverage"

ELA_RTL = (
    RTL / "reset_sync.v",
    RTL / "fcapz_ela.v",
    RTL / "dpram.v",
    RTL / "trig_compare.v",
)

COVERAGE_FLAGS = (
    "--coverage-line",
    "--coverage-toggle",
    "--coverage-user",
)

WARNING_FLAGS = (
    "-Wno-DECLFILENAME",
    "-Wno-GENUNNAMED",
    "-Wno-UNUSEDSIGNAL",
    "-Wno-UNDRIVEN",
    "-Wno-WIDTHTRUNC",
    "-Wno-WIDTHEXPAND",
    "-Wno-UNSIGNED",
    "-Wno-BLKSEQ",
    "-Wno-PINCONNECTEMPTY",
    "-Wno-PINMISSING",
    "-Wno-UNUSEDPARAM",
    "-Wno-SYNCASYNCNET",
    "-Wno-TIMESCALEMOD",
    "-Wno-INITIALDLY",
)


@dataclass(frozen=True)
class ElaBench:
    name: str
    top: str
    testbench: Path
    sources: tuple[Path, ...] = ELA_RTL


BENCHES = (
    ElaBench("fcapz_ela", "fcapz_ela_tb", TB / "fcapz_ela_tb.sv"),
    ElaBench(
        "fcapz_ela_bug_probe",
        "fcapz_ela_bug_probe_tb",
        TB / "fcapz_ela_bug_probe_tb.sv",
    ),
    ElaBench(
        "fcapz_ela_config_matrix",
        "fcapz_ela_config_matrix_tb",
        TB / "fcapz_ela_config_matrix_tb.sv",
    ),
)

BENCH_BY_NAME = {bench.name: bench for bench in BENCHES}


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def quote_cmd(args: list[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in args)


class Runner:
    def __init__(self, mode: str, *, dry_run: bool = False) -> None:
        self.mode = self._resolve_mode(mode)
        self.dry_run = dry_run
        self.root_wsl = windows_to_wsl_path(ROOT)

    @staticmethod
    def _resolve_mode(mode: str) -> str:
        if mode != "auto":
            return mode
        if shutil.which("verilator") and shutil.which("verilator_coverage"):
            return "native"
        if os.name == "nt" and shutil.which("wsl.exe"):
            return "wsl"
        return "native"

    def _display(self, args: list[str]) -> str:
        if self.mode == "wsl":
            inner = f"cd {shlex.quote(self.root_wsl)} && {quote_cmd(args)}"
            return f"wsl.exe -e bash -lc {shlex.quote(inner)}"
        return quote_cmd(args)

    def run(
        self,
        args: list[str],
        label: str,
        *,
        capture: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        print(f"[verilator-cov] {label}: {self._display(args)}", flush=True)
        if self.dry_run:
            return subprocess.CompletedProcess(args, 0, "", "")

        if self.mode == "wsl":
            script = f"cd {shlex.quote(self.root_wsl)} && {quote_cmd(args)}"
            cmd = ["wsl.exe", "-e", "bash", "-lc", script]
            cwd = ROOT
        else:
            cmd = args
            cwd = ROOT

        return subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            capture_output=capture,
        )


def check_tools(runner: Runner) -> bool:
    result = runner.run(["verilator", "--version"], "check verilator", capture=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        print("verilator is not reachable; use --runner wsl if it is installed in WSL",
              file=sys.stderr)
        return False

    match = re.search(r"Verilator\s+(\d+)\.(\d+)", result.stdout + result.stderr)
    if not match:
        print("could not parse Verilator version", file=sys.stderr)
        return False
    version = int(match.group(1)), int(match.group(2))
    if version < (5, 0):
        print(f"Verilator 5.0 or newer is required (found {version[0]}.{version[1]})",
              file=sys.stderr)
        return False

    cov = runner.run(["verilator_coverage", "--help"], "check verilator_coverage", capture=True)
    if cov.returncode != 0:
        sys.stderr.write(cov.stdout + cov.stderr)
        print("verilator_coverage is not reachable", file=sys.stderr)
        return False
    return True


def build_cmd(bench: ElaBench, build_dir: Path, *, functional: bool, runner: Runner) -> list[str]:
    bench_dir = build_dir / bench.name
    obj_dir = bench_dir / "obj_dir"
    main_cpp = bench_dir / "coverage_main.cpp"
    main_cpp_arg = windows_to_wsl_path(main_cpp) if runner.mode == "wsl" else str(main_cpp)
    sources = [bench.testbench, *bench.sources]
    if functional:
        sources.append(TB / "fcapz_ela_func_cov.sv")

    return [
        "verilator",
        "-sv",
        "--cc",
        "--exe",
        "--build",
        "--timing",
        "--assert",
        *COVERAGE_FLAGS,
        *WARNING_FLAGS,
        "-Irtl",
        "--top-module",
        bench.top,
        "-Mdir",
        rel(obj_dir),
        *[rel(src) for src in sources],
        main_cpp_arg,
    ]


def run_cmd(bench: ElaBench, build_dir: Path, *, windows_exe: bool) -> list[str]:
    exe = build_dir / bench.name / "obj_dir" / f"V{bench.top}"
    if windows_exe:
        exe = exe.with_suffix(".exe")
    return [rel(exe)]


def write_harness(bench: ElaBench, build_dir: Path) -> None:
    bench_dir = build_dir / bench.name
    coverage_file = rel(bench_dir / "coverage.dat")
    text = f"""// Generated by sim/run_verilator_ela_coverage.py
#include "V{bench.top}.h"
#include "verilated.h"
#include "verilated_cov.h"

int main(int argc, char** argv) {{
    VerilatedContext context;
    context.commandArgs(argc, argv);

    V{bench.top} top(&context);
    while (!context.gotFinish()) {{
        top.eval();
        if (!top.eventsPending()) break;
        context.time(top.nextTimeSlot());
    }}

    top.final();
    VerilatedCov::write("{coverage_file}");
    return 0;
}}
"""
    (bench_dir / "coverage_main.cpp").write_text(text)


def merge_cmd(build_dir: Path, benches: list[ElaBench]) -> list[str]:
    return [
        "verilator_coverage",
        "--write",
        rel(build_dir / "merged.dat"),
        *[rel(build_dir / bench.name / "coverage.dat") for bench in benches],
    ]


def annotate_cmd(build_dir: Path) -> list[str]:
    return [
        "verilator_coverage",
        "--annotate",
        rel(build_dir / "annotated"),
        "--annotate-all",
        "--annotate-points",
        "--annotate-min",
        "1",
        rel(build_dir / "merged.dat"),
    ]


def write_info_cmd(build_dir: Path) -> list[str]:
    return [
        "verilator_coverage",
        "--write-info",
        rel(build_dir / "merged.info"),
        rel(build_dir / "merged.dat"),
    ]


def selected_benches(names: list[str]) -> list[ElaBench]:
    if not names:
        return list(BENCHES)
    unknown = [name for name in names if name not in BENCH_BY_NAME]
    if unknown:
        print(f"Unknown ELA coverage bench(es): {unknown}", file=sys.stderr)
        print(f"Available: {', '.join(BENCH_BY_NAME)}", file=sys.stderr)
        sys.exit(2)
    return [BENCH_BY_NAME[name] for name in names]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("testbench", nargs="*", help="ELA bench name(s) to run")
    parser.add_argument(
        "--runner",
        choices=("auto", "native", "wsl"),
        default="auto",
        help="where to run Verilator; auto prefers native, then WSL on Windows",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=DEFAULT_BUILD,
        help="coverage output directory",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="print commands without running them")
    parser.add_argument("--keep-going", action="store_true",
                        help="continue after a bench fails")
    parser.add_argument(
        "--no-functional",
        action="store_true",
        help="skip the bound functional coverage module",
    )
    parser.add_argument("--no-merge", action="store_true", help="skip coverage merge")
    parser.add_argument("--no-annotate", action="store_true",
                        help="skip annotated coverage output")
    parser.add_argument("--write-info", action="store_true",
                        help="also emit lcov-compatible merged.info")
    args = parser.parse_args()

    benches = selected_benches(args.testbench)
    build_dir = args.build_dir if args.build_dir.is_absolute() else ROOT / args.build_dir
    runner = Runner(args.runner, dry_run=args.dry_run)

    if not args.dry_run and not check_tools(runner):
        sys.exit(127)

    failures: list[str] = []
    build_dir.mkdir(parents=True, exist_ok=True)

    for bench in benches:
        (build_dir / bench.name).mkdir(parents=True, exist_ok=True)
        if not args.dry_run:
            write_harness(bench, build_dir)
        for label, cmd in (
            (
                f"build {bench.name}",
                build_cmd(bench, build_dir, functional=not args.no_functional, runner=runner),
            ),
            (
                f"simulate {bench.name}",
                run_cmd(bench, build_dir,
                        windows_exe=(runner.mode == "native" and os.name == "nt")),
            ),
        ):
            result = runner.run(cmd, label)
            if result.returncode != 0:
                failures.append(label)
                if not args.keep_going:
                    print(f"[verilator-cov] FAILED: {label}", file=sys.stderr)
                    sys.exit(result.returncode)
                break

    if failures and not args.keep_going:
        sys.exit(1)

    if not failures and not args.no_merge:
        result = runner.run(merge_cmd(build_dir, benches), "merge coverage")
        if result.returncode != 0:
            sys.exit(result.returncode)

        if not args.no_annotate:
            result = runner.run(annotate_cmd(build_dir), "annotate coverage")
            if result.returncode != 0:
                sys.exit(result.returncode)

        if args.write_info:
            result = runner.run(write_info_cmd(build_dir), "write lcov info")
            if result.returncode != 0:
                sys.exit(result.returncode)

    if failures:
        print(f"[verilator-cov] FAILED: {failures}", file=sys.stderr)
        sys.exit(1)

    print(f"Verilator ELA coverage complete for {len(benches)} bench(es).")
    if not args.no_merge:
        print(f"Coverage data: {rel(build_dir / 'merged.dat')}")
        if not args.no_annotate:
            print(f"Annotated RTL: {rel(build_dir / 'annotated')}")


if __name__ == "__main__":
    main()
