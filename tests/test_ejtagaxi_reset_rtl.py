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
class EjtagAxiResetRtlTests(unittest.TestCase):
    """Focused RTL regression for reset bookkeeping and first post-reset read."""

    def _run_reset_regression(self, debug_en: int):
        with tempfile.TemporaryDirectory(prefix="ejtagaxi-reset-") as tmpdir:
            vvp = Path(tmpdir) / f"ejtagaxi_reset_regression_debug{debug_en}.vvp"
            sources = [
                str(ROOT / "tb" / "fcapz_ejtagaxi_reset_regression_tb.sv"),
                str(ROOT / "tb" / "axi4_test_slave.v"),
                str(ROOT / "rtl" / "fcapz_ejtagaxi.v"),
                str(ROOT / "rtl" / "fcapz_async_fifo.v"),
                str(ROOT / "tb" / "xpm_fifo_async_stub.v"),
            ]
            compile_result = subprocess.run(
                [
                    "iverilog",
                    "-g2012",
                    "-I",
                    str(ROOT / "rtl"),
                    "-P",
                    f"fcapz_ejtagaxi_reset_regression_tb.DEBUG_EN={debug_en}",
                    "-o",
                    str(vvp),
                ]
                + sources,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                compile_result.returncode,
                0,
                f"iverilog compilation failed for DEBUG_EN={debug_en}:\n"
                f"{compile_result.stderr}",
            )

            sim_result = subprocess.run(
                ["vvp", str(vvp)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = sim_result.stdout + sim_result.stderr
            self.assertEqual(
                sim_result.returncode,
                0,
                f"reset regression simulation failed for DEBUG_EN={debug_en}:\n{output}",
            )
            self.assertIn(
                "PASS: reset regression",
                output,
                f"expected PASS banner in DEBUG_EN={debug_en} simulation output:\n{output}",
            )

    def test_reset_drain_and_first_read_regression_debug_disabled(self):
        self._run_reset_regression(0)

    def test_reset_drain_and_first_read_regression_debug_enabled(self):
        self._run_reset_regression(1)
