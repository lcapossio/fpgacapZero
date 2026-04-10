# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Tile the monitor that hosts the fcapz window when an external viewer starts.

The host window is resized to a **bottom band** (about half the work area or more);
on Windows the viewer's largest top-level window fills the **top** band. Elsewhere only the GUI is
repositioned until platform-specific viewer placement exists.

**Windows:** band **heights** come from Qt :meth:`~PySide6.QtGui.QScreen.availableGeometry`
(logical pixels) so :meth:`~PySide6.QtWidgets.QWidget.setGeometry` matches the screen.
The external viewer is placed with Win32 ``SetWindowPos`` using the full ``rcMonitor``
width (physical virtual-screen coords) and the same ``top_h`` — Surfer stays
edge-to-edge without forcing Qt to use an oversized width (which triggers
``QWindowsWindow::setGeometry`` clamp warnings on mixed-DPI setups).

**Non-Windows:** only the host is tiled, using ``availableGeometry`` for both axes.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QProcess, QTimer
from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtWidgets import QMainWindow, QWidget

_Rect = tuple[int, int, int, int]

# Target share of work-area height for the external viewer (top); host gets the rest.
_VIEWER_HEIGHT_FRACTION = 0.50
# Minimum host strip height (px) so capture / docks stay usable.
_HOST_MIN_HEIGHT_PX = 300
# Also reserve at least this fraction of work-area height for the host (takes precedence on tall screens).
_HOST_MIN_HEIGHT_FRACTION = 0.38
# Preferred minimum height (px) for the viewer; may be reduced if the work area is small.
_VIEWER_MIN_HEIGHT_PX = 120


def split_work_area_vertical(
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    viewer_height_fraction: float = _VIEWER_HEIGHT_FRACTION,
    host_min_height_px: int = _HOST_MIN_HEIGHT_PX,
    viewer_min_height_px: int = _VIEWER_MIN_HEIGHT_PX,
) -> tuple[_Rect, _Rect] | None:
    """
    Split a work-area rectangle into ``(top, bottom)`` as ``(x, y, w, h)``.

    The top region is sized for the waveform viewer (~``viewer_height_fraction`` of
    ``h``), with at least ``host_min_height_px`` for the bottom strip when the work
    area is tall enough.
    """
    if h < 2 or w < 1:
        return None
    # Host strip must be tall enough for the capture GUI; on large screens also use a % of work area.
    min_host = max(
        min(host_min_height_px, h - 1),
        max(96, int(h * _HOST_MIN_HEIGHT_FRACTION)),
    )
    min_host = min(min_host, h - viewer_min_height_px - 1)
    min_host = max(1, min_host)

    top_h = max(viewer_min_height_px, int(h * viewer_height_fraction))
    top_h = min(top_h, h - min_host)
    bottom_h = h - top_h
    if bottom_h < min_host:
        bottom_h = min(min_host, h - 1)
        top_h = h - bottom_h

    top: _Rect = (x, y, w, top_h)
    bottom: _Rect = (x, y + top_h, w, bottom_h)
    return top, bottom


def _screen_for_host_widget(host: QWidget) -> QScreen | None:
    """Screen containing the host window (not necessarily the primary display)."""
    main = host.window()
    handle = main.windowHandle()
    if handle is not None:
        s = handle.screen()
        if s is not None:
            return s
    center = main.mapToGlobal(main.rect().center())
    return QGuiApplication.screenAt(center)


def _qt_work_area_vertical_halves(screen: QScreen | None) -> tuple[_Rect, _Rect] | None:
    """Split the Qt **available** work area for host ``setGeometry`` (logical pixels)."""
    if screen is None:
        return None
    ag = screen.availableGeometry()
    return split_work_area_vertical(ag.x(), ag.y(), ag.width(), ag.height())


def _win32_viewer_top_band(host_hwnd: int, top_h: int) -> _Rect | None:
    """
    Top-of-screen band for ``SetWindowPos`` on the external viewer: full ``rcMonitor``
    width, ``top_h`` height, aligned to work-area top (Win32 coords).
    """
    if sys.platform != "win32" or host_hwnd == 0 or top_h < 1:
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None

    user32 = ctypes.windll.user32
    MONITOR_DEFAULTTONEAREST = 2

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    hmon = user32.MonitorFromWindow(wintypes.HWND(host_hwnd), MONITOR_DEFAULTTONEAREST)
    if not hmon:
        return None
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return None
    mon = mi.rcMonitor
    work = mi.rcWork
    mon_left = int(mon.left)
    mon_w = int(mon.right) - int(mon.left)
    work_top = int(work.top)
    return (mon_left, work_top, mon_w, top_h)


def _place_main_bottom_half(main: QMainWindow, bottom: _Rect) -> None:
    x, y, w, h = bottom
    if main.isMaximized() or main.isFullScreen():
        main.showNormal()
    screen = main.screen()
    if screen is not None:
        ag = screen.availableGeometry()
        mw = max(main.minimumWidth(), 1)
        mh = max(main.minimumHeight(), 1)
        w = max(w, mw)
        h = max(h, mh)
        w = min(w, ag.width())
        h = min(h, ag.height())
        x = max(ag.left(), min(x, ag.left() + ag.width() - w))
        y = max(ag.top(), min(y, ag.top() + ag.height() - h))
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
    Move main window to the bottom strip; on Windows move viewer to the top region.

    Returns True if the external viewer window was placed (always True on non-Windows
    where only the main window is moved).
    """
    main = host.window()
    if not isinstance(main, QMainWindow):
        return True
    if proc.state() == QProcess.ProcessState.NotRunning:
        return True

    screen = _screen_for_host_widget(host)
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    halves_qt = _qt_work_area_vertical_halves(screen)
    if halves_qt is None:
        return True
    _top_qt, bottom_qt = halves_qt

    _place_main_bottom_half(main, bottom_qt)

    if sys.platform != "win32":
        return True

    pid = int(proc.processId())
    if pid == 0:
        return False

    hwnd = _win32_find_largest_top_level_hwnd(pid)
    if hwnd is None:
        return False
    wid = int(main.winId())
    top_win = _win32_viewer_top_band(wid, _top_qt[3])
    if top_win is None:
        return False
    _win32_place_hwnd_top_half(hwnd, top_win)
    return True


def schedule_vertical_split_with_viewer(host: QWidget, proc: QProcess) -> None:
    """Call after ``QProcess.started``; retries until the viewer window exists (wgpu/egui can be slow)."""
    remaining = [14]

    def _tick() -> None:
        if proc.state() == QProcess.ProcessState.NotRunning:
            return
        ok = _try_vertical_split(host, proc)
        remaining[0] -= 1
        if not ok and remaining[0] > 0:
            QTimer.singleShot(260, _tick)

    QTimer.singleShot(420, _tick)
