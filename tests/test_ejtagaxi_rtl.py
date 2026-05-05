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
class EjtagAxiRtlTests(unittest.TestCase):
    """RTL smoke tests for EJTAG-AXI FIFO parameter variants."""

    def _run_tb(self, name: str, params: dict[str, str | int] | None = None):
        with tempfile.TemporaryDirectory(prefix=f"ejtagaxi-{name}-") as tmpdir:
            vvp = Path(tmpdir) / "fcapz_ejtagaxi_reset_regression_tb.vvp"
            sources = [
                str(ROOT / "tb" / "fcapz_ejtagaxi_reset_regression_tb.sv"),
                str(ROOT / "tb" / "axi4_test_slave.v"),
                str(ROOT / "rtl" / "fcapz_ejtagaxi.v"),
                str(ROOT / "rtl" / "fcapz_async_fifo.v"),
                str(ROOT / "tb" / "xpm_fifo_async_stub.v"),
            ]
            cmd = ["iverilog", "-g2012", "-I", str(ROOT / "rtl")]
            for key, value in (params or {}).items():
                cmd.extend(["-P", f"fcapz_ejtagaxi_reset_regression_tb.{key}={value}"])
            cmd.extend(["-o", str(vvp)])
            cmd.extend(sources)
            compile_result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(
                compile_result.returncode,
                0,
                f"iverilog compilation failed for {name}:\n{compile_result.stderr}",
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
                f"EJTAG-AXI simulation failed for {name}:\n{output}",
            )
            self.assertIn("PASS: reset regression", output)

    def test_default_fifo_parameters(self):
        self._run_tb("default")

    def test_xpm_asymmetric_fifo_depths_distributed_command_queue(self):
        self._run_tb(
            "xpm-asymmetric",
            {
                "USE_BEHAV_ASYNC_FIFO": 0,
                "ASYNC_FIFO_IMPL": 1,
                "CMD_FIFO_DEPTH": 16,
                "RESP_FIFO_DEPTH": 64,
                "CMD_FIFO_MEMORY_TYPE": '"distributed"',
                "RESP_FIFO_MEMORY_TYPE": '"block"',
                "BURST_FIFO_MEMORY_TYPE": '"distributed"',
            },
        )

    def test_xpm_rejects_depth_below_16(self):
        with tempfile.TemporaryDirectory(prefix="ejtagaxi-bad-depth-") as tmpdir:
            vvp = Path(tmpdir) / "fcapz_ejtagaxi_bad_depth_tb.vvp"
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
                    "fcapz_ejtagaxi_reset_regression_tb.USE_BEHAV_ASYNC_FIFO=0",
                    "-P",
                    "fcapz_ejtagaxi_reset_regression_tb.ASYNC_FIFO_IMPL=1",
                    "-P",
                    "fcapz_ejtagaxi_reset_regression_tb.CMD_FIFO_DEPTH=8",
                    "-o",
                    str(vvp),
                ]
                + sources,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(compile_result.returncode, 0)
            self.assertIn(
                "XPM_FIFO_DEPTH_must_be_at_least_16",
                compile_result.stderr + compile_result.stdout,
            )
