# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Elaboration check on the PolarFire TAP's UJTAG user opcodes."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    shutil.which("iverilog") is None or shutil.which("vvp") is None,
    reason="iverilog/vvp not installed",
)


def _elaborate(tmp_path: Path, top: str, params: dict[str, str]) -> str:
    out = tmp_path / f"{top}.vvp"
    cmd = ["iverilog", "-g2012", "-I", str(ROOT / "rtl"), "-s", top, "-o", str(out)]
    cmd += [f"-P{top}.{k}={v}" for k, v in params.items()]
    cmd += [
        str(ROOT / "sim" / "ujtag_stub.v"),
        str(ROOT / "rtl" / "jtag_tap" / "jtag_tap_polarfire.v"),
        str(ROOT / "rtl" / "jtag_reg_iface.v"),
        str(ROOT / "rtl" / "fcapz_eio.v"),
        str(ROOT / "rtl" / "fcapz_eio_polarfire.v"),
    ]
    subprocess.run(cmd, check=True, cwd=ROOT)
    result = subprocess.run(
        ["vvp", "-n", str(out)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.stdout


@pytest.mark.parametrize(
    ("params", "rejected"),
    [
        ({}, False),
        ({"IR_USER1": "8'h7f", "IR_USER2": "8'h10"}, False),
        ({"IR_USER1": "8'h0f"}, True),
        ({"IR_USER1": "8'hff"}, True),
        ({"IR_USER2": "8'h80"}, True),
        ({"IR_USER1": "8'h21", "IR_USER2": "8'h21"}, True),
        # USER2 unused: neither its range nor a clash with USER1 matters.
        ({"IR_USER1": "8'h21", "IR_USER2": "8'h21", "CH2_EN": "0"}, False),
        ({"IR_USER2": "8'hff", "CH2_EN": "0"}, False),
        ({"IR_USER1": "8'hff", "CH2_EN": "0"}, True),
    ],
)
def test_tap_opcode_check(tmp_path: Path, params: dict[str, str], rejected: bool) -> None:
    log = _elaborate(tmp_path, "jtag_tap_polarfire", params)
    assert ("jtag_tap_polarfire:" in log) == rejected, log


def test_single_chain_eio_may_reuse_default_user2(tmp_path: Path) -> None:
    """The EIO uses USER1 only, so USER1 = 0x21 next to the default USER2 is fine."""

    log = _elaborate(tmp_path, "fcapz_eio_polarfire", {"IR_USER1": "8'h21"})
    assert "jtag_tap_polarfire:" not in log, log
