# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Fetch the pre-generated VexRiscv core for the Arty reference variant.

VexRiscv is generated from SpinalHDL; rather than vendor a ~260 KB generated
file (or require a Scala toolchain), this pulls the pinned, pre-generated
``VexRiscv_Lite.v`` (RV32I, plain Wishbone iBus/dBus) published by the LiteX
project, verifies its SHA-256, and drops it next to the subsystem RTL. The
fetched core is git-ignored -- this mirrors how the MicroBlaze variant relies
on Vivado-provided IP rather than checking it in. Network is needed once.

    python examples/arty_a7/vex/get_deps.py

VexRiscv is MIT-licensed (Copyright (c) SpinalHDL contributors); see
https://github.com/SpinalHDL/VexRiscv.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

_VEX_DIR = Path(__file__).resolve().parent

# Pinned to a specific upstream commit + content hash for reproducibility.
_PIN_COMMIT = "1979a644dbe64d8d32dfbdd970dccee6add63723"
_CORE_NAME = "VexRiscv_Lite.v"
_CORE_SHA256 = "90e0b8f5912df2532d12bc766b110a632c1b85dd82b8aecd431d715c25f4cbbe"
_CORE_URL = (
    "https://raw.githubusercontent.com/litex-hub/pythondata-cpu-vexriscv/"
    f"{_PIN_COMMIT}/pythondata_cpu_vexriscv/verilog/{_CORE_NAME}"
)


def _sha256(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def fetch_vexriscv(force: bool = False) -> Path:
    """Download + verify VexRiscv_Lite.v into vex/. Idempotent."""
    dest = _VEX_DIR / _CORE_NAME
    if dest.exists() and not force:
        if _sha256(dest.read_bytes()) == _CORE_SHA256:
            print(f"fcapz: {_CORE_NAME} already present and verified")
            return dest
        print(f"fcapz: {_CORE_NAME} hash mismatch on disk; re-fetching")

    print(f"fcapz: fetching {_CORE_URL}")
    with urllib.request.urlopen(_CORE_URL, timeout=60) as resp:  # noqa: S310 - pinned https
        data = resp.read()
    got = _sha256(data)
    if got != _CORE_SHA256:
        raise SystemExit(
            f"fcapz: {_CORE_NAME} SHA-256 mismatch\n  expected {_CORE_SHA256}\n"
            f"  got      {got}\nRefusing to use an unexpected core."
        )
    dest.write_bytes(data)
    print(f"fcapz: wrote {dest} ({len(data)} bytes, sha256 ok)")
    return dest


if __name__ == "__main__":
    fetch_vexriscv(force="--force" in sys.argv[1:])
