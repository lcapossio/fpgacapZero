# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("iverilog"), "iverilog not on PATH")
@unittest.skipUnless(shutil.which("vvp"), "vvp not on PATH")
class ElaBugProbeRtlTests(unittest.TestCase):
    def test_trig_holdoff_has_single_procedural_driver_region(self):
        """Synthesis rejects trig_holdoff when it is assigned in two always blocks."""
        rtl = (ROOT / "rtl" / "fcapz_ela.v").read_text()
        blocks = re.split(r"\n\s*always\s*@", rtl)
        driver_blocks = [
            block
            for block in blocks
            if re.search(r"(?<![A-Za-z0-9_])trig_holdoff\s*<=", block)
        ]
        self.assertEqual(len(driver_blocks), 1)

    def test_focused_ela_regressions(self):
        with tempfile.TemporaryDirectory(prefix="ela-bug-probe-") as tmpdir:
            vvp = Path(tmpdir) / "fcapz_ela_bug_probe_tb.vvp"
            sources = [
                str(ROOT / "tb" / "fcapz_ela_bug_probe_tb.sv"),
                str(ROOT / "rtl" / "fcapz_ela.v"),
                str(ROOT / "rtl" / "dpram.v"),
                str(ROOT / "rtl" / "trig_compare.v"),
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
                ["vvp", str(vvp)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = sim_result.stdout + sim_result.stderr
            self.assertEqual(
                sim_result.returncode,
                0,
                f"ELA bug-probe simulation failed:\n{output}",
            )
            self.assertIn(
                "Regression summary:",
                output,
                f"expected regression summary in simulation output:\n{output}",
            )
            self.assertIn(
                "0 failed",
                output,
                f"expected all focused ELA regressions to pass:\n{output}",
            )
