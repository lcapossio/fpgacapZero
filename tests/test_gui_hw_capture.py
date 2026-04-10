# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""
Real **GUI + hardware** capture checks (opt-in).

Drives :class:`~fcapz.gui.app_window.MainWindow` like a user: connect, then captures
from the ELA panel, and asserts stable sample geometry plus **Arty reference
counter** sanity (longest +1 mod-256 run and trigger sample ~match), matching
``examples/arty_a7/test_hw_integration.py::TestCapture.test_samples_are_counter_values``.
For continuous mode, the same payload checks run on **every** ``progress`` result.

**Not run in default CI** (``-m "not hw"``). Requires a programmed board and JTAG.

Environment
-----------
``FPGACAP_GUI_HW=1`` (or ``true`` / ``yes``)
    Enable this module. Without it, all tests here are skipped.

``FPGACAP_SKIP_HW``
    If set, skipped (same convention as ``examples/arty_a7/test_hw_integration.py``).

``FPGACAP_BACKEND``
    ``hw_server`` (default) or ``openocd``.

``FPGACAP_BITFILE``
    Optional path to ``.bit`` for hw_server programming. If unset, uses
    ``examples/arty_a7/arty_a7_top.bit`` when that file exists.

``FPGACAP_HW_SERVER_PORT`` / ``FPGACAP_OPENOCD_PORT`` / ``FPGACAP_OPENOCD_TAP``
    Override defaults when needed.

``FPGACAP_CONTINUOUS_CAPTURES``
    For ``test_gui_continuous_many_captures_consistent``: number of continuous
    shots to validate (default ``1000``). Use a small value (e.g. ``20``) for a
    quick sanity run.

Example::

    FPGACAP_GUI_HW=1 python -m pytest tests/test_gui_hw_capture.py -v --tb=short -m \"hw and gui\"

    FPGACAP_GUI_HW=1 FPGACAP_CONTINUOUS_CAPTURES=50 \\
        python -m pytest \\
        tests/test_gui_hw_capture.py::test_gui_continuous_many_captures_consistent -v
"""

from __future__ import annotations

import os
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

from fcapz.analyzer import CaptureResult
from fcapz.gui.app_window import MainWindow
from fcapz.gui.settings import GuiSettings

REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_ARTY_BIT = REPO_ROOT / "examples" / "arty_a7" / "arty_a7_top.bit"


def _best_sequential_counter_run_low8(samples: list[int]) -> int:
    """Length of longest run of +1 (mod 256) steps in low 8 bits (Arty counter probe)."""
    vals = [s & 0xFF for s in samples]
    if not vals:
        return 0
    best_run = 0
    current_run = 1
    for i in range(1, len(vals)):
        if (vals[i] - vals[i - 1]) & 0xFF == 1:
            current_run += 1
        else:
            best_run = max(best_run, current_run)
            current_run = 1
    return max(best_run, current_run)


def _assert_capture_matches_arty_counter(
    result: CaptureResult,
    *,
    pre: int,
    trig_val: int = 0,
    context: str = "",
) -> None:
    """Same ideas as ``TestCapture.test_samples_are_counter_values`` + trigger anchor."""
    samples = result.samples
    note = f" {context}" if context else ""
    br = _best_sequential_counter_run_low8(samples)
    assert br >= pre + 1, (
        f"expected sequential counter run >= {pre + 1}, got {br}{note}; "
        f"low8={[x & 0xFF for x in samples]}"
    )
    tbyte = samples[pre] & 0xFF
    ok = {trig_val & 0xFF, (trig_val + 1) & 0xFF}
    assert tbyte in ok, (
        f"trigger sample @{pre} = 0x{tbyte:02x}, expected one of "
        f"{{{', '.join(f'0x{v:02x}' for v in sorted(ok))}}}{note}"
    )


def _gui_hw_enabled() -> bool:
    v = os.environ.get("FPGACAP_GUI_HW", "").strip().lower()
    return v in ("1", "true", "yes")


def _skip_hw_reason() -> str | None:
    if os.environ.get("FPGACAP_SKIP_HW", "").strip():
        return "FPGACAP_SKIP_HW is set"
    if not _gui_hw_enabled():
        return "set FPGACAP_GUI_HW=1 to run GUI+hardware capture tests"
    return None


def _gui_settings_for_hw() -> GuiSettings:
    gs = GuiSettings()
    backend = os.environ.get("FPGACAP_BACKEND", "hw_server").strip().lower()
    if backend == "openocd":
        gs.connection.backend = "openocd"
        gs.connection.port = int(os.environ.get("FPGACAP_OPENOCD_PORT", "6666"))
        gs.connection.tap = os.environ.get("FPGACAP_OPENOCD_TAP", "xc7a100t.tap")
    else:
        gs.connection.backend = "hw_server"
        gs.connection.tap = os.environ.get("FPGACAP_HW_SERVER_TAP", "xc7a100t.tap")
        p = os.environ.get("FPGACAP_HW_SERVER_PORT", "").strip()
        if p:
            gs.connection.port = int(p)
        bf = os.environ.get("FPGACAP_BITFILE", "").strip()
        if bf:
            gs.connection.program = bf
        elif _DEFAULT_ARTY_BIT.is_file():
            gs.connection.program = str(_DEFAULT_ARTY_BIT)
    return gs


def _button_in_widget(root: Any, text: str) -> QPushButton:
    for b in root.findChildren(QPushButton):
        if b.text() == text:
            return b
    raise AssertionError(f"no QPushButton with text {text!r} under {root!r}")


@contextmanager
def _patched_hw_main_window(qtbot: Any, tmp_path: Path) -> Any:
    reason = _skip_hw_reason()
    if reason is not None:
        pytest.skip(reason)

    gui_path = tmp_path / "gui.toml"
    gui_path.parent.mkdir(parents=True, exist_ok=True)
    settings = _gui_settings_for_hw()

    with (
        patch("fcapz.gui.app_window.default_gui_config_path", return_value=gui_path),
        patch("fcapz.gui.app_window.load_gui_settings", return_value=settings),
        patch("fcapz.gui.app_window.save_gui_settings"),
        patch("fcapz.gui.app_window.QMessageBox.critical"),
        patch("fcapz.gui.app_window.QMessageBox.warning"),
    ):
        w = MainWindow(restore_saved_layout=False, persist_window_layout=False)
        qtbot.addWidget(w)
        w.show()
        qtbot.waitExposed(w)
        try:
            yield w
        finally:
            if w._analyzer is not None:
                w._on_disconnect()
            QApplication.processEvents()


pytestmark = [pytest.mark.gui, pytest.mark.hw]


@pytest.mark.hw
@pytest.mark.gui
def test_gui_three_captures_consistent(qtbot: Any, tmp_path: Path) -> None:
    """Connect via GUI, run three single captures, check history and per-shot shape."""
    connect_timeout_ms = 240_000
    capture_timeout_ms = 45_000

    with _patched_hw_main_window(qtbot, tmp_path) as w:
        w._conn.request_connect()
        qtbot.waitUntil(lambda: w._analyzer is not None, timeout=connect_timeout_ms)

        # Match examples/arty_a7 TestCapture.test_basic_capture_value_match
        pre, post = 4, 8
        w._capture._pre.setValue(pre)
        w._capture._post.setValue(post)
        w._capture._trig_val.setText("0")
        w._capture._trig_mask.setText("0xFF")
        expected_n = pre + 1 + post

        cap_btn = _button_in_widget(w._capture, "Capture")

        for _ in range(3):
            before = w._history._table.rowCount()
            qtbot.mouseClick(cap_btn, Qt.MouseButton.LeftButton)

            def _done() -> bool:
                return w._history._table.rowCount() > before and not w._capture_running()

            qtbot.waitUntil(_done, timeout=capture_timeout_ms)

        assert w._history._table.rowCount() >= 3
        last_three = w._history._entries[-3:]

        lens = [len(e.result.samples) for e in last_three]
        assert lens == [expected_n, expected_n, expected_n], lens

        overflows = [e.result.overflow for e in last_three]
        assert overflows == [False, False, False]

        for i, e in enumerate(last_three, start=1):
            _assert_capture_matches_arty_counter(
                e.result,
                pre=pre,
                trig_val=0,
                context=f"single capture #{i}",
            )

        tidx = pre
        bases = [e.result.samples[tidx] & 0xFF for e in last_three]
        assert bases[0] == bases[1] == bases[2], (
            f"trigger sample bytes differ across runs: {bases!r}"
        )


@pytest.mark.hw
@pytest.mark.gui
def test_gui_continuous_many_captures_consistent(qtbot: Any, tmp_path: Path) -> None:
    """
    Continuous mode: validate **every** ``CaptureWorker.progress`` result (N times).

    The stock GUI coalesces continuous progress into occasional history rows; this
    test replaces ``_on_worker_progress`` **before** starting continuous capture so
    each hardware result is checked without creating N temp VCD trees.
    """
    count = int(os.environ.get("FPGACAP_CONTINUOUS_CAPTURES", "1000"))
    if count < 1:
        pytest.fail("FPGACAP_CONTINUOUS_CAPTURES must be >= 1")

    connect_timeout_ms = 240_000
    # Budget ~0.65 s per capture wall time (arm + trigger + read); floor 10 min.
    run_timeout_ms = max(600_000, int(count * 650))

    with _patched_hw_main_window(qtbot, tmp_path) as w:
        w._conn.request_connect()
        qtbot.waitUntil(lambda: w._analyzer is not None, timeout=connect_timeout_ms)

        pre, post = 4, 8
        w._capture._pre.setValue(pre)
        w._capture._post.setValue(post)
        w._capture._trig_val.setText("0")
        w._capture._trig_mask.setText("0xFF")
        w._capture._timeout.setText("3.0")
        expected_n = pre + 1 + post

        state: dict[str, Any] = {"n": 0, "ref": None}

        _orig_progress = w._on_worker_progress

        def _tracked_progress(self: MainWindow, result: CaptureResult) -> None:
            if self._analyzer is None:
                return
            if not self._continuous_mode:
                self._history.add_capture(self._analyzer, result)
                return
            state["n"] = int(state["n"]) + 1
            i = int(state["n"])
            assert len(result.samples) == expected_n, f"shot #{i}: sample count"
            assert not result.overflow, f"shot #{i}: overflow"
            _assert_capture_matches_arty_counter(
                result,
                pre=pre,
                trig_val=0,
                context=f"continuous shot #{i}",
            )
            low = result.samples[pre] & 0xFF
            if state["ref"] is None:
                state["ref"] = low
            else:
                assert low == state["ref"], (
                    f"shot #{i}: trigger low byte 0x{low:02x} != 0x{int(state['ref']):02x}"
                )
            if i >= count:
                self._on_stop_continuous()

        w._on_worker_progress = types.MethodType(_tracked_progress, w)

        try:
            cont_btn = _button_in_widget(w._capture, "Continuous")
            qtbot.mouseClick(cont_btn, Qt.MouseButton.LeftButton)
            qtbot.waitUntil(
                lambda: w._cap_thread is not None,
                timeout=30_000,
            )

            def _finished() -> bool:
                return int(state["n"]) >= count and not w._capture_running()

            qtbot.waitUntil(_finished, timeout=run_timeout_ms)
        finally:
            w._on_worker_progress = _orig_progress

        assert int(state["n"]) == count, f"expected {count} progress callbacks, got {state['n']}"
