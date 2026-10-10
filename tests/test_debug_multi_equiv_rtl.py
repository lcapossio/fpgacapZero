# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""fcapz_debug_multi_xilinx7 after the vendor-free split matches its frozen
pre-split copy on every TCK, for each parameter shape the bench knows."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"

SOURCES = [
    ROOT / "tb" / "fcapz_debug_multi_equiv_tb.sv",
    ROOT / "tb" / "legacy" / "fcapz_debug_multi_xilinx7_ref.v",
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

# tb/fcapz_debug_multi_equiv_tb.sv's SHAPE parameter
SHAPES = {
    0: "default",
    1: "heterogeneous slots + timestamps",
    2: "EIO only",
    3: "dependent defaults",
    4: "segments + timestamps",
    5: "4-bit samples",
}


@unittest.skipUnless(shutil.which("iverilog"), "iverilog not on PATH")
@unittest.skipUnless(shutil.which("vvp"), "vvp not on PATH")
class DebugMultiEquivalenceRtlTests(unittest.TestCase):
    def test_split_wrapper_matches_the_pre_split_wrapper(self):
        with tempfile.TemporaryDirectory(prefix="debug-multi-equiv-") as tmpdir:
            for shape, label in SHAPES.items():
                with self.subTest(shape=label):
                    vvp = Path(tmpdir) / f"equiv{shape}.vvp"
                    compile_result = subprocess.run(
                        ["iverilog", "-g2012", "-I", str(RTL), "-I", str(ROOT / "tb"),
                         f"-Pfcapz_debug_multi_equiv_tb.SHAPE={shape}",
                         "-s", "fcapz_debug_multi_equiv_tb", "-o", str(vvp)]
                        + [str(s) for s in SOURCES],
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        compile_result.returncode, 0,
                        f"iverilog compilation failed:\n{compile_result.stderr}",
                    )
                    sim = subprocess.run(
                        ["vvp", "-n", str(vvp)], capture_output=True, text=True, timeout=600
                    )
                    output = sim.stdout + sim.stderr
                    self.assertEqual(sim.returncode, 0, f"simulation failed:\n{output}")
                    self.assertIn(f"SHAPE={shape}: ", output, output)
                    self.assertIn(" 0 failed ===", output, output)
                    self.assertIn("0 mismatches", output, output)
