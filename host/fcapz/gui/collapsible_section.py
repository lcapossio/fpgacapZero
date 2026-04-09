# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Reusable show/hide section to keep tall panels manageable."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout, QWidget


class CollapsibleSection(QFrame):
    """Header row toggles visibility of a content widget (no space when collapsed)."""

    expandedChanged = Signal(bool)

    def __init__(
        self,
        title: str,
        content: QWidget,
        *,
        start_open: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._content = content
        self._expanded = start_open
        self._title = title

        self._toggle = QPushButton()
        self._toggle.setFlat(True)
        self._toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.clicked.connect(self._flip)
        self._update_toggle_text()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self._toggle, 0)
        lay.addWidget(self._content, 0)
        self._content.setVisible(self._expanded)

    def _update_toggle_text(self) -> None:
        prefix = "▼ " if self._expanded else "▶ "
        self._toggle.setText(prefix + self._title)

    def _flip(self) -> None:
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        self._update_toggle_text()
        self.expandedChanged.emit(self._expanded)

    def setExpanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._flip()

    def isExpanded(self) -> bool:
        return self._expanded
