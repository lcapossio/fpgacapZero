# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from fcapz.gui.history_panel import HistoryPanel

pytestmark = pytest.mark.gui


class _FakeWcp:
    def __init__(self, ready: bool) -> None:
        self.ready = ready
        self.reloaded = False

    def can_reload(self) -> bool:
        return self.ready

    def send_reload(self) -> bool:
        self.reloaded = True
        return self.ready

    def prepare_listener(self) -> int:
        return 1


def _make_reused_panel(qtbot: Any, monkeypatch: pytest.MonkeyPatch) -> HistoryPanel:
    panel = HistoryPanel()
    qtbot.addWidget(panel)
    panel.set_reuse_external_viewer(True)
    panel._last_viewer_program = str(Path("surfer").resolve())
    monkeypatch.setattr(panel, "_running_viewer_process", lambda: object())
    return panel


def test_surfer_reload_uses_wcp_when_pretrigger_is_unchanged(
    qtbot: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = _make_reused_panel(qtbot, monkeypatch)
    panel._last_surfer_marker_pretrigger = 123
    wcp = _FakeWcp(ready=True)
    panel._surfer_wcp = wcp
    monkeypatch.setattr(
        panel,
        "stop_viewer_processes",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("relaunched")),
    )
    messages: list[str] = []
    panel.status_message.connect(messages.append)

    panel._start_viewer_process(
        "Surfer",
        ["surfer"],
        silent=True,
        surfer_wcp=True,
        surfer_marker_time=123,
        surfer_marker_pretrigger=123,
    )

    assert wcp.reloaded
    assert messages == ["Updated live wave for Surfer - reloaded in Surfer (WCP)."]


def test_surfer_reopens_when_wcp_unavailable_and_pretrigger_unchanged(
    qtbot: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = _make_reused_panel(qtbot, monkeypatch)
    panel._last_surfer_marker_pretrigger = 123
    panel._surfer_wcp = _FakeWcp(ready=False)
    stopped = []
    monkeypatch.setattr(
        panel, "stop_viewer_processes", lambda *args, **kwargs: stopped.append(True),
    )
    started = []
    monkeypatch.setattr("fcapz.gui.history_panel.QProcess.start", lambda self: started.append(True))

    panel._start_viewer_process(
        "Surfer",
        ["surfer"],
        silent=True,
        surfer_wcp=True,
        surfer_marker_time=123,
        surfer_marker_pretrigger=123,
    )

    assert stopped == [True]
    assert started == [True]


def test_surfer_pretrigger_change_reopens_when_marker_must_move(
    qtbot: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = _make_reused_panel(qtbot, monkeypatch)
    panel._last_surfer_marker_pretrigger = 8
    panel._surfer_wcp = _FakeWcp(ready=True)
    stopped = []
    monkeypatch.setattr(
        panel, "stop_viewer_processes", lambda *args, **kwargs: stopped.append(True),
    )
    started = []
    monkeypatch.setattr("fcapz.gui.history_panel.QProcess.start", lambda self: started.append(True))

    panel._start_viewer_process(
        "Surfer",
        ["surfer"],
        silent=True,
        surfer_wcp=True,
        surfer_marker_time=456,
        surfer_marker_pretrigger=456,
    )

    assert stopped == [True]
    assert started == [True]
