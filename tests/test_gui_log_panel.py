# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QLineEdit

from fcapz.gui.app_window import _sanitize_user_layout_key
from fcapz.gui.log_panel import LogPanel, _MAX_LINES

pytestmark = pytest.mark.gui


def test_sanitize_user_layout_key() -> None:
    assert _sanitize_user_layout_key("  My Layout #1  ") == "My_Layout_1"
    assert _sanitize_user_layout_key("!!!") == "layout"


def test_log_panel_filter_case_insensitive(qtbot) -> None:
    p = LogPanel()
    qtbot.addWidget(p)
    flt = p.findChild(QLineEdit)
    assert flt is not None
    p._on_line_received("INFO alpha")
    p._on_line_received("WARN Beta")
    flt.setText("beta")
    assert "Beta" in p._edit.toPlainText()
    assert "alpha" not in p._edit.toPlainText().casefold()


def test_log_panel_ring_buffer_cap(qtbot) -> None:
    p = LogPanel()
    qtbot.addWidget(p)
    for i in range(_MAX_LINES + 50):
        p._on_line_received(f"line {i}")
    assert len(p._lines) == _MAX_LINES
    assert "line 0" not in p._lines
    assert any("line 4049" in ln for ln in p._lines)
