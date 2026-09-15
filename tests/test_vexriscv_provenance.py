# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Guard the vendored VexRiscv pin against drift between its two records.

The pin (upstream commit, content SHA-256, raw URL) is stated in both
examples/common/vexriscv/get_deps.py (which enforces it offline at build time)
and third_party/vexriscv/PROVENANCE.toml (which documents it). They must agree,
or a future bump could verify one core while advertising another.
"""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_GET_DEPS = ROOT / "examples" / "common" / "vexriscv" / "get_deps.py"
_PROVENANCE = ROOT / "third_party" / "vexriscv" / "PROVENANCE.toml"


def _load_get_deps():
    spec = importlib.util.spec_from_file_location("vex_get_deps", _GET_DEPS)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_get_deps_pin_matches_provenance() -> None:
    gd = _load_get_deps()
    prov = tomllib.loads(_PROVENANCE.read_text(encoding="utf-8"))

    assert gd._CORE_SHA256 == prov["core"]["sha256"], "SHA-256 pin differs"
    assert gd._PIN_COMMIT == prov["source"]["commit"], "upstream commit differs"
    assert gd._CORE_URL == prov["source"]["raw_url"], "raw fetch URL differs"


def test_debug_core_pin_matches_provenance() -> None:
    # The CPU-debug core (EmbeddedRiscvJtag) is regenerated, not downloaded,
    # so it has only a content hash to keep in sync (no commit/URL).
    gd = _load_get_deps()
    prov = tomllib.loads(_PROVENANCE.read_text(encoding="utf-8"))
    debug = prov["core"]["debug"]

    assert gd._DEBUG_CORE_SHA256 == debug["sha256"], "debug core SHA-256 differs"
    assert gd._DEBUG_CORE_NAME == debug["file"], "debug core file name differs"
