# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TB = "fcapz_ejtagaxi_stream_tb"
DRAIN_TB = "fcapz_ejtagaxi_drain_tb"


@unittest.skipUnless(shutil.which("iverilog"), "iverilog not on PATH")
@unittest.skipUnless(shutil.which("vvp"), "vvp not on PATH")
class EjtagAxiStreamRtlTests(unittest.TestCase):
    """RTL tests for the EJTAG-AXI streaming read (CMD_STREAM_RSTART)."""

    def _run_tb(self, name: str, params: dict[str, str | int] | None = None,
                tb: str = TB, expect: str = "PASS: stream"):
        with tempfile.TemporaryDirectory(prefix=f"ejtagaxi-stream-{name}-") as tmpdir:
            vvp = Path(tmpdir) / f"{tb}.vvp"
            sources = [
                str(ROOT / "tb" / f"{tb}.sv"),
                str(ROOT / "tb" / "axi4_test_slave.v"),
                str(ROOT / "rtl" / "fcapz_ejtagaxi.v"),
                str(ROOT / "rtl" / "fcapz_async_fifo.v"),
                str(ROOT / "tb" / "xpm_fifo_async_stub.v"),
            ]
            cmd = ["iverilog", "-g2012", "-I", str(ROOT / "rtl")]
            for key, value in (params or {}).items():
                cmd.extend(["-P", f"{tb}.{key}={value}"])
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
                timeout=900,
            )
            output = sim_result.stdout + sim_result.stderr
            self.assertEqual(
                sim_result.returncode,
                0,
                f"EJTAG-AXI stream simulation failed for {name}:\n{output}",
            )
            self.assertIn(expect, output)

    def test_default_depth_16(self):
        self._run_tb("default")

    def test_depth_256_behavioral_fifo(self):
        self._run_tb("d256", {"FIFO_DEPTH": 256})

    def test_depth_256_xpm_slave_stalls(self):
        self._run_tb(
            "d256-xpm-stall",
            {"FIFO_DEPTH": 256, "USE_BEHAV_ASYNC_FIFO": 0, "STALL_CYCLES": 3},
        )

    def test_fast_tck_slow_axi(self):
        self._run_tb("fast-tck", {"FIFO_DEPTH": 256, "TCK_HALF_NS": 3, "STALL_CYCLES": 1})

    def test_burst_stuck_past_the_r_timeout_is_drained(self):
        # The R timeout fires before the slave answers: its late beats must
        # not become the first words of the next stream.
        self._run_tb("drain-timeout", {"STALL_CYCLES": 4300},
                     tb=DRAIN_TB, expect="PASS: drain")

    def test_r_timeout_past_12_bits_is_drained(self):
        # TIMEOUT > 4096: the timeout and drain counters must still reach it.
        self._run_tb("drain-timeout-8192", {"TIMEOUT": 8192, "STALL_CYCLES": 8600},
                     tb=DRAIN_TB, expect="PASS: drain")

    def test_burst_in_flight_at_the_abort_is_drained(self):
        self._run_tb("drain-abort",
                     {"STALL_CYCLES": 3000, "PRE_SCANS": 2, "PRE_SLOTS": 1},
                     tb=DRAIN_TB, expect="PASS: drain")


if __name__ == "__main__":
    unittest.main()
