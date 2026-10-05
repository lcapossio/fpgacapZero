# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTY = ROOT / "examples" / "arty_a7"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_arty_verilog_and_vhdl_tops_expose_same_validation_blocks() -> None:
    verilog_top = _read(ARTY / "arty_a7_top.v")
    vhdl_top = _read(ARTY / "arty_a7_top.vhd")

    markers = {
        "managed ELA/EIO hub": "fcapz_debug_multi_xilinx7",
        "EJTAG-AXI bridge": "fcapz_ejtagaxi_xilinx7",
        "AXI test slave": "axi4_test_slave",
        "AXI monitor": "fcapz_axi_mon_xilinx7",
    }
    for label, marker in markers.items():
        assert marker in verilog_top, f"Verilog Arty top missing {label}"
        assert marker in vhdl_top, f"VHDL Arty top missing {label}"

    verilog_monitor = re.search(
        r"fcapz_axi_mon_xilinx7\s*#\s*\((?P<params>.*?)\)\s*u_axi_mon",
        verilog_top,
        re.S,
    )
    assert verilog_monitor is not None
    assert ".CTRL_CHAIN(2)" in verilog_monitor.group("params")
    assert ".DECODE_EN(1)" in verilog_monitor.group("params")

    vhdl_monitor = re.search(
        r"u_axi_mon\s*:\s*fcapz_axi_mon_xilinx7\s*generic\s+map\s*\((?P<params>.*?)\)",
        vhdl_top,
        re.S | re.I,
    )
    assert vhdl_monitor is not None
    vhdl_params = re.sub(r"\s+", "", vhdl_monitor.group("params"))
    assert "CTRL_CHAIN=>2" in vhdl_params
    assert "DECODE_EN=>1" in vhdl_params


def test_arty_vhdl_build_and_freshness_lists_include_monitor_sources() -> None:
    # The Verilog/MicroBlaze build compiles the Verilog monitor core; the VHDL
    # build compiles the VHDL monitor entity instead. Both compile the Xilinx-7
    # TAP wrapper. Assert each build actually *lists* the monitor source it uses
    # (a path that appears only in an explanatory comment would not satisfy this,
    # since the checked paths differ per build and never appear as comments).
    verilog_build = _read(ARTY / "build_arty.tcl").replace("\\", "/")
    for source in ("rtl/fcapz_axi_mon.v", "rtl/fcapz_axi_mon_xilinx7.v"):
        assert source in verilog_build, f"build_arty.tcl missing {source}"

    vhdl_build = _read(ARTY / "build_arty_vhdl.tcl").replace("\\", "/")
    for source in ("rtl/vhdl/core/fcapz_axi_mon.vhd", "rtl/fcapz_axi_mon_xilinx7.v"):
        assert source in vhdl_build, f"build_arty_vhdl.tcl missing {source}"

    # Freshness manifests must list the monitor source each variant actually
    # builds: the Verilog list the .v core, the VHDL list the .vhd entity.
    hw_test = _read(ARTY / "test_hw_integration.py")
    for source in ("fcapz_axi_mon.v", "fcapz_axi_mon_xilinx7.v"):
        pattern = rf'_ROOT\s*/\s*"rtl"\s*/\s*"{re.escape(source)}"'
        assert re.search(pattern, hw_test), f"test_hw_integration.py missing rtl/{source}"
    assert re.search(
        r'_ROOT\s*/\s*"rtl"\s*/\s*"vhdl"\s*/\s*"core"\s*/\s*"fcapz_axi_mon\.vhd"',
        hw_test,
    ), "test_hw_integration.py VHDL list missing rtl/vhdl/core/fcapz_axi_mon.vhd"
