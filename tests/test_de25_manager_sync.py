# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DE25 = ROOT / "examples" / "de25_nano"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tcl_sources() -> list[str]:
    tcl = _read(DE25 / "build_de25_nano_manager.tcl")
    sources = []
    for base, rel in re.findall(r'"\$\{(repo_path|example_dir)\}/([^"]+)"', tcl):
        if rel.endswith(".v"):
            sources.append(rel if base == "repo_path" else f"examples/de25_nano/{rel}")
    return sources


def test_manager_build_compiles_the_intel_hub_layers() -> None:
    sources = _tcl_sources()
    for layer in (
        "rtl/fcapz_core_manager.v",
        "rtl/fcapz_debug_multi_core.v",
        "rtl/fcapz_debug_multi.v",
        "rtl/fcapz_debug_multi_intel.v",
        "rtl/jtag_tap/jtag_tap_intel.v",
        "examples/de25_nano/de25_nano_manager_top.v",
    ):
        assert layer in sources, f"build_de25_nano_manager.tcl missing {layer}"


def test_manager_freshness_list_covers_every_build_input() -> None:
    hw_test = _read(DE25 / "test_hw_manager.py")
    block = re.search(r"_BITSTREAM_SOURCES\s*=\s*\[(?P<body>.*?)\n\]", hw_test, re.S)
    assert block is not None
    listed = set()
    for parts in re.findall(r"_ROOT((?:\s*/\s*\"[^\"]+\")+)", block.group("body")):
        listed.add("/".join(re.findall(r'"([^"]+)"', parts)))
    for name in re.findall(r'_EXAMPLE_DIR\s*/\s*"([^"]+)"', block.group("body")):
        listed.add(f"examples/de25_nano/{name}")
    for source in _tcl_sources():
        assert source in listed, f"test_hw_manager.py freshness list missing {source}"
    for extra in (
        "rtl/fcapz_version.vh",
        "examples/de25_nano/build_de25_nano_manager.tcl",
        "examples/de25_nano/de25_nano.qsf",
        "examples/de25_nano/de25_nano.sdc",
    ):
        assert extra in listed, f"test_hw_manager.py freshness list missing {extra}"


def test_manager_top_puts_the_hub_on_instance_1() -> None:
    top = _read(DE25 / "de25_nano_manager_top.v")
    hub = re.search(r"fcapz_debug_multi_intel\s*#\s*\((?P<params>.*?)\)\s*u_debug", top, re.S)
    assert hub is not None
    params = re.sub(r"\s+", "", hub.group("params"))
    for expected in (".CTRL_CHAIN(1)", ".NUM_ELAS(2)", ".NUM_EIOS(2)", ".TIMESTAMP_W(32)"):
        assert expected in params, f"hub missing {expected}"
    assert re.search(r"fcapz_ejtagaxi_intel\s*#\s*\(.*?\.CHAIN\(4\)", top, re.S)
