# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Equivalence test: fcapz_async_fifo behavioral vs XPM-stub variants.

Compiles and runs tb/fcapz_async_fifo_equiv_tb.v with Icarus Verilog.
Skipped automatically when iverilog is not on PATH.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("iverilog"), "iverilog not on PATH")
class AsyncFifoEquivTests(unittest.TestCase):
    """Simulate both FIFO variants side-by-side and assert identical outputs."""

    def test_behavioral_matches_xpm_stub(self):
        with tempfile.TemporaryDirectory() as tmp:
            vvp = Path(tmp) / "fifo_equiv_tb.vvp"
            sources = [
                str(ROOT / "tb" / "fcapz_async_fifo_equiv_tb.v"),
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
                timeout=30,
            )
            output = sim_result.stdout + sim_result.stderr
            self.assertNotIn(
                "MISMATCH",
                output,
                f"FIFO equivalence mismatch detected:\n{output}",
            )
            self.assertIn(
                "PASS",
                output,
                f"Expected PASS in simulation output:\n{output}",
            )
