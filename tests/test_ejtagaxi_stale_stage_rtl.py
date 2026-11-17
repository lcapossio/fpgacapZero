# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("iverilog"), "iverilog not on PATH")
class EjtagAxiStaleStageRtlTests(unittest.TestCase):
    """A command left in the TCK staging register must not survive axi_rst.

    Models a device that drops register initial values (PolarFire): the
    staging register holds a write at power-up and TCK only starts after
    axi_rst has ended.
    """

    def test_stale_staged_command_is_dropped_by_reset(self):
        with tempfile.TemporaryDirectory(prefix="ejtagaxi-stale-") as tmpdir:
            vvp = Path(tmpdir) / "ejtagaxi_stale_stage.vvp"
            sources = [
                str(ROOT / "tb" / "fcapz_ejtagaxi_stale_stage_tb.sv"),
                str(ROOT / "tb" / "axi4_test_slave.v"),
                str(ROOT / "rtl" / "fcapz_ejtagaxi.v"),
                str(ROOT / "rtl" / "fcapz_async_fifo.v"),
                str(ROOT / "tb" / "xpm_fifo_async_stub.v"),
            ]
            compile_result = subprocess.run(
                ["iverilog", "-g2012", "-I", str(ROOT / "rtl"), "-o", str(vvp)]
                + sources,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                compile_result.returncode,
                0,
                f"iverilog compilation failed:\n{compile_result.stderr}",
            )

            sim_result = subprocess.run(
                ["vvp", "-n", str(vvp)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = sim_result.stdout + sim_result.stderr
            self.assertEqual(sim_result.returncode, 0, output)
            self.assertIn("PASS: stale staged command dropped by reset", output, output)


if __name__ == "__main__":
    unittest.main()
