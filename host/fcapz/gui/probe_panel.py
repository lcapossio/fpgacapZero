# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import json
from typing import Any, Mapping

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGroupBox, QTextEdit, QVBoxLayout, QWidget


class ProbePanel(QGroupBox):
    """Read-only view of :meth:`fcapz.analyzer.Analyzer.probe` results."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("ELA identity", parent)
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setPlaceholderText("Connect, then identity appears here.")
        font = self._text.font()
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._text.setFont(font)

        lay = QVBoxLayout(self)
        lay.addWidget(self._text)

    def set_probe_info(self, info: Mapping[str, Any]) -> None:
        self._text.setPlainText(json.dumps(dict(info), indent=2))

    def clear(self) -> None:
        self._text.clear()
