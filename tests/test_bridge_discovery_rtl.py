# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Discovery's identity scans are NOPs on the EJTAG-AXI and EJTAG-UART bridges."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("iverilog"), "iverilog not on PATH")
@unittest.skipUnless(shutil.which("vvp"), "vvp not on PATH")
class BridgeDiscoveryRtlTests(unittest.TestCase):
    def test_discovery_scans_leave_both_bridges_idle(self):
        with tempfile.TemporaryDirectory(prefix="bridge-discovery-") as tmpdir:
            vvp = Path(tmpdir) / "fcapz_bridge_discovery_tb.vvp"
            sources = [
                ROOT / "tb" / "fcapz_bridge_discovery_tb.sv",
                ROOT / "tb" / "axi4_test_slave.v",
                ROOT / "rtl" / "fcapz_ejtagaxi.v",
                ROOT / "rtl" / "fcapz_ejtaguart.v",
                ROOT / "rtl" / "fcapz_async_fifo.v",
                ROOT / "tb" / "xpm_fifo_async_stub.v",
            ]
            compile_result = subprocess.run(
                ["iverilog", "-g2012", "-I", str(ROOT / "rtl"), "-o", str(vvp)]
                + [str(s) for s in sources],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                compile_result.returncode, 0,
                f"iverilog compilation failed:\n{compile_result.stderr}",
            )
            sim = subprocess.run(
                ["vvp", str(vvp)], capture_output=True, text=True, timeout=300
            )
            output = sim.stdout + sim.stderr
            self.assertEqual(sim.returncode, 0, output)
            self.assertIn("PASS: bridge discovery", output)
            self.assertIn("0 failed", output)


if __name__ == "__main__":
    unittest.main()
