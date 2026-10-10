# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""A core-manager slot switch straight after a burst lands on the first ACTIVE
write at every sample width (tb/fcapz_debug_multi_burst_select_tb.sv).  The
bench keeps the host's confirmed-select loop, which older bitstreams need."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from fcapz.transport import MANAGER_SELECT_ATTEMPTS

ROOT = Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"

SOURCES = [
    ROOT / "tb" / "fcapz_debug_multi_burst_select_tb.sv",
    RTL / "fcapz_debug_multi.v",
    RTL / "fcapz_debug_multi_core.v",
    RTL / "fcapz_core_manager.v",
    RTL / "jtag_pipe_iface.v",
    RTL / "reset_sync.v",
    RTL / "fcapz_ela.v",
    RTL / "dpram.v",
    RTL / "trig_compare.v",
    RTL / "fcapz_eio.v",
]

# 1 bit: the longest preload; 4: dropped the first write before BUG-227; 8: short preload
SAMPLE_WIDTHS = (1, 4, 8)


@unittest.skipUnless(shutil.which("iverilog"), "iverilog not on PATH")
@unittest.skipUnless(shutil.which("vvp"), "vvp not on PATH")
class DebugMultiBurstSelectRtlTests(unittest.TestCase):
    def test_bench_matches_the_host_attempt_count(self):
        bench = SOURCES[0].read_text(encoding="utf-8")
        self.assertIn(f"writes < {MANAGER_SELECT_ATTEMPTS})", bench)

    def test_slot_switch_after_a_burst_lands(self):
        with tempfile.TemporaryDirectory(prefix="debug-multi-select-") as tmpdir:
            for sample_w in SAMPLE_WIDTHS:
                with self.subTest(sample_w=sample_w):
                    vvp = Path(tmpdir) / f"select{sample_w}.vvp"
                    compile_result = subprocess.run(
                        ["iverilog", "-g2012", "-I", str(RTL), "-I", str(ROOT / "tb"),
                         f"-Pfcapz_debug_multi_burst_select_tb.SAMPLE_W={sample_w}",
                         "-s", "fcapz_debug_multi_burst_select_tb", "-o", str(vvp)]
                        + [str(s) for s in SOURCES],
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        compile_result.returncode, 0,
                        f"iverilog compilation failed:\n{compile_result.stderr}",
                    )
                    sim = subprocess.run(
                        ["vvp", "-n", str(vvp)], capture_output=True, text=True, timeout=300
                    )
                    output = sim.stdout + sim.stderr
                    self.assertEqual(sim.returncode, 0, f"simulation failed:\n{output}")
                    self.assertIn(f"SAMPLE_W={sample_w}: ", output, output)
                    self.assertIn(" 0 failed ===", output, output)
                    self.assertIn("landed, 1 write(s)", output, output)
