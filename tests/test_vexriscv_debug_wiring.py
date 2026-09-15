# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Guard the VexRiscv CPU-debug plumbing against drift across the three tops.

The debug path (BSCANE2/sld_virtual_jtag tunnel -> VexRiscv_EmbeddedJtag DTM)
is threaded through several files by hand -- the vendored core, the two vendor
tunnel adapters, vex_cpu, the three tops, and the three build scripts. These
static checks catch the easy ways that thread can break (a renamed port, a
core swap that forgets a file, a chain-index typo) without needing hardware.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "examples" / "common" / "vexriscv"
ARTY = ROOT / "examples" / "arty_a7"
DE25 = ROOT / "examples" / "de25_nano"

# The tunnel signals vex_cpu exposes and every adapter/top must agree on.
_JI_PORTS = ("ji_tdi", "ji_enable", "ji_capture", "ji_shift", "ji_update",
             "ji_reset", "ji_tdo")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_debug_core_module_name_and_tunnel_ports() -> None:
    core = _read(ROOT / "third_party" / "vexriscv" / "VexRiscv_EmbeddedJtag.v")
    assert "module VexRiscv_EmbeddedJtag" in core
    # No-TAP tunnel + debug controls the wrappers/vex_cpu bind to.
    for port in ("jtagInstruction_tdi", "jtagInstruction_tdo", "ndmreset",
                 "debugReset", "jtag_clk"):
        assert port in core, f"vendored debug core missing port {port}"


def test_vex_cpu_selects_debug_core_by_generate() -> None:
    cpu = _read(COMMON / "vex_cpu.v")
    assert "DEBUG_EN" in cpu
    assert "VexRiscv_EmbeddedJtag u_core" in cpu   # debug branch
    assert "VexRiscv u_core" in cpu                # default (Lite) branch
    for port in (*_JI_PORTS, "debugReset", "ndmreset", "jtag_clk"):
        assert port in cpu, f"vex_cpu missing tunnel port {port}"


def test_xilinx_tunnel_adapter_bscane2_user3_with_reset() -> None:
    w = _read(COMMON / "vex_jtag_bscan_xilinx7.v")
    assert "BSCANE2" in w
    assert "parameter CHAIN = 3" in w              # USER3 by default
    # The RESET gotcha: this adapter must wire BSCANE2.RESET (unlike the fcapz
    # TAP wrapper), else the tunnel has no defined reset state.
    assert ".RESET" in w and "ji_reset" in w
    for port in _JI_PORTS:
        assert port in w


def test_intel_tunnel_adapter_vjtag_index6() -> None:
    w = _read(COMMON / "vex_jtag_bscan_intel.v")
    assert "sld_virtual_jtag" in w
    assert "parameter CHAIN = 6" in w              # first free vJTAG index
    for state in ("virtual_state_cdr", "virtual_state_sdr", "virtual_state_udr"):
        assert state in w
    for port in _JI_PORTS:
        assert port in w


def test_arty_verilog_top_debug_on_user3() -> None:
    top = _read(ARTY / "arty_a7_vex_top.v")
    assert "DEBUG_EN" in top
    assert "vex_jtag_bscan_xilinx7 #(.CHAIN(3))" in top
    # ndmreset stays isolated: it is captured (dbg_ndmreset) but must not appear
    # in either reset-source expression that drives the shared fabric.
    assert "dbg_ndmreset" in top
    for line in top.splitlines():
        if "rst_100_async" in line and "=" in line and "assign" in line:
            assert "ndmreset" not in line
        if "wire rst_100 " in line:
            assert "ndmreset" not in line


def test_arty_vhdl_top_debug_on_user3() -> None:
    top = _read(ARTY / "arty_a7_top.vhd")
    assert "DEBUG_EN" in top
    assert "vex_jtag_bscan_xilinx7" in top
    assert "CHAIN => 3" in top


def test_de25_top_debug_on_index6() -> None:
    top = _read(DE25 / "de25_nano_vex_top.v")
    assert "DEBUG_EN" in top
    assert "vex_jtag_bscan_intel #(.CHAIN(6))" in top


def test_build_scripts_swap_core_and_set_debug() -> None:
    # Each variant build must (a) react to FCAPZ_VEX_DEBUG, (b) compile the
    # EmbeddedJtag core (not Lite) + the matching tunnel adapter in debug mode,
    # and (c) turn on DEBUG_EN on the top.
    checks = {
        ARTY / "build_arty_vex.tcl": ("vex_jtag_bscan_xilinx7.v", "DEBUG_EN=1"),
        ARTY / "build_arty_vhdl.tcl": ("vex_jtag_bscan_xilinx7.v", "DEBUG_EN=1"),
        DE25 / "build_de25_nano_vex.tcl": ("vex_jtag_bscan_intel.v",
                                           "set_parameter -name DEBUG_EN 1"),
    }
    for path, (adapter, debug_set) in checks.items():
        text = _read(path)
        assert "FCAPZ_VEX_DEBUG" in text, f"{path.name} ignores FCAPZ_VEX_DEBUG"
        assert "VexRiscv_EmbeddedJtag.v" in text, f"{path.name} misses debug core"
        assert adapter in text, f"{path.name} misses {adapter}"
        assert debug_set in text, f"{path.name} does not set DEBUG_EN"
