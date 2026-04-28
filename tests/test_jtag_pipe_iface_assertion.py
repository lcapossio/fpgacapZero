# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(
    shutil.which("iverilog") is None or shutil.which("vvp") is None,
    reason="iverilog/vvp not installed",
)
def test_jtag_pipe_iface_rejects_misaligned_segment_pointer(tmp_path: Path) -> None:
    """Segmented single-chain burst readback must fail loudly on bad pointers."""

    out = tmp_path / "jtag_pipe_iface_tb.vvp"
    compile_cmd = [
        "iverilog",
        "-g2012",
        "-Wall",
        "-I",
        str(ROOT / "rtl"),
        "-o",
        str(out),
        str(ROOT / "tb" / "jtag_pipe_iface_tb.sv"),
        str(ROOT / "rtl" / "jtag_pipe_iface.v"),
    ]
    subprocess.run(compile_cmd, check=True, cwd=ROOT)

    result = subprocess.run(
        ["vvp", str(out), "+MISALIGN_SEG_PTR"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    assert result.returncode != 0
    assert "not aligned to SEG_DEPTH" in result.stdout
