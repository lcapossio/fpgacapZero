# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""
Smoke tests for Surfer ↔ fcapz-gui integration feasibility.

Upstream Surfer (desktop) is an **eframe/egui** app started with ``eframe::run_native``;
there is **no** stable CLI to reparent its window into a Qt ``QWidget`` (no ``--parent-hwnd``
/ embed flag in public ``surfer --help``).

Practical integration paths today:

1. **Current behaviour** — ``subprocess.Popen`` launches Surfer as a **separate top-level
   window** (already implemented in :mod:`fcapz.gui.viewers`).
2. **Future in-window** — Surfer documents **web** embedding (iframe / WASM + ``postMessage``)
   and **server** mode (``surfer server`` / ``surver``); a Qt **QWebEngineView** could load
   those, but that is a separate dependency and UX story.

These tests only run when ``surfer`` is on ``PATH`` (e.g. developer machine, not CI).
"""

from __future__ import annotations

import shutil
import subprocess

import pytest


def _surfer_exe() -> str | None:
    return shutil.which("surfer")


@pytest.mark.skipif(_surfer_exe() is None, reason="surfer executable not on PATH")
def test_surfer_help_includes_command_file_and_server() -> None:
    """Guard against CLI drift: we rely on --command-file; server hints at remote/embed path."""
    exe = _surfer_exe()
    assert exe is not None
    proc = subprocess.run(
        [exe, "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    out = (proc.stdout or "") + (proc.stderr or "")
    lowered = out.lower()
    assert "command-file" in lowered or "command_file" in lowered, out[:2000]
    assert "server" in lowered, out[:2000]


@pytest.mark.skipif(_surfer_exe() is None, reason="surfer executable not on PATH")
def test_surfer_help_has_no_documented_native_embed_flag() -> None:
    """
    If Surfer ever adds an explicit embed/parent flag, this test should fail and we can
    revisit QWidget embedding (e.g. ``QWindow.fromWinId`` / platform glue).
    """
    exe = _surfer_exe()
    assert exe is not None
    proc = subprocess.run(
        [exe, "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0
    out = ((proc.stdout or "") + (proc.stderr or "")).lower()
    # Heuristic: no obvious "embed in parent window" switch today.
    assert "parent-hwnd" not in out
    assert "embed-window" not in out
    assert "reparent" not in out
