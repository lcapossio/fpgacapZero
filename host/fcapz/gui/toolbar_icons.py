# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Hand-drawn QIcons for the main toolbar.

``QStyle.standardIcon`` is often empty on Windows. A stylesheet on ``QToolButton``
can also suppress icon painting; the main window avoids styling tool buttons.

Stroke color follows light/dark so glyphs stay visible on the native toolbar.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QIcon,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QPolygonF,
)

_Draw = Callable[[QPainter, int, QColor], None]


def _fallback_stroke_color() -> QColor:
    hints = QGuiApplication.styleHints()
    scheme = hints.colorScheme() if hasattr(hints, "colorScheme") else Qt.ColorScheme.Unknown
    if scheme == Qt.ColorScheme.Dark:
        return QColor(240, 242, 248)
    if scheme == Qt.ColorScheme.Light:
        return QColor(28, 32, 42)
    pal = QGuiApplication.palette()
    win = pal.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Window)
    if win.lightness() < 128:
        return QColor(240, 242, 248)
    return QColor(28, 32, 42)


def _stroke_color(toolbar_palette: QPalette | None) -> QColor:
    """Prefer the toolbar's ``ButtonText`` vs ``Window`` contrast; then theme fallback."""
    if toolbar_palette is not None:
        btn = toolbar_palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.ButtonText)
        bg = toolbar_palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Window)
        if abs(btn.lightness() - bg.lightness()) > 20:
            return btn
    return _fallback_stroke_color()


def _pen(fg: QColor, width: float = 1.8) -> QPen:
    pen = QPen(fg)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _disabled_stroke(
    active_fg: QColor,
    toolbar_palette: QPalette | None,
) -> QColor:
    """Muted color for ``QIcon.Mode.Disabled`` so toolbar actions read clearly when off."""
    if toolbar_palette is not None:
        return toolbar_palette.color(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.ButtonText,
        )
    c = QColor(active_fg)
    c.setAlpha(100)
    return c


def _icon(draw: _Draw, toolbar_palette: QPalette | None, *, logical_size: int = 24) -> QIcon:
    fg = _stroke_color(toolbar_palette)
    screen = QGuiApplication.primaryScreen()
    dpr = float(screen.devicePixelRatio()) if screen is not None else 1.0
    phys = max(1, int(round(logical_size * dpr)))

    def _render(stroke: QColor) -> QPixmap:
        pm = QPixmap(phys, phys)
        pm.fill(Qt.GlobalColor.transparent)
        pm.setDevicePixelRatio(dpr)
        pt = QPainter(pm)
        pt.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw(pt, phys, stroke)
        pt.end()
        return pm

    icon = QIcon(_render(fg))
    icon.addPixmap(_render(_disabled_stroke(fg, toolbar_palette)), QIcon.Mode.Disabled)
    return icon


def _draw_connect(p: QPainter, s: int, fg: QColor) -> None:
    p.setPen(_pen(fg, 2.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(int(0.18 * s), int(0.36 * s), int(0.26 * s), int(0.32 * s))
    p.drawEllipse(int(0.56 * s), int(0.36 * s), int(0.26 * s), int(0.32 * s))
    p.drawLine(int(0.44 * s), int(0.52 * s), int(0.56 * s), int(0.52 * s))


def _draw_disconnect(p: QPainter, s: int, fg: QColor) -> None:
    p.setPen(_pen(fg, 2.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(int(0.14 * s), int(0.38 * s), int(0.22 * s), int(0.28 * s))
    p.drawEllipse(int(0.64 * s), int(0.38 * s), int(0.22 * s), int(0.28 * s))
    p.drawLine(int(0.26 * s), int(0.52 * s), int(0.42 * s), int(0.52 * s))
    p.drawLine(int(0.58 * s), int(0.52 * s), int(0.74 * s), int(0.52 * s))
    p.setPen(_pen(fg, 2.4))
    p.drawLine(int(0.22 * s), int(0.22 * s), int(0.78 * s), int(0.78 * s))


def _draw_configure(p: QPainter, s: int, fg: QColor) -> None:
    p.setPen(_pen(fg, 1.6))
    p.setBrush(QBrush(fg))
    for i, kx in enumerate((0.38, 0.62, 0.32)):
        y = int((0.22 + i * 0.28) * s)
        p.drawLine(int(0.16 * s), y, int(0.84 * s), y)
        p.drawEllipse(int(kx * s - 3), y - 3, 6, 6)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _draw_arm(p: QPainter, s: int, fg: QColor) -> None:
    p.setBrush(QBrush(fg))
    p.setPen(Qt.PenStyle.NoPen)
    tri = QPolygonF(
        [
            QPointF(0.24 * s, 0.22 * s),
            QPointF(0.24 * s, 0.78 * s),
            QPointF(0.76 * s, 0.50 * s),
        ],
    )
    p.drawPolygon(tri)


def _draw_capture(p: QPainter, s: int, fg: QColor) -> None:
    p.setPen(_pen(fg, 2.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx = 0.50 * s
    p.drawLine(int(cx), int(0.20 * s), int(cx), int(0.62 * s))
    p.drawLine(int(cx), int(0.62 * s), int(0.30 * s), int(0.42 * s))
    p.drawLine(int(cx), int(0.62 * s), int(0.70 * s), int(0.42 * s))


def _draw_continuous(p: QPainter, s: int, fg: QColor) -> None:
    p.setPen(_pen(fg, 2.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = int(0.18 * s)
    side = int(0.64 * s)
    p.drawArc(m, m, side, side, 50 * 16, 240 * 16)
    p.drawLine(int(0.72 * s), int(0.30 * s), int(0.78 * s), int(0.22 * s))
    p.drawLine(int(0.72 * s), int(0.30 * s), int(0.64 * s), int(0.26 * s))


def _draw_stop(p: QPainter, s: int, fg: QColor) -> None:
    m = int(0.30 * s)
    side = int(s - 2 * m)
    p.setBrush(QBrush(fg))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRect(m, m, side, side)


_DRAWERS: dict[str, _Draw] = {
    "connect": _draw_connect,
    "disconnect": _draw_disconnect,
    "configure": _draw_configure,
    "arm": _draw_arm,
    "capture": _draw_capture,
    "continuous": _draw_continuous,
    "stop": _draw_stop,
}


def main_toolbar_icon(
    which: str,
    *,
    toolbar_palette: QPalette | None = None,
    logical_size: int = 24,
) -> QIcon:
    draw = _DRAWERS[which]
    return _icon(draw, toolbar_palette, logical_size=logical_size)
