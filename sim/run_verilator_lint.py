#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Run the full-project Verilog RTL matrix through Verilator lint.

The iverilog pass in sim/run_sim.py remains the broad elaboration and
simulation gate. This script adds Verilator's stricter procedural-driver
analysis across the project Verilog RTL surface, including MULTIDRIVEN
warnings for one reg assigned by more than one always block.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"
SIM = ROOT / "sim"

STUBS = (
    SIM / "bscane2_stub.v",
    SIM / "xpm_fifo_async_stub.v",
    SIM / "ujtag_stub.v",
    SIM / "gw_jtag_stub.v",
    SIM / "jtagg_stub.v",
    SIM / "sld_virtual_jtag_stub.v",
)

ELA_CORE = (
    RTL / "reset_sync.v",
    RTL / "dpram.v",
    RTL / "trig_compare.v",
    RTL / "fcapz_ela.v",
)

EIO_CORE = (
    RTL / "fcapz_eio.v",
)

EJTAG_AXI_CORE = (
    RTL / "fcapz_async_fifo.v",
    RTL / "fcapz_ejtagaxi.v",
)

EJTAG_UART_CORE = (
    RTL / "fcapz_async_fifo.v",
    RTL / "fcapz_ejtaguart.v",
)

JTAG_REG_SOURCES = (
    RTL / "reset_sync.v",
    RTL / "jtag_reg_iface.v",
)

ELA_WRAPPER_SOURCES = (
    *ELA_CORE,
    RTL / "jtag_reg_iface.v",
    RTL / "jtag_burst_read.v",
    RTL / "fcapz_eio.v",
    RTL / "fcapz_regbus_mux.v",
)

EJTAG_AXI_WRAPPER_SOURCES = (
    RTL / "reset_sync.v",
    RTL / "jtag_pipe_iface.v",
    *EJTAG_AXI_CORE,
)

EJTAG_UART_WRAPPER_SOURCES = (
    RTL / "reset_sync.v",
    RTL / "jtag_pipe_iface.v",
    *EJTAG_UART_CORE,
)


@dataclass(frozen=True)
class LintTarget:
    name: str
    top: str
    sources: tuple[Path, ...]


TARGETS = (
    LintTarget(
        name="dpram",
        top="dpram",
        sources=(RTL / "dpram.v",),
    ),
    LintTarget(
        name="reset_sync",
        top="reset_sync",
        sources=(RTL / "reset_sync.v",),
    ),
    LintTarget(
        name="trig_compare",
        top="trig_compare",
        sources=(RTL / "trig_compare.v",),
    ),
    LintTarget(
        name="jtag_reg_iface",
        top="jtag_reg_iface",
        sources=(RTL / "jtag_reg_iface.v",),
    ),
    LintTarget(
        name="jtag_burst_read",
        top="jtag_burst_read",
        sources=(RTL / "jtag_burst_read.v",),
    ),
    LintTarget(
        name="jtag_pipe_iface",
        top="jtag_pipe_iface",
        sources=(RTL / "jtag_pipe_iface.v",),
    ),
    LintTarget(
        name="fcapz_async_fifo",
        top="fcapz_async_fifo",
        sources=(SIM / "xpm_fifo_async_stub.v", RTL / "fcapz_async_fifo.v"),
    ),
    LintTarget(
        name="fcapz_regbus_mux",
        top="fcapz_regbus_mux",
        sources=(RTL / "fcapz_regbus_mux.v",),
    ),
    LintTarget(
        name="fcapz_ela",
        top="fcapz_ela",
        sources=ELA_CORE,
    ),
    LintTarget(
        name="fcapz_eio",
        top="fcapz_eio",
        sources=EIO_CORE,
    ),
    LintTarget(
        name="fcapz_ejtagaxi",
        top="fcapz_ejtagaxi",
        sources=EJTAG_AXI_CORE,
    ),
    LintTarget(
        name="fcapz_ejtaguart",
        top="fcapz_ejtaguart",
        sources=EJTAG_UART_CORE,
    ),
    LintTarget(
        name="jtag_tap_xilinx7",
        top="jtag_tap_xilinx7",
        sources=(SIM / "bscane2_stub.v", RTL / "jtag_tap" / "jtag_tap_xilinx7.v"),
    ),
    LintTarget(
        name="jtag_tap_xilinxus",
        top="jtag_tap_xilinxus",
        sources=(SIM / "bscane2_stub.v", RTL / "jtag_tap" / "jtag_tap_xilinxus.v"),
    ),
    LintTarget(
        name="jtag_tap_polarfire",
        top="jtag_tap_polarfire",
        sources=(SIM / "ujtag_stub.v", RTL / "jtag_tap" / "jtag_tap_polarfire.v"),
    ),
    LintTarget(
        name="jtag_tap_gowin",
        top="jtag_tap_gowin",
        sources=(SIM / "gw_jtag_stub.v", RTL / "jtag_tap" / "jtag_tap_gowin.v"),
    ),
    LintTarget(
        name="jtag_tap_ecp5",
        top="jtag_tap_ecp5",
        sources=(SIM / "jtagg_stub.v", RTL / "jtag_tap" / "jtag_tap_ecp5.v"),
    ),
    LintTarget(
        name="jtag_tap_intel",
        top="jtag_tap_intel",
        sources=(
            SIM / "sld_virtual_jtag_stub.v",
            RTL / "jtag_tap" / "jtag_tap_intel.v",
        ),
    ),
    LintTarget(
        name="fcapz_ela_xilinx7",
        top="fcapz_ela_xilinx7",
        sources=(
            SIM / "bscane2_stub.v",
            *ELA_WRAPPER_SOURCES,
            RTL / "jtag_tap" / "jtag_tap_xilinx7.v",
            RTL / "fcapz_ela_xilinx7.v",
        ),
    ),
    LintTarget(
        name="lint_eio_en_xilinx7",
        top="lint_eio_en_xilinx7",
        sources=(
            SIM / "bscane2_stub.v",
            *ELA_WRAPPER_SOURCES,
            RTL / "jtag_tap" / "jtag_tap_xilinx7.v",
            RTL / "fcapz_ela_xilinx7.v",
            SIM / "lint_eio_en_xilinx7.v",
        ),
    ),
    LintTarget(
        name="fcapz_eio_xilinx7",
        top="fcapz_eio_xilinx7",
        sources=(
            SIM / "bscane2_stub.v",
            *JTAG_REG_SOURCES,
            *EIO_CORE,
            RTL / "jtag_tap" / "jtag_tap_xilinx7.v",
            RTL / "fcapz_eio_xilinx7.v",
        ),
    ),
    LintTarget(
        name="fcapz_ejtagaxi_xilinx7",
        top="fcapz_ejtagaxi_xilinx7",
        sources=(
            SIM / "bscane2_stub.v",
            SIM / "xpm_fifo_async_stub.v",
            *EJTAG_AXI_WRAPPER_SOURCES,
            RTL / "jtag_tap" / "jtag_tap_xilinx7.v",
            RTL / "fcapz_ejtagaxi_xilinx7.v",
        ),
    ),
    LintTarget(
        name="fcapz_ejtaguart_xilinx7",
        top="fcapz_ejtaguart_xilinx7",
        sources=(
            SIM / "bscane2_stub.v",
            SIM / "xpm_fifo_async_stub.v",
            *EJTAG_UART_WRAPPER_SOURCES,
            RTL / "jtag_tap" / "jtag_tap_xilinx7.v",
            RTL / "fcapz_ejtaguart_xilinx7.v",
        ),
    ),
    LintTarget(
        name="fcapz_ela_xilinxus",
        top="fcapz_ela_xilinxus",
        sources=(
            SIM / "bscane2_stub.v",
            *ELA_WRAPPER_SOURCES,
            RTL / "jtag_tap" / "jtag_tap_xilinxus.v",
            RTL / "fcapz_ela_xilinxus.v",
        ),
    ),
    LintTarget(
        name="fcapz_eio_xilinxus",
        top="fcapz_eio_xilinxus",
        sources=(
            SIM / "bscane2_stub.v",
            *JTAG_REG_SOURCES,
            *EIO_CORE,
            RTL / "jtag_tap" / "jtag_tap_xilinxus.v",
            RTL / "fcapz_eio_xilinxus.v",
        ),
    ),
    LintTarget(
        name="fcapz_ejtagaxi_xilinxus",
        top="fcapz_ejtagaxi_xilinxus",
        sources=(
            SIM / "bscane2_stub.v",
            SIM / "xpm_fifo_async_stub.v",
            *EJTAG_AXI_WRAPPER_SOURCES,
            RTL / "jtag_tap" / "jtag_tap_xilinxus.v",
            RTL / "fcapz_ejtagaxi_xilinxus.v",
        ),
    ),
    LintTarget(
        name="fcapz_ejtaguart_xilinxus",
        top="fcapz_ejtaguart_xilinxus",
        sources=(
            SIM / "bscane2_stub.v",
            SIM / "xpm_fifo_async_stub.v",
            *EJTAG_UART_WRAPPER_SOURCES,
            RTL / "jtag_tap" / "jtag_tap_xilinxus.v",
            RTL / "fcapz_ejtaguart_xilinxus.v",
        ),
    ),
    LintTarget(
        name="fcapz_ela_polarfire",
        top="fcapz_ela_polarfire",
        sources=(
            SIM / "ujtag_stub.v",
            *ELA_WRAPPER_SOURCES,
            RTL / "jtag_tap" / "jtag_tap_polarfire.v",
            RTL / "fcapz_ela_polarfire.v",
        ),
    ),
    LintTarget(
        name="fcapz_eio_polarfire",
        top="fcapz_eio_polarfire",
        sources=(
            SIM / "ujtag_stub.v",
            *JTAG_REG_SOURCES,
            *EIO_CORE,
            RTL / "jtag_tap" / "jtag_tap_polarfire.v",
            RTL / "fcapz_eio_polarfire.v",
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
    LintTarget(
        name="fcapz_ela_ecp5",
        top="fcapz_ela_ecp5",
        sources=(
            SIM / "jtagg_stub.v",
            *ELA_WRAPPER_SOURCES,
            RTL / "jtag_tap" / "jtag_tap_ecp5.v",
            RTL / "fcapz_ela_ecp5.v",
        ),
    ),
    LintTarget(
        name="fcapz_eio_ecp5",
        top="fcapz_eio_ecp5",
        sources=(
            SIM / "jtagg_stub.v",
            *JTAG_REG_SOURCES,
            *EIO_CORE,
            RTL / "jtag_tap" / "jtag_tap_ecp5.v",
            RTL / "fcapz_eio_ecp5.v",
        ),
    ),
    LintTarget(
        name="fcapz_ela_intel",
        top="fcapz_ela_intel",
        sources=(
            SIM / "sld_virtual_jtag_stub.v",
            *ELA_CORE,
            RTL / "jtag_reg_iface.v",
            RTL / "jtag_burst_read.v",
            RTL / "jtag_tap" / "jtag_tap_intel.v",
            RTL / "fcapz_ela_intel.v",
        ),
    ),
    LintTarget(
        name="fcapz_eio_intel",
        top="fcapz_eio_intel",
        sources=(
            SIM / "sld_virtual_jtag_stub.v",
            *JTAG_REG_SOURCES,
            *EIO_CORE,
            RTL / "jtag_tap" / "jtag_tap_intel.v",
            RTL / "fcapz_eio_intel.v",
        ),
    ),
    LintTarget(
        name="fcapz_ejtagaxi_intel",
        top="fcapz_ejtagaxi_intel",
        sources=(
            SIM / "sld_virtual_jtag_stub.v",
            SIM / "xpm_fifo_async_stub.v",
            *EJTAG_AXI_WRAPPER_SOURCES,
            RTL / "jtag_tap" / "jtag_tap_intel.v",
            RTL / "fcapz_ejtagaxi_intel.v",
        ),
    ),
    LintTarget(
        name="fcapz_ejtaguart_intel",
        top="fcapz_ejtaguart_intel",
        sources=(
            SIM / "sld_virtual_jtag_stub.v",
            SIM / "xpm_fifo_async_stub.v",
            *EJTAG_UART_WRAPPER_SOURCES,
            RTL / "jtag_tap" / "jtag_tap_intel.v",
            RTL / "fcapz_ejtaguart_intel.v",
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
    "-Wno-PINCONNECTEMPTY",
    "-Wno-UNUSEDPARAM",
    "-Wno-SYNCASYNCNET",
)


def verilator_version() -> tuple[int, int] | None:
    result = subprocess.run(
        ["verilator", "--version"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None

    match = re.search(r"Verilator\s+(\d+)\.(\d+)", result.stdout + result.stderr)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def check_verilator_version() -> bool:
    version = verilator_version()
    if version is None:
        print("could not determine Verilator version", file=sys.stderr)
        return False
    if version < (5, 0):
        major, minor = version
        print(
            "Verilator 5.0 or newer is required for this lint flag set "
            f"(found {major}.{minor})",
            file=sys.stderr,
        )
        return False
    return True


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
    saw_driver_warning = (
        "MULTIDRIVEN" in output
        or ("%Warning-" in output and "multiple driving" in output and "'q'" in output)
    )
    if result.returncode == 0 or not saw_driver_warning:
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
    if not check_verilator_version():
        sys.exit(2)

    ok = run_lint()
    if args.self_test:
        ok = run_self_test() and ok

    if not ok:
        sys.exit(1)
    suffix = " and MULTIDRIVEN self-test" if args.self_test else ""
    print(f"Verilator RTL lint passed for {len(TARGETS)} target(s){suffix}.")


if __name__ == "__main__":
    main()
