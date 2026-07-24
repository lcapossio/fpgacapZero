# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Unit tests for the fcapz-web CLI helpers: OpenOCD binary auto-detection and
config auto-discovery (``--openocd-cfg-dir``)."""

from __future__ import annotations

from pathlib import Path

import fcapz.web.__main__ as web_main
from fcapz.web.__main__ import _build_openocd_launcher, _discover_cfgs


def _write_cfg(dirpath: Path, name: str) -> Path:
    p = dirpath / name
    p.write_text("# openocd config\n")
    return p


def test_discover_cfgs_globs_directory(tmp_path):
    _write_cfg(tmp_path, "arty_a7.cfg")
    _write_cfg(tmp_path, "arty_a7_hs3.cfg")
    (tmp_path / "notes.txt").write_text("ignore me")
    found = _discover_cfgs([str(tmp_path)])
    assert [Path(p).name for p in found] == ["arty_a7.cfg", "arty_a7_hs3.cfg"]


def test_discover_cfgs_skips_missing_dir(tmp_path, capsys):
    found = _discover_cfgs([str(tmp_path / "nope")])
    assert found == []
    assert "not a directory" in capsys.readouterr().err


def test_launcher_auto_detects_binary_and_discovers_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(web_main.shutil, "which", lambda name: "/usr/bin/openocd")
    _write_cfg(tmp_path, "arty_a7.cfg")
    launcher = _build_openocd_launcher(None, None, [str(tmp_path)])
    assert launcher is not None
    assert launcher.config_names == ["arty_a7"]


def test_launcher_none_without_binary(tmp_path, monkeypatch, capsys):
    # A config exists but no openocd binary anywhere -> feature disabled.
    monkeypatch.setattr(web_main.shutil, "which", lambda name: None)
    _write_cfg(tmp_path, "arty_a7.cfg")
    assert _build_openocd_launcher(None, None, [str(tmp_path)]) is None
    assert "stays disabled" in capsys.readouterr().err


def test_launcher_none_without_config(monkeypatch, capsys):
    monkeypatch.setattr(web_main.shutil, "which", lambda name: "/usr/bin/openocd")
    assert _build_openocd_launcher(None, None, None) is None
    assert "stays disabled" in capsys.readouterr().err


def test_launcher_none_when_nothing_configured(monkeypatch):
    # No binary, no configs -> silent None (feature simply not requested).
    monkeypatch.setattr(web_main.shutil, "which", lambda name: None)
    assert _build_openocd_launcher(None, None, None) is None


def test_launcher_merges_explicit_and_discovered(tmp_path, monkeypatch):
    explicit = _write_cfg(tmp_path, "custom.cfg")
    disc_dir = tmp_path / "boards"
    disc_dir.mkdir()
    _write_cfg(disc_dir, "arty_a7.cfg")
    launcher = _build_openocd_launcher(
        "/usr/bin/openocd", [str(explicit)], [str(disc_dir)]
    )
    assert launcher.config_names == ["arty_a7", "custom"]


def test_launcher_dedupes_duplicate_stem(tmp_path, monkeypatch, capsys):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _write_cfg(a, "arty_a7.cfg")
    _write_cfg(b, "arty_a7.cfg")  # same stem, different path
    launcher = _build_openocd_launcher(
        "/usr/bin/openocd", None, [str(a), str(b)]
    )
    assert launcher.config_names == ["arty_a7"]  # first wins
    assert "duplicate OpenOCD config name" in capsys.readouterr().err
