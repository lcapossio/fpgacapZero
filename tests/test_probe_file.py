# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

import argparse
import json

import pytest

from fcapz.analyzer import ProbeSpec
from fcapz.cli import _build_config
from fcapz.probes import (
    PROBE_FILE_FORMAT,
    load_probe_file,
    probe_file_dict,
    probes_to_arg,
    write_probe_file,
)
from fcapz.rpc import RpcServer


def test_probe_file_round_trip(tmp_path):
    path = tmp_path / "design.prob"

    write_probe_file(
        path,
        [ProbeSpec("valid", 1, 0), ProbeSpec("state", 7, 1)],
        sample_width=8,
        sample_clock_hz=125_000_000,
    )

    loaded = load_probe_file(path)
    assert loaded.sample_width == 8
    assert loaded.sample_clock_hz == 125_000_000
    assert probes_to_arg(loaded.probes) == "valid:1:0,state:7:1"


def test_probe_file_dict_is_minimal_and_versioned():
    data = probe_file_dict([ProbeSpec("counter", 8, 0)], sample_width=8)

    assert data["format"] == PROBE_FILE_FORMAT
    assert data["core"] == "ela"
    assert data["sample_width"] == 8
    assert data["probes"] == [{"name": "counter", "width": 8, "lsb": 0}]


def test_probe_file_rejects_overlap(tmp_path):
    path = tmp_path / "bad.prob"
    path.write_text(
        json.dumps(
            {
                "format": PROBE_FILE_FORMAT,
                "sample_width": 8,
                "probes": [
                    {"name": "lo", "width": 4, "lsb": 0},
                    {"name": "mid", "width": 4, "lsb": 2},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="overlaps"):
        load_probe_file(path)


def test_probe_file_rejects_explicit_null_sample_width(tmp_path):
    path = tmp_path / "null_width.prob"
    path.write_text(
        json.dumps(
            {
                "format": PROBE_FILE_FORMAT,
                "sample_width": None,
                "probes": [{"name": "state", "width": 4, "lsb": 0}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="sample_width.*not null"):
        load_probe_file(path)


def test_cli_build_config_loads_probe_file(tmp_path):
    path = tmp_path / "soc.prob"
    write_probe_file(
        path,
        [ProbeSpec("wb_cyc", 1, 0), ProbeSpec("wb_adr", 30, 1)],
        sample_width=31,
        sample_clock_hz=75_000_000,
    )

    cfg = _build_config(
        argparse.Namespace(
            pretrigger=1,
            posttrigger=2,
            trigger_mode="value_match",
            trigger_value=0,
            trigger_mask=0xFF,
            sample_width=None,
            depth=1024,
            sample_clock_hz=None,
            probes=None,
            probe_file=str(path),
            channel=0,
            decimation=0,
            ext_trigger_mode="disabled",
            trigger_sequence=None,
            probe_sel=0,
            stor_qual_mode=0,
            stor_qual_value=0,
            stor_qual_mask=0,
            startup_arm=False,
            trigger_holdoff=0,
            trigger_delay=0,
        )
    )

    assert cfg.sample_width == 31
    assert cfg.sample_clock_hz == 75_000_000
    assert [(p.name, p.width, p.lsb) for p in cfg.probes] == [
        ("wb_cyc", 1, 0),
        ("wb_adr", 30, 1),
    ]


def test_rpc_build_config_loads_probe_file(tmp_path):
    path = tmp_path / "soc.prob"
    write_probe_file(path, [ProbeSpec("state", 4, 0)], sample_width=4)

    cfg = RpcServer._build_config({"probe_file": str(path)})

    assert cfg.sample_width == 4
    assert probes_to_arg(cfg.probes) == "state:4:0"
