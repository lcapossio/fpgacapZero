#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Check that translated VHDL cores track the source-of-truth Verilog cores.

Verilog is the development source for the portable EIO/ELA cores.  This script
is the CI gate for the VHDL port: it checks that public generics/parameters and
register address constants remain aligned, then runs the matching Verilog and
VHDL regression benches in one job.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"
RTL_VHDL = RTL / "vhdl" / "core"


@dataclass(frozen=True)
class CoreParity:
    name: str
    verilog: Path
    vhdl: Path
    parameters: tuple[str, ...]
    constants: tuple[str, ...]


CORES = (
    CoreParity(
        name="fcapz_eio",
        verilog=RTL / "fcapz_eio.v",
        vhdl=RTL_VHDL / "fcapz_eio.vhd",
        parameters=("IN_W", "OUT_W"),
        constants=(
            "ADDR_VERSION",
            "ADDR_IN_W",
            "ADDR_OUT_W",
            "ADDR_IN_BASE",
            "ADDR_OUT_BASE",
        ),
    ),
    CoreParity(
        name="fcapz_ela",
        verilog=RTL / "fcapz_ela.v",
        vhdl=RTL_VHDL / "fcapz_ela.vhd",
        parameters=(
            "SAMPLE_W",
            "DEPTH",
            "TRIG_STAGES",
            "STOR_QUAL",
            "NUM_CHANNELS",
            "INPUT_PIPE",
            "DECIM_EN",
            "EXT_TRIG_EN",
            "TIMESTAMP_W",
            "NUM_SEGMENTS",
            "PROBE_MUX_W",
            "STARTUP_ARM",
            "DEFAULT_TRIG_EXT",
            "REL_COMPARE",
            "DUAL_COMPARE",
            "USER1_DATA_EN",
        ),
        constants=(
            "ADDR_VERSION",
            "ADDR_CTRL",
            "ADDR_STATUS",
            "ADDR_SAMPLE_W",
            "ADDR_DEPTH",
            "ADDR_PRETRIG",
            "ADDR_POSTTRIG",
            "ADDR_CAPTURE_LEN",
            "ADDR_TRIG_MODE",
            "ADDR_TRIG_VALUE",
            "ADDR_TRIG_MASK",
            "ADDR_BURST_PTR",
            "ADDR_SQ_MODE",
            "ADDR_SQ_VALUE",
            "ADDR_SQ_MASK",
            "ADDR_FEATURES",
            "ADDR_SEQ_BASE",
            "SEQ_STRIDE",
            "ADDR_CHAN_SEL",
            "ADDR_NUM_CHAN",
            "ADDR_PROBE_SEL",
            "ADDR_DECIM",
            "ADDR_TRIG_EXT",
            "ADDR_NUM_SEGMENTS",
            "ADDR_SEG_STATUS",
            "ADDR_SEG_SEL",
            "ADDR_TIMESTAMP_W",
            "ADDR_SEG_START",
            "ADDR_PROBE_MUX_W",
            "ADDR_TRIG_DELAY",
            "ADDR_STARTUP_ARM",
            "ADDR_TRIG_HOLDOFF",
            "ADDR_COMPARE_CAPS",
            "ADDR_DATA_BASE",
        ),
    ),
)


VERILOG_PARITY_TESTS = (
    "fcapz_eio",
    "fcapz_ela",
    "fcapz_ela_bug_probe",
    "fcapz_ela_config_matrix",
)
VHDL_PARITY_TESTS = ("fcapz_eio", "fcapz_ela")


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
    return re.sub(r"--.*", "", text)


def parse_int_literal(value: str) -> int:
    value = value.strip()
    value = re.sub(r"\s+", "", value)
    value = value.strip("()")
    verilog_hex = re.fullmatch(r"(?:\d+)?'[hH]([0-9a-fA-F_]+)", value)
    if verilog_hex:
        return int(verilog_hex.group(1).replace("_", ""), 16)
    vhdl_hex = re.fullmatch(r"16#([0-9a-fA-F_]+)#", value)
    if vhdl_hex:
        return int(vhdl_hex.group(1).replace("_", ""), 16)
    decimal = re.fullmatch(r"\d+", value)
    if decimal:
        return int(value)
    raise ValueError(f"unsupported integer literal: {value!r}")


def parse_verilog_parameters(text: str) -> dict[str, int]:
    body = strip_comments(text)
    found: dict[str, int] = {}
    for match in re.finditer(r"\bparameter\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^,\n)]+)", body):
        found[match.group(1)] = parse_int_literal(match.group(2))
    return found


def parse_vhdl_generics(text: str) -> dict[str, int]:
    body = strip_comments(text)
    generic_block = re.search(r"\bgeneric\s*\((.*?)\)\s*;", body, flags=re.I | re.S)
    if generic_block is None:
        return {}
    body = generic_block.group(1)
    found: dict[str, int] = {}
    for match in re.finditer(
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?:positive|natural|integer)\s*:=\s*([^;,\n)]+)",
        body,
        flags=re.I,
    ):
        found[match.group(1)] = parse_int_literal(match.group(2))
    return found


def parse_verilog_constants(text: str) -> dict[str, int]:
    body = strip_comments(text)
    found: dict[str, int] = {}
    pattern = r"\blocalparam(?:\s+\[[^\]]+\])?\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;]+);"
    for match in re.finditer(pattern, body):
        try:
            found[match.group(1)] = parse_int_literal(match.group(2))
        except ValueError:
            pass
    return found


def parse_vhdl_constants(text: str) -> dict[str, int]:
    body = strip_comments(text)
    found: dict[str, int] = {}
    for match in re.finditer(
        r"\bconstant\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?:natural|positive|integer)\s*:=\s*([^;]+);",
        body,
        flags=re.I,
    ):
        try:
            found[match.group(1)] = parse_int_literal(match.group(2))
        except ValueError:
            pass
    return found


def compare_named_values(
    label: str,
    names: tuple[str, ...],
    left: dict[str, int],
    right: dict[str, int],
) -> list[str]:
    errors: list[str] = []
    for name in names:
        if name not in left:
            errors.append(f"{label}: missing Verilog {name}")
            continue
        if name not in right:
            errors.append(f"{label}: missing VHDL {name}")
            continue
        if left[name] != right[name]:
            errors.append(f"{label}: {name} mismatch, Verilog={left[name]} VHDL={right[name]}")
    return errors


def check_static_parity() -> bool:
    errors: list[str] = []
    for core in CORES:
        verilog_text = core.verilog.read_text(encoding="utf-8")
        vhdl_text = core.vhdl.read_text(encoding="utf-8")
        errors.extend(
            compare_named_values(
                f"{core.name} parameter",
                core.parameters,
                parse_verilog_parameters(verilog_text),
                parse_vhdl_generics(vhdl_text),
            )
        )
        errors.extend(
            compare_named_values(
                f"{core.name} register",
                core.constants,
                parse_verilog_constants(verilog_text),
                parse_vhdl_constants(vhdl_text),
            )
        )

    if errors:
        print("[hdl-parity] static parity failed:")
        for error in errors:
            print(f"  - {error}")
        return False
    print(f"[hdl-parity] static parity passed for {len(CORES)} translated core(s).")
    return True


def run_cmd(cmd: list[str], label: str) -> bool:
    print(f"[hdl-parity] {label}: {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=ROOT, text=True)
    if result.returncode != 0:
        print(f"[hdl-parity] FAILED: {label}")
        return False
    return True


def run_sim_parity() -> bool:
    ok = True
    ok &= run_cmd(
        [sys.executable, "sim/run_sim.py", *VERILOG_PARITY_TESTS],
        "source Verilog regressions",
    )
    ok &= run_cmd(
        [sys.executable, "sim/run_vhdl_sim.py", *VHDL_PARITY_TESTS],
        "translated VHDL regressions",
    )
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="only check generic/register-map parity",
    )
    parser.add_argument(
        "--sim-only",
        action="store_true",
        help="only run Verilog and VHDL parity simulations",
    )
    args = parser.parse_args()

    if args.static_only and args.sim_only:
        parser.error("--static-only and --sim-only are mutually exclusive")

    ok = True
    if not args.sim_only:
        ok &= check_static_parity()
    if not args.static_only:
        ok &= run_sim_parity()

    if not ok:
        sys.exit(1)
    print("[hdl-parity] Verilog/VHDL parity checks passed.")


if __name__ == "__main__":
    main()
