# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Block mouse-wheel changes on numeric fields and combo boxes.

Scrolling a dock or dialog often passes the wheel to the widget under the
cursor; Qt would otherwise step spin boxes and cycle combo entries. A filter
on :class:`~PySide6.QtWidgets.QApplication` sees every event first.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox


class RejectSpinComboWheelFilter(QObject):
    """Drop :class:`~PySide6.QtCore.QEvent.Type.Wheel` for spins and combos."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.Wheel:
            if isinstance(obj, QAbstractSpinBox):
                return True
            if isinstance(obj, QComboBox):
                return True
        return False


def install_reject_spin_combo_wheel_filter(app: QApplication) -> RejectSpinComboWheelFilter:
    """Register the filter on *app*; parent *app* keeps the filter alive."""
    filt = RejectSpinComboWheelFilter(app)
    app.installEventFilter(filt)
    return filt
