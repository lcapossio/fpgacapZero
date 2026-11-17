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
class AsyncFifoXpmResetRtlTests(unittest.TestCase):
    """The XPM FIFO's single rst stays synchronous to wr_clk, whichever
    domain the reset came from, and gates writes while it is held."""

    def test_xpm_reset_is_synchronous_to_wr_clk(self):
        with tempfile.TemporaryDirectory(prefix="async-fifo-xpm-rst-") as tmpdir:
            vvp = Path(tmpdir) / "async_fifo_xpm_rst.vvp"
            sources = [
                str(ROOT / "tb" / "fcapz_async_fifo_xpm_rst_tb.sv"),
                str(ROOT / "rtl" / "fcapz_async_fifo.v"),
                str(ROOT / "tb" / "xpm_fifo_async_stub.v"),
            ]
            compile_result = subprocess.run(
                ["iverilog", "-g2012", "-o", str(vvp)] + sources,
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
            self.assertIn("PASS: XPM reset is synchronous to wr_clk", output, output)


if __name__ == "__main__":
    unittest.main()
