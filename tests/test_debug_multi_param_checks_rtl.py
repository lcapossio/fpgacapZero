# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""fcapz_debug_multi rejects per-slot overrides wider than the scalar shape.

Each case instantiates fcapz_debug_multi_xilinx7, so the overrides also have
to reach fcapz_debug_multi_core through every layer.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"

SOURCES = [
    RTL / "fcapz_debug_multi_xilinx7.v",
    RTL / "fcapz_debug_multi.v",
    RTL / "fcapz_debug_multi_core.v",
    RTL / "fcapz_core_manager.v",
    RTL / "jtag_pipe_iface.v",
    RTL / "reset_sync.v",
    RTL / "fcapz_ela.v",
    RTL / "dpram.v",
    RTL / "trig_compare.v",
    RTL / "fcapz_eio.v",
    RTL / "jtag_tap" / "jtag_tap_xilinx7.v",
    ROOT / "sim" / "bscane2_stub.v",
]

# name -> (parameter overrides, expected $error text or None for a clean shape)
CASES = {
    "clean_hetero": (
        ".SAMPLE_W(8), .DEPTH(64), .TIMESTAMP_W(16), .EIO_IN_W(4), .EIO_OUT_W(4),"
        " .ELA_SAMPLE_WS({32'd4, 32'd8}), .ELA_DEPTHS({32'd16, 32'd64}),"
        " .ELA_TIMESTAMP_WS({32'd0, 32'd16}), .EIO_IN_WS(32'd2), .EIO_OUT_WS(32'd3)",
        None,
    ),
    "ela_sample_w": (
        ".SAMPLE_W(8), .ELA_SAMPLE_WS({32'd16, 32'd8})",
        "ELA 1 SAMPLE_W 16 exceeds scalar SAMPLE_W 8",
    ),
    "ela_probe_w": (
        ".SAMPLE_W(8), .ELA_PROBE_MUX_WS({32'd0, 32'd12})",
        "ELA 0 probe width 12 exceeds scalar slot width 8",
    ),
    "ela_timestamp_w": (
        ".TIMESTAMP_W(0), .ELA_TIMESTAMP_WS({32'd16, 32'd0})",
        "ELA 1 TIMESTAMP_W 16 exceeds scalar TIMESTAMP_W 0",
    ),
    "ela_depth": (
        ".DEPTH(64), .ELA_DEPTHS({32'd64, 32'd256})",
        "ELA 0 DEPTH 256 exceeds scalar DEPTH 64",
    ),
    "eio_in_w": (
        ".EIO_IN_W(2), .EIO_IN_WS(32'd5)",
        "EIO 0 IN_W 5 exceeds scalar EIO_IN_W 2",
    ),
    "eio_out_w": (
        ".EIO_OUT_W(2), .EIO_OUT_WS(32'd7)",
        "EIO 0 OUT_W 7 exceeds scalar EIO_OUT_W 2",
    ),
}

HARNESS = """`timescale 1ns/1ps
module param_check_top;
    fcapz_debug_multi_xilinx7 #({params}) dut (
        .ela_sample_clk(2'b00), .ela_sample_rst(2'b00), .ela_trigger_in(2'b00)
    );
    initial #1 $finish;
endmodule
"""


@unittest.skipUnless(shutil.which("iverilog"), "iverilog not on PATH")
@unittest.skipUnless(shutil.which("vvp"), "vvp not on PATH")
class DebugMultiParamCheckTests(unittest.TestCase):
    def test_oversized_slot_overrides_are_reported(self):
        with tempfile.TemporaryDirectory(prefix="debug-multi-params-") as tmpdir:
            for name, (params, expected) in CASES.items():
                with self.subTest(case=name):
                    top = Path(tmpdir) / f"{name}.v"
                    top.write_text(HARNESS.format(params=params), encoding="utf-8")
                    vvp = Path(tmpdir) / f"{name}.vvp"
                    compile_result = subprocess.run(
                        ["iverilog", "-g2012", "-I", str(RTL), "-s", "param_check_top",
                         "-o", str(vvp), str(top)] + [str(s) for s in SOURCES],
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        compile_result.returncode, 0,
                        f"iverilog compilation failed:\n{compile_result.stderr}",
                    )
                    sim = subprocess.run(
                        ["vvp", "-n", str(vvp)], capture_output=True, text=True, timeout=120
                    )
                    output = sim.stdout + sim.stderr
                    if expected is None:
                        self.assertNotIn("fcapz_debug_multi:", output, output)
                    else:
                        self.assertIn(f"fcapz_debug_multi: {expected}", output, output)
