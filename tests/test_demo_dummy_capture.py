# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Regression: demo mock analyzer must write real waveform files for the GUI."""

from __future__ import annotations

from pathlib import Path

from fcapz.analyzer import CaptureConfig, CaptureResult, TriggerConfig
from fcapz.gui.demo_dummy_capture import _install_demo_hw_mocks


def test_demo_mock_write_vcd_creates_file(tmp_path: Path) -> None:
    ex, mock_an = _install_demo_hw_mocks()
    try:
        cfg = CaptureConfig(
            pretrigger=0,
            posttrigger=1,
            trigger=TriggerConfig(mode="value_match", value=0, mask=255),
        )
        result = CaptureResult(config=cfg, samples=[0xAA, 0x55], overflow=False)
        vcd = tmp_path / "demo.vcd"
        mock_an.write_vcd(result, str(vcd))
        assert vcd.is_file()
        text = vcd.read_text(encoding="ascii")
        assert "$var" in text
        assert "$dumpvars" in text
    finally:
        ex.close()
