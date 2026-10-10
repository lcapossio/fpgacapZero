# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""core.json lists every RTL file the core-manager shells need."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Vendor primitives are not RTL sources; their simulation stubs stand in.
STUBS = {
    "xilinx7": ROOT / "sim" / "bscane2_stub.v",
    "xilinxus": ROOT / "sim" / "bscane2_stub.v",
    "intel": ROOT / "sim" / "sld_virtual_jtag_stub.v",
}


@unittest.skipUnless(shutil.which("iverilog"), "iverilog not on PATH")
class CoreManifestTests(unittest.TestCase):
    def test_manager_shells_elaborate_from_manifest_sources(self):
        manifest = json.loads((ROOT / "core.json").read_text(encoding="utf-8"))
        sources = [ROOT / f for f in manifest["files"]]
        missing = [str(s) for s in sources if not s.exists()]
        self.assertEqual(missing, [], "core.json lists files that do not exist")
        with tempfile.TemporaryDirectory(prefix="core-manifest-") as tmpdir:
            # Stage only the manifest's files, so a missing header or module
            # cannot be found elsewhere in the repository.
            staged = Path(tmpdir) / "src"
            for rel in manifest["files"]:
                dest = staged / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / rel, dest)
            include_dirs = sorted({str((staged / rel).parent) for rel in manifest["files"]})
            verilog = [str(staged / rel) for rel in manifest["files"] if rel.endswith(".v")]
            for vendor, stub in STUBS.items():
                top = f"fcapz_debug_multi_{vendor}"
                with self.subTest(top=top):
                    self.assertIn(f"rtl/{top}.v", manifest["files"])
                    result = subprocess.run(
                        ["iverilog", "-g2012", "-s", top,
                         "-o", str(Path(tmpdir) / f"{vendor}.vvp")]
                        + [arg for d in include_dirs for arg in ("-I", d)]
                        + [str(stub)] + verilog,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
