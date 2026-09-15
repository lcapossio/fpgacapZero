# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Verify (or refresh) the vendored VexRiscv core shared by the examples.

The pre-generated ``VexRiscv_Lite.v`` (RV32I, plain Wishbone iBus/dBus) is
vendored under ``third_party/vexriscv/`` so clean builds are reproducible and
need no network access. This module is the single source of truth for both
board examples (Arty A7 and DE25-Nano):

  * ``fetch_vexriscv()`` -- the default, offline: verify the checked-in core's
    SHA-256 and return its path. Called by the per-board build launchers.
  * ``update_vexriscv()`` -- networked: re-fetch the pinned core from upstream
    and rewrite the vendored file. Run explicitly when bumping the pin:

        python examples/common/vexriscv/get_deps.py --update

VexRiscv is MIT-licensed (Copyright (c) Spinal HDL contributors); the license
and full provenance live next to the vendored file
(third_party/vexriscv/LICENSE, PROVENANCE.toml).
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_VENDOR_DIR = _ROOT / "third_party" / "vexriscv"

_CORE_NAME = "VexRiscv_Lite.v"
_CORE_PATH = _VENDOR_DIR / _CORE_NAME

# Pinned to a specific upstream commit + content hash for reproducibility.
# Keep in sync with third_party/vexriscv/PROVENANCE.toml.
_PIN_COMMIT = "1979a644dbe64d8d32dfbdd970dccee6add63723"
_CORE_SHA256 = "90e0b8f5912df2532d12bc766b110a632c1b85dd82b8aecd431d715c25f4cbbe"
_CORE_URL = (
    "https://raw.githubusercontent.com/litex-hub/pythondata-cpu-vexriscv/"
    f"{_PIN_COMMIT}/pythondata_cpu_vexriscv/verilog/{_CORE_NAME}"
)

# Second vendored core: the CPU-debug variant (EmbeddedRiscvJtag / standard
# RISC-V Debug Module + JTAG DTM), used by the examples' "vex-debug" build
# variant. It is NOT a LiteX download -- the no-TAP JTAG tunnel postdates the
# pin above -- but regenerated locally from SpinalHDL/VexRiscv master with the
# vendored recipe (third_party/vexriscv/GenFcapzVexDebug.scala). There is thus
# no fetch URL: it is verified offline by SHA-256 only. See PROVENANCE.toml
# ([core.debug]) for the full regeneration recipe.
_DEBUG_CORE_NAME = "VexRiscv_EmbeddedJtag.v"
_DEBUG_CORE_PATH = _VENDOR_DIR / _DEBUG_CORE_NAME
_DEBUG_CORE_SHA256 = (
    "42d38244f0c6aeab84c26b39ae3ecc56944401c9b8b42842625a84f2d8c3c6c1"
)


def _sha256(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def fetch_vexriscv() -> Path:
    """Verify the vendored core (offline) and return its path.

    Named ``fetch_*`` for API stability with the per-board build launchers.
    Does no network I/O -- the core is checked in; use ``update_vexriscv()``
    (``--update``) to refresh the pin.
    """
    if not _CORE_PATH.exists():
        raise SystemExit(
            f"fcapz: vendored core missing: {_CORE_PATH}\n"
            "The repository should ship it; run "
            "'python examples/common/vexriscv/get_deps.py --update' to re-fetch."
        )
    got = _sha256(_CORE_PATH.read_bytes())
    if got != _CORE_SHA256:
        raise SystemExit(
            f"fcapz: {_CORE_NAME} SHA-256 mismatch (vendored file corrupt or edited)\n"
            f"  expected {_CORE_SHA256}\n  got      {got}\n"
            "Restore it from git or re-fetch with '--update'."
        )
    print(f"fcapz: {_CORE_NAME} vendored and verified ({_CORE_PATH})")
    return _CORE_PATH


def fetch_vexriscv_debug() -> Path:
    """Verify the vendored CPU-debug core (offline) and return its path.

    Hash-only check: this core has no upstream download (it is regenerated,
    not fetched -- see PROVENANCE.toml [core.debug]). Called by the per-board
    build launchers for the ``vex-debug`` variant.
    """
    if not _DEBUG_CORE_PATH.exists():
        raise SystemExit(
            f"fcapz: vendored debug core missing: {_DEBUG_CORE_PATH}\n"
            "The repository should ship it; regenerate per "
            "third_party/vexriscv/PROVENANCE.toml ([core.debug])."
        )
    got = _sha256(_DEBUG_CORE_PATH.read_bytes())
    if got != _DEBUG_CORE_SHA256:
        raise SystemExit(
            f"fcapz: {_DEBUG_CORE_NAME} SHA-256 mismatch "
            "(vendored file corrupt or edited)\n"
            f"  expected {_DEBUG_CORE_SHA256}\n  got      {got}\n"
            "Restore it from git, or regenerate per PROVENANCE.toml."
        )
    print(f"fcapz: {_DEBUG_CORE_NAME} vendored and verified ({_DEBUG_CORE_PATH})")
    return _DEBUG_CORE_PATH


def update_vexriscv() -> Path:
    """Re-fetch the pinned core from upstream and rewrite the vendored file."""
    print(f"fcapz: fetching {_CORE_URL}")
    with urllib.request.urlopen(_CORE_URL, timeout=60) as resp:  # noqa: S310 - pinned https
        data = resp.read()
    got = _sha256(data)
    if got != _CORE_SHA256:
        raise SystemExit(
            f"fcapz: {_CORE_NAME} SHA-256 mismatch\n  expected {_CORE_SHA256}\n"
            f"  got      {got}\nRefusing to vendor an unexpected core."
        )
    _VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    _CORE_PATH.write_bytes(data)
    print(f"fcapz: wrote {_CORE_PATH} ({len(data)} bytes, sha256 ok)")
    return _CORE_PATH


if __name__ == "__main__":
    if "--update" in sys.argv[1:]:
        update_vexriscv()
        # The debug core has no download; only its hash is (re)checked.
        fetch_vexriscv_debug()
    else:
        fetch_vexriscv()
        fetch_vexriscv_debug()
