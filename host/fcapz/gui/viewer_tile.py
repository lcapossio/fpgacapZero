# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Tile the primary monitor when an external viewer starts.

The main window is resized to the bottom half. On Windows the viewer's largest
top-level window is moved to the top half; elsewhere only the GUI is repositioned.

Horizontally, both halves use the screen's full :meth:`~PySide6.QtGui.QScreen.geometry`
width (entire monitor width). Vertically, the split follows
:meth:`~PySide6.QtGui.QScreen.availableGeometry` so windows stay in the work area.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QProcess, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMainWindow, QWidget

_Rect = tuple[int, int, int, int]


def _primary_vertical_halves() -> tuple[_Rect, _Rect] | None:
    """Return ``(top_rect, bottom_rect)`` as ``(x, y, w, h)`` for the primary screen."""
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None
    geo = screen.geometry()
    ag = screen.availableGeometry()
    h2 = max(1, ag.height() // 2)
    x_full, w_full = geo.x(), geo.width()
    y0, full_h = ag.y(), ag.height()
    top = (x_full, y0, w_full, h2)
    bottom = (x_full, y0 + h2, w_full, full_h - h2)
    return top, bottom


def _place_main_bottom_half(main: QMainWindow, bottom: _Rect) -> None:
    x, y, w, h = bottom
    if main.isMaximized() or main.isFullScreen():
        main.showNormal()
    main.setGeometry(x, y, w, h)
    main.raise_()


def _win32_find_largest_top_level_hwnd(pid: int) -> int | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None

    user32 = ctypes.windll.user32
    GWL_STYLE = -16
    WS_CHILD = 0x40000000
    candidates: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd: int, _lp: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        proc_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
        if int(proc_id.value) != pid:
            return True
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        if style and (int(style) & WS_CHILD):
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        rw = int(rect.right) - int(rect.left)
        rh = int(rect.bottom) - int(rect.top)
        if rw < 160 or rh < 120:
            return True
        candidates.append((hwnd, rw * rh))
        return True

    user32.EnumWindows(_enum, 0)
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[1], reverse=True)
    return int(candidates[0][0])


def _win32_place_hwnd_top_half(hwnd: int, top: _Rect) -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    x, y, w, h = top
    SWP_NOZORDER = 0x0004
    SWP_SHOWWINDOW = 0x0040
    HWND_TOP = 0
    user32.SetWindowPos(
        wintypes.HWND(hwnd),
        wintypes.HWND(HWND_TOP),
        int(x),
        int(y),
        int(w),
        int(h),
        int(SWP_NOZORDER | SWP_SHOWWINDOW),
    )


def _try_vertical_split(host: QWidget, proc: QProcess) -> bool:
    """
    Move main window to bottom half; on Windows move viewer to top half.

    Returns True if the external viewer window was placed (always True on non-Windows
    where only the main window is moved).
    """
    main = host.window()
    if not isinstance(main, QMainWindow):
        return True
    if proc.state() == QProcess.ProcessState.NotRunning:
        return True

    halves = _primary_vertical_halves()
    if halves is None:
        return True
    top, bottom = halves

    _place_main_bottom_half(main, bottom)

    if sys.platform != "win32":
        return True

    pid = int(proc.processId())
    if pid == 0:
        return False

    hwnd = _win32_find_largest_top_level_hwnd(pid)
    if hwnd is None:
        return False
    _win32_place_hwnd_top_half(hwnd, top)
    return True


def schedule_vertical_split_with_viewer(host: QWidget, proc: QProcess) -> None:
    """Call after ``QProcess.started``; retries a few times until the viewer window exists."""
    remaining = [6]

    def _tick() -> None:
        if proc.state() == QProcess.ProcessState.NotRunning:
            return
        ok = _try_vertical_split(host, proc)
        remaining[0] -= 1
        if not ok and remaining[0] > 0:
            QTimer.singleShot(280, _tick)

    QTimer.singleShot(320, _tick)
