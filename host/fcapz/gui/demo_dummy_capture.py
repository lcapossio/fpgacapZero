# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Launch fcapz-gui with one synthetic history row (no JTAG / hardware).

Run from the repo (with the package on ``PYTHONPATH`` or an editable install)::

    python -m fcapz.gui.demo_dummy_capture

Or after ``pip install -e '.[gui]'``::

    python -m fcapz.gui.demo_dummy_capture
"""

from __future__ import annotations

import sys

from ..analyzer import Analyzer, CaptureConfig, CaptureResult, ProbeSpec, TriggerConfig
from ..transport import VendorStubTransport


def _dummy_result() -> CaptureResult:
    """A short 8-bit capture with three named probes for the embedded preview."""
    cfg = CaptureConfig(
        pretrigger=32,
        posttrigger=31,
        trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
        sample_width=8,
        depth=1024,
        sample_clock_hz=100_000_000,
        probes=[
            ProbeSpec("clk", 1, 0),
            ProbeSpec("nibble", 4, 1),
            ProbeSpec("tag", 3, 5),
        ],
        channel=0,
        decimation=0,
        ext_trigger_mode=0,
        sequence=None,
        probe_sel=0,
        stor_qual_mode=0,
        stor_qual_value=0,
        stor_qual_mask=0,
        trigger_delay=0,
    )
    samples: list[int] = []
    for i in range(64):
        clk = i & 1
        nibble = (i >> 1) & 0xF
        tag = (i >> 3) & 0x7
        samples.append(clk | (nibble << 1) | (tag << 5))
    return CaptureResult(config=cfg, samples=samples, overflow=False)


def main(_argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(
            "demo_dummy_capture needs PySide6 "
            "(install: pip install 'fpgacapzero[gui]')",
            file=sys.stderr,
        )
        return 1

    # Build window first so user config / viewers load like a normal session.
    app = QApplication.instance() or QApplication(sys.argv)
    from .app_window import MainWindow

    w = MainWindow(restore_saved_layout=False, persist_window_layout=False)
    analyzer = Analyzer(VendorStubTransport("demo"))
    w._history.set_analyzer_ref(analyzer)
    w._history.add_capture(analyzer, _dummy_result())
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
