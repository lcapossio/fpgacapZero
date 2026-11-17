# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
"""The post-synthesis insertion wrapper (tools/fcapz_insert_wrap.v) elaborates
for 7-series and UltraScale, and its cross-triggers deliver one pulse per
trigger between clocks of any speed."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

RTL = [
    "reset_sync.v", "dpram.v", "trig_compare.v", "fcapz_ela.v", "fcapz_eio.v",
    "fcapz_core_manager.v", "fcapz_debug_multi_core.v", "fcapz_hub_reset.v",
    "fcapz_debug_multi.v", "fcapz_debug_multi_xilinx7.v",
    "fcapz_debug_multi_xilinxus.v", "jtag_reg_iface.v", "jtag_pipe_iface.v",
    "jtag_burst_read.v", "jtag_tap/jtag_tap_xilinx7.v",
    "jtag_tap/jtag_tap_xilinxus.v", "dff_sync.v", "dff_reg_sync.v",
    "fcapz_async_fifo.v",
]


def _tcl_sources() -> list[str]:
    """The RTL list tools/fcapz_insert_vivado.tcl synthesizes."""
    text = (ROOT / "tools" / "fcapz_insert_vivado.tcl").read_text(encoding="utf-8")
    body = text.split("set fcapz::rtl_sources {", 1)[1].split("}", 1)[0]
    return body.split()


def test_tcl_and_test_list_the_same_rtl() -> None:
    assert sorted(_tcl_sources()) == sorted(RTL)


@pytest.mark.skipif(
    shutil.which("iverilog") is None or shutil.which("vvp") is None,
    reason="iverilog/vvp not installed",
)
@pytest.mark.parametrize("ultrascale", [False, True])
def test_cross_trigger_one_pulse_per_trigger(tmp_path: Path, ultrascale: bool) -> None:
    out = tmp_path / "insert_wrap_tb.vvp"
    cmd = ["iverilog", "-g2012", "-I", str(ROOT / "rtl"), "-o", str(out)]
    if ultrascale:
        cmd.append("-DULTRASCALE")
    cmd += [
        str(ROOT / "tb" / "fcapz_insert_wrap_tb.sv"),
        str(ROOT / "tools" / "fcapz_insert_wrap.v"),
        str(ROOT / "sim" / "bscane2_stub.v"),
        str(ROOT / "tb" / "xpm_fifo_async_stub.v"),
        *(str(ROOT / "rtl" / f) for f in RTL),
    ]
    subprocess.run(cmd, check=True, cwd=ROOT)
    result = subprocess.run(
        ["vvp", str(out)], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    assert "PASS" in result.stdout, result.stdout[-3000:]
    assert "FAIL" not in result.stdout, result.stdout[-3000:]
