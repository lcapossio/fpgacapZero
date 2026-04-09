# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Bottom-dock style log viewer + :mod:`logging` handler (thread-safe via Qt signals)."""

from __future__ import annotations

import logging
import sys
from collections import deque

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_MAX_LINES = 4000


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
    """Read-only log for ``fcapz``; filter, level, and optional stderr mirror."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Log", parent)
        self._signaler = _LogSignaler()
        self._signaler.line.connect(self._on_line_received)

        self._lines: deque[str] = deque(maxlen=_MAX_LINES)
        self._qt_handler: QtGuiLogHandler | None = None
        self._stderr_handler: logging.StreamHandler | None = None

        self._edit = QPlainTextEdit()
        self._edit.setReadOnly(True)
        self._edit.setObjectName("fcapz_log_plain")
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = self._edit.font()
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(max(8, font.pointSize() - 1))
        self._edit.setFont(font)
        self._edit.setMinimumHeight(64)

        self._level = QComboBox()
        for label, lev in (
            ("DEBUG", logging.DEBUG),
            ("INFO", logging.INFO),
            ("WARNING", logging.WARNING),
            ("ERROR", logging.ERROR),
        ):
            self._level.addItem(label, lev)
        self._level.setCurrentIndex(1)
        self._level.currentIndexChanged.connect(self._on_level_changed)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter lines (substring, case-insensitive)…")
        self._filter.textChanged.connect(lambda _: self._refresh_display())

        self._mirror_stderr = QCheckBox("Mirror to stderr")
        self._mirror_stderr.toggled.connect(self._on_mirror_stderr_toggled)

        self._autoscroll = QCheckBox("Auto-scroll")
        self._autoscroll.setChecked(True)

        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear)
        copy = QPushButton("Copy all")
        copy.clicked.connect(self._copy_all)

        hint = QLabel(
            "Python logging for namespace <code>fcapz</code>. "
            "Level filters this panel; root <code>fcapz</code> logger level may also apply.",
        )
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setWordWrap(True)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Level:"))
        row1.addWidget(self._level)
        row1.addStretch(1)
        row1.addWidget(self._mirror_stderr)

        row2 = QHBoxLayout()
        row2.addWidget(self._autoscroll)
        row2.addStretch(1)
        row2.addWidget(clear)
        row2.addWidget(copy)

        lay = QVBoxLayout(self)
        lay.addWidget(hint)
        lay.addLayout(row1)
        lay.addWidget(self._filter)
        lay.addLayout(row2)
        lay.addWidget(self._edit, stretch=1)

    def set_qt_handler(self, handler: QtGuiLogHandler) -> None:
        self._qt_handler = handler
        self._on_level_changed()

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

    def _on_level_changed(self) -> None:
        if self._qt_handler is None:
            return
        lev = self._level.currentData()
        if isinstance(lev, int):
            self._qt_handler.setLevel(lev)

    def _on_mirror_stderr_toggled(self, checked: bool) -> None:
        lg = logging.getLogger("fcapz")
        if checked:
            if self._stderr_handler is None:
                self._stderr_handler = logging.StreamHandler(sys.stderr)
                self._stderr_handler.setFormatter(
                    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"),
                )
                lg.addHandler(self._stderr_handler)
        else:
            if self._stderr_handler is not None:
                lg.removeHandler(self._stderr_handler)
                self._stderr_handler = None

    def _on_line_received(self, line: str) -> None:
        s = line.rstrip()
        self._lines.append(s)
        if self._filter_substring():
            self._refresh_display()
        else:
            self._edit.appendPlainText(s)
            if self._autoscroll.isChecked():
                sb = self._edit.verticalScrollBar()
                sb.setValue(sb.maximum())
                cur = self._edit.textCursor()
                cur.movePosition(QTextCursor.MoveOperation.End)
                self._edit.setTextCursor(cur)

    def _filter_substring(self) -> str:
        return self._filter.text().strip().casefold()

    def _refresh_display(self) -> None:
        needle = self._filter_substring()
        if needle:
            filtered = [ln for ln in self._lines if needle in ln.casefold()]
            text = "\n".join(filtered)
        else:
            text = "\n".join(self._lines)
        self._edit.setPlainText(text)
        if self._autoscroll.isChecked():
            sb = self._edit.verticalScrollBar()
            sb.setValue(sb.maximum())
            cur = self._edit.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.End)
            self._edit.setTextCursor(cur)

    def clear(self) -> None:
        self._lines.clear()
        self._edit.clear()

    def _copy_all(self) -> None:
        self._edit.selectAll()
        self._edit.copy()
        cur = self._edit.textCursor()
        cur.clearSelection()
        self._edit.setTextCursor(cur)

    def shutdown(self) -> None:
        self._on_mirror_stderr_toggled(False)
        self._mirror_stderr.blockSignals(True)
        self._mirror_stderr.setChecked(False)
        self._mirror_stderr.blockSignals(False)
