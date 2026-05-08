# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

from pathlib import Path

import pytest
from fcapz.analyzer import CaptureConfig, CaptureResult, ProbeSpec, TriggerConfig
from fcapz.gui.multi_capture_wave import (
    WaveCapture,
    export_merged_vcd_text,
    merged_signal_paths,
    write_merged_gtkw,
    write_merged_surfer_command_file,
)

pytestmark = pytest.mark.gui


def _result(*, pre: int, hz: int, probe: str, samples: list[int]) -> CaptureResult:
    cfg = CaptureConfig(
        pretrigger=pre,
        posttrigger=max(0, len(samples) - pre - 1),
        trigger=TriggerConfig("value_match", 0, 0xFF),
        sample_width=8,
        depth=32,
        sample_clock_hz=hz,
        probes=[ProbeSpec(probe, 8, 0)],
    )
    return CaptureResult(config=cfg, samples=samples)


def test_merged_vcd_uses_one_scope_per_capture_and_aligns_triggers() -> None:
    ela0 = WaveCapture("ela0", _result(pre=2, hz=150_000_000, probe="counter", samples=[1, 2, 3]))
    ela1 = WaveCapture(
        "ela1",
        _result(pre=1, hz=130_000_000, probe="counter_xor", samples=[9, 10, 11]),
    )

    text = export_merged_vcd_text([ela0, ela1])

    assert "$scope module fcapz $end" in text
    assert "$scope module ela0 $end" in text
    assert "$scope module ela1 $end" in text
    assert "$var wire 8 ! counter $end" in text
    assert "$var wire 8 \" counter_xor $end" in text
    # 150 MHz rounds to 7 ns/sample, so ELA0 pretrigger=2 sets trigger origin at 14 ns.
    # 130 MHz rounds to 8 ns/sample, so ELA1 starts at 6 ns to align its pretrigger at 14 ns.
    assert "#6\nb00001001 \"" in text
    assert "#14\nb00000011 !\nb00001010 \"" in text


def test_merged_surfer_command_lists_hierarchical_signals(tmp_path: Path) -> None:
    captures = [
        WaveCapture("ela0", _result(pre=2, hz=150_000_000, probe="counter", samples=[1, 2, 3])),
        WaveCapture("ela1", _result(pre=1, hz=130_000_000, probe="counter_xor", samples=[9, 10, 11])),
    ]
    assert merged_signal_paths(captures) == [
        "fcapz.ela0.counter",
        "fcapz.ela1.counter_xor",
    ]

    path = tmp_path / "merged.surfer.txt"
    write_merged_surfer_command_file(captures, path)
    text = path.read_text(encoding="utf-8")

    assert "module_add fcapz" in text
    assert "add_variables fcapz.ela0.counter fcapz.ela1.counter_xor" in text
    assert "cursor_set 14" in text
    assert "marker_set fcapz_trigger" in text


def test_merged_gtkw_uses_vector_ranges(tmp_path: Path) -> None:
    captures = [
        WaveCapture("ela0", _result(pre=0, hz=150_000_000, probe="counter", samples=[1])),
    ]
    vcd = tmp_path / "merged.vcd"
    vcd.write_text("$enddefinitions $end\n", encoding="ascii")
    gtkw = tmp_path / "merged.gtkw"

    write_merged_gtkw(captures, vcd, gtkw)
    text = gtkw.read_text(encoding="utf-8")

    assert "fcapz.ela0.counter[7:0]" in text
