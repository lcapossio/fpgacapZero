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
@unittest.skipUnless(shutil.which("vvp"), "vvp not on PATH")
class EjtagUartRtlTests(unittest.TestCase):
    """RTL smoke test for the EJTAG-UART shared async FIFO user."""

    def test_uart_bridge_tb(self):
        with tempfile.TemporaryDirectory(prefix="ejtaguart-") as tmpdir:
            vvp = Path(tmpdir) / "fcapz_ejtaguart_tb.vvp"
            sources = [
                str(ROOT / "tb" / "fcapz_ejtaguart_tb.sv"),
                str(ROOT / "rtl" / "fcapz_ejtaguart.v"),
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
                ["vvp", str(vvp)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = sim_result.stdout + sim_result.stderr
            self.assertEqual(
                sim_result.returncode,
                0,
                f"EJTAG-UART simulation failed:\n{output}",
            )
            self.assertIn("EJTAGUART TB:", output)
            self.assertIn("0 failed", output)
