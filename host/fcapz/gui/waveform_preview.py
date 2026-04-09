# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Embedded logic-style waveform preview from :class:`~fcapz.analyzer.CaptureResult`."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..analyzer import CaptureResult

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment, misc]

try:
    import pyqtgraph as pg
except ImportError:
    pg = None  # type: ignore[assignment, misc]

_PREVIEW_COLORS = (
    "#0066cc",
    "#cc5500",
    "#008844",
    "#8844aa",
    "#aa4488",
    "#446688",
)


def lanes_from_capture(result: CaptureResult) -> list[tuple[str, list[int]]]:
    """
    Extract per-lane integer values for each sample (same ordering as VCD export).

    Does not add a separate timestamp lane; the X axis uses timestamps when present.
    """
    cfg = result.config
    out: list[tuple[str, list[int]]] = []
    if cfg.probes:
        for p in cfg.probes:
            mask = (1 << p.width) - 1
            out.append(
                (p.name, [int((int(s) >> p.lsb) & mask) for s in result.samples]),
            )
    else:
        mask = (1 << cfg.sample_width) - 1
        out.append(("sample", [int(s) & mask for s in result.samples]))
    return out


def _x_edges_for_step_plot(x: np.ndarray) -> np.ndarray:
    """PyQtGraph ``stepMode='center'`` expects ``len(x) == len(y) + 1``."""
    x = np.asarray(x, dtype=np.float64)
    n = int(x.size)
    if n == 0:
        return x
    if n == 1:
        return np.array([float(x[0]) - 0.5, float(x[0]) + 0.5])
    d = np.diff(x)
    first = float(x[0] - d[0] * 0.5)
    last = float(x[-1] + d[-1] * 0.5)
    mid = x[:-1] + d * 0.5
    return np.concatenate([[first], mid.astype(np.float64), [last]])


def _x_axis_and_label(result: CaptureResult) -> tuple[list[float], str]:
    cfg = result.config
    n = len(result.samples)
    timescale_ns = max(1, int(round(1_000_000_000 / cfg.sample_clock_hz)))
    if result.timestamps and len(result.timestamps) == n:
        scale_s = timescale_ns * 1e-9
        return [float(t) * scale_s for t in result.timestamps], "Time (s)"
    return [float(i) for i in range(n)], "Sample index"


class WaveformPreviewWidget(QWidget):
    """
    Stacked step plot of captured probes (pyqtgraph).

    If pyqtgraph/numpy are missing, shows an install hint instead.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._plot_widget: QWidget | None = None

        if np is None or pg is None:
            hint = QLabel(
                "Install pyqtgraph for an embedded waveform preview:\n"
                '  pip install "fpgacapzero[gui]"',
            )
            hint.setWordWrap(True)
            layout.addWidget(hint)
            return

        pg.setConfigOption("background", "w")
        pg.setConfigOption("foreground", "k")
        plot = pg.PlotWidget()
        plot.setMinimumHeight(220)
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.setLabel("left", "Lanes (stacked)")
        pi = plot.getPlotItem()
        pi.showAxis("right", False)
        pi.getViewBox().setMouseMode(pg.ViewBox.RectMode)
        layout.addWidget(plot)
        self._plot_widget = plot
        self._plot = plot

    def clear(self) -> None:
        if self._plot_widget is None:
            return
        self._plot.getPlotItem().clear()
        self._plot.setTitle("")
        self._plot.setLabel("bottom", "")

    def show_result(self, result: CaptureResult) -> None:
        if self._plot_widget is None:
            return
        self.clear()
        if not result.samples:
            self._plot.setTitle("No samples")
            return

        x_list, x_label = _x_axis_and_label(result)
        lanes = lanes_from_capture(result)
        x_centers = np.asarray(x_list, dtype=np.float64)
        x_step = _x_edges_for_step_plot(x_centers)
        lane_gap = 0.45
        lane_height = 1.0

        pi = self._plot.getPlotItem()
        pi.addLegend(offset=(-30, 10))
        for i, (name, values) in enumerate(lanes):
            y_raw = np.asarray(values, dtype=np.float64)
            base = float(i) * (lane_height + lane_gap)
            vmax = float(y_raw.max()) if y_raw.size else 0.0
            if vmax <= 1.0:
                y = base + y_raw * lane_height
            else:
                denom = max(vmax, 1.0)
                y = base + (y_raw / denom) * (lane_height * 0.95)

            color = _PREVIEW_COLORS[i % len(_PREVIEW_COLORS)]
            pen = pg.mkPen(color=color, width=2)
            self._plot.plot(
                x_step,
                y,
                stepMode="center",
                pen=pen,
                name=name,
            )

        n_lane = len(lanes)
        ymax = max(n_lane * (lane_height + lane_gap), 0.1)
        self._plot.setYRange(-0.15, ymax + 0.1, padding=0.02)
        self._plot.setLabel("bottom", x_label)
        flag = "overflow" if result.overflow else "ok"
        self._plot.setTitle(f"{len(result.samples)} samples — {flag}")
