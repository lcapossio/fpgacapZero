# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Regression: continuous capture uses QThread.started + Slot, not partial; sleep runs."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QObject, QThread, Slot

from fcapz.analyzer import CaptureConfig, CaptureResult, TriggerConfig
from fcapz.gui import worker as worker_mod
from fcapz.gui.worker import CaptureWorker


class _ProgressCtrl(QObject):
    def __init__(self, cap_worker: CaptureWorker) -> None:
        super().__init__()
        self._w = cap_worker
        self.count = 0

    @Slot(object)
    def on_progress(self, _result: object) -> None:
        self.count += 1
        if self.count >= 2:
            self._w.cancel_continuous()


def test_continuous_capture_sleeps_between_cycles() -> None:
    app = QCoreApplication.instance() or QCoreApplication([])

    cfg = CaptureConfig(
        pretrigger=0,
        posttrigger=1,
        trigger=TriggerConfig(mode="value_match", value=0, mask=255),
    )
    result = CaptureResult(config=cfg, samples=[0xAA], overflow=False)
    an = MagicMock()
    an.configure = MagicMock()
    an.arm = MagicMock()
    an.capture = MagicMock(return_value=result)

    delay_s = 0.25
    cap_w = CaptureWorker(an, inter_cycle_delay_s=delay_s)
    cap_w.set_pending_run(cfg, 1.0, continuous=True)

    thread = QThread()
    cap_w.moveToThread(thread)
    thread.started.connect(cap_w.thread_started)
    ctrl = _ProgressCtrl(cap_w)
    cap_w.progress.connect(ctrl.on_progress)
    cap_w.finished.connect(thread.quit)
    thread.finished.connect(ctrl.deleteLater)

    sleeps: list[float] = []

    def _record_sleep(dt: float) -> None:
        sleeps.append(float(dt))

    with patch.object(worker_mod.time, "sleep", side_effect=_record_sleep):
        thread.start()
        # Queued progress delivery needs the main thread event loop while we wait.
        deadline = time.monotonic() + 15.0
        while thread.isRunning() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert not thread.isRunning(), "QThread did not finish"

    assert ctrl.count == 2
    # One full interruptible delay after 1st progress, another after 2nd before loop exits.
    assert sum(sleeps) >= delay_s * 1.5, f"expected ~{delay_s * 2}s of sleep, got {sum(sleeps)}"
    an.capture.assert_called()
