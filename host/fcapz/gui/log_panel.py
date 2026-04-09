# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Bottom-dock style log viewer + :mod:`logging` handler (thread-safe via Qt signals)."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_MAX_DOCUMENT_BLOCKS = 4000


class _LogSignaler(QObject):
    """Marshals log records onto the GUI thread."""

    line = Signal(str)


class QtGuiLogHandler(logging.Handler):
    """Append formatted records via :class:`_LogSignaler` (queued across threads)."""

    def __init__(self, signaler: _LogSignaler) -> None:
        super().__init__()
        self._signaler = signaler

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._signaler.line.emit(msg)
        except Exception:  # noqa: BLE001
            self.handleError(record)


class LogPanel(QGroupBox):
    """Read-only scrolling log; ``fcapz`` loggers can attach :class:`QtGuiLogHandler`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Log", parent)
        self._signaler = _LogSignaler()
        self._signaler.line.connect(self.append_line)

        self._edit = QPlainTextEdit()
        self._edit.setReadOnly(True)
        self._edit.setObjectName("fcapz_log_plain")
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._edit.document().setMaximumBlockCount(_MAX_DOCUMENT_BLOCKS)
        font = self._edit.font()
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(max(8, font.pointSize() - 1))
        self._edit.setFont(font)
        self._edit.setMinimumHeight(64)

        self._autoscroll = QCheckBox("Auto-scroll")
        self._autoscroll.setChecked(True)

        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear)
        copy = QPushButton("Copy all")
        copy.clicked.connect(self._copy_all)

        hint = QLabel("Python logging for namespace <code>fcapz</code>.")
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setWordWrap(True)

        row = QHBoxLayout()
        row.addWidget(self._autoscroll)
        row.addStretch(1)
        row.addWidget(clear)
        row.addWidget(copy)

        lay = QVBoxLayout(self)
        lay.addWidget(hint)
        lay.addLayout(row)
        lay.addWidget(self._edit, stretch=1)

    def make_handler(self, *, fmt: str | None = None) -> QtGuiLogHandler:
        h = QtGuiLogHandler(self._signaler)
        h.setLevel(logging.DEBUG)
        h.setFormatter(
            logging.Formatter(
                fmt or "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            ),
        )
        return h

    def append_line(self, line: str) -> None:
        self._edit.appendPlainText(line.rstrip())
        if self._autoscroll.isChecked():
            sb = self._edit.verticalScrollBar()
            sb.setValue(sb.maximum())
            cur = self._edit.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.End)
            self._edit.setTextCursor(cur)

    def clear(self) -> None:
        self._edit.clear()

    def _copy_all(self) -> None:
        self._edit.selectAll()
        self._edit.copy()
        cur = self._edit.textCursor()
        cur.clearSelection()
        self._edit.setTextCursor(cur)
