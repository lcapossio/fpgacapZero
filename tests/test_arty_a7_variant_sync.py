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
    required_files = (
        "fcapz_axi_mon.v",
        "fcapz_axi_mon_xilinx7.v",
    )

    for file in (ARTY / "build_arty.tcl", ARTY / "build_arty_vhdl.tcl"):
        text = _read(file).replace("\\", "/")
        for source in required_files:
            assert f"rtl/{source}" in text, f"{file.relative_to(ROOT)} missing rtl/{source}"

    hw_test = _read(ARTY / "test_hw_integration.py")
    for source in required_files:
        pattern = rf'_ROOT\s*/\s*"rtl"\s*/\s*"{re.escape(source)}"'
        assert re.search(pattern, hw_test), f"test_hw_integration.py missing rtl/{source}"
