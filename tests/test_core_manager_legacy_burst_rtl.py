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
class CoreManagerLegacyBurstRtlTests(unittest.TestCase):
    def test_burst_start_sync_reads_old_managers_correctly(self):
        """The naive burst misreads after a slot switch on a manager from
        before MGR_CAPS bit 2, exactly where the toggle model predicts; the
        host's start sync reads it, and the current manager, correctly."""
        with tempfile.TemporaryDirectory(prefix="mgr-legacy-burst-") as tmpdir:
            vvp = Path(tmpdir) / "fcapz_core_manager_legacy_burst_tb.vvp"
            sources = [
                ROOT / "tb" / "fcapz_core_manager_legacy_burst_tb.sv",
                ROOT / "tb" / "legacy" / "fcapz_core_manager_pre_burst_start.v",
                ROOT / "rtl" / "fcapz_core_manager.v",
                ROOT / "rtl" / "jtag_pipe_iface.v",
                ROOT / "rtl" / "jtag_burst_read.v",
            ]
            compile_result = subprocess.run(
                ["iverilog", "-g2012", "-I", str(ROOT / "rtl"), "-o", str(vvp)]
                + [str(s) for s in sources],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                compile_result.returncode,
                0,
                f"iverilog compilation failed:\n{compile_result.stderr}",
            )
            sim_result = subprocess.run(
                ["vvp", str(vvp)], capture_output=True, text=True, timeout=300
            )
            output = sim_result.stdout + sim_result.stderr
            self.assertEqual(sim_result.returncode, 0, f"simulation failed:\n{output}")
            self.assertIn("legacy burst summary: 0 failed", output, output)
            self.assertEqual(output.count(": 0 failures"), 16, output)
