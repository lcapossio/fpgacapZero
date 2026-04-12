# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Wrap panels in :class:`QScrollArea` so tight dock splitters scroll.

They scroll instead of squashing forms.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QSizePolicy, QWidget


def scroll_wrap(
    inner: QWidget,
    *,
    min_width: int = 280,
    min_height: int = 160,
) -> QScrollArea:
    """
    ``widgetResizable`` is **True** so the panel **fills** its dock when space is available
    (normal layouts and nested splitters behave correctly). The inner widget still has a
    **minimum** size; when the dock viewport is smaller, scroll bars appear instead of
    squashing the form.

    Do **not** wrap panels that host a :class:`QSplitter` (e.g. capture history +
    waveform preview): fixed inner minimums break splitter share.
    """
    scroll = QScrollArea()
    scroll.setObjectName("fcapz_scroll_area")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    mw = max(min_width, inner.minimumWidth())
    mh = max(min_height, inner.minimumHeight())
    inner.setMinimumWidth(mw)
    inner.setMinimumHeight(mh)
    scroll.setWidget(inner)
    scroll.setSizePolicy(
        QSizePolicy.Policy.Expanding,
        QSizePolicy.Policy.Expanding,
    )
    return scroll
