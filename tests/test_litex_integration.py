# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from pathlib import Path

import pytest

from fcapz.litex import add_ela_sources, describe_probe_fields, ela_rtl_sources


class FakePlatform:
    def __init__(self):
        self.sources = []

    def add_source(self, path):
        self.sources.append(Path(path))


class FakeSignal:
    def __init__(self, width):
        self.width = width

    def __len__(self):
        return self.width


def test_describe_probe_fields_preserves_litex_cat_offsets():
    fields = describe_probe_fields(
        {
            "valid": FakeSignal(1),
            "state": FakeSignal(3),
            "counter": FakeSignal(8),
        }
    )

    assert [(field.name, field.width, field.offset) for field in fields] == [
        ("valid", 1, 0),
        ("state", 3, 1),
        ("counter", 8, 4),
    ]


def test_ela_rtl_sources_includes_common_and_vendor_files():
    sources = [path.as_posix() for path in ela_rtl_sources("xilinx7", rtl_dir="rtl")]

    assert "rtl/fcapz_ela.v" in sources
    assert "rtl/fcapz_ela_multi_xilinx7.v" in sources
    assert "rtl/fcapz_core_manager.v" in sources
    assert "rtl/fcapz_debug_multi_xilinx7.v" in sources
    assert "rtl/jtag_pipe_iface.v" in sources
    assert "rtl/fcapz_ela_xilinx7.v" in sources
    assert "rtl/jtag_tap/jtag_tap_xilinx7.v" in sources


def test_ela_rtl_sources_rejects_unknown_vendor():
    with pytest.raises(ValueError, match="unsupported ELA vendor"):
        ela_rtl_sources("mystery")


def test_add_ela_sources_adds_manifest_to_platform():
    platform = FakePlatform()

    add_ela_sources(platform, vendor="xilinxus", rtl_dir="rtl")

    source_names = {source.as_posix() for source in platform.sources}
    assert "rtl/fcapz_ela_xilinxus.v" in source_names
    assert "rtl/fcapz_ela_xilinx7.v" in source_names
