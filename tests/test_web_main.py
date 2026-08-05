# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Unit tests for the fcapz-web CLI helpers: OpenOCD binary auto-detection and
config auto-discovery (``--openocd-cfg-dir``)."""

from __future__ import annotations

from pathlib import Path

import pytest

# fcapz.web.__main__ imports the FastAPI app, so skip this module entirely when
# the web extra isn't installed (CI's pytest job installs only .[dev,gui]).
pytest.importorskip("fastapi")

import fcapz.web.__main__ as web_main  # noqa: E402
from fcapz.web.__main__ import (  # noqa: E402
    _build_openocd_launcher,
    _default_cfg_dirs,
    _discover_cfgs,
    _find_openocd,
    _is_shim,
)


def _write_cfg(dirpath: Path, name: str) -> Path:
    p = dirpath / name
    p.write_text("# openocd config\n")
    return p


def _isolate_fs(monkeypatch):
    """Cut _build_openocd_launcher off from the host's real openocd install and
    the repo's example configs, so a test controls exactly what's 'present'."""
    monkeypatch.setattr(web_main, "_openocd_search_roots", lambda: [])
    monkeypatch.setattr(web_main, "_default_cfg_dirs", lambda: [])


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
    _isolate_fs(monkeypatch)
    monkeypatch.setattr(web_main.shutil, "which", lambda name: "/usr/bin/openocd")
    _write_cfg(tmp_path, "arty_a7.cfg")
    launcher = _build_openocd_launcher(None, None, [str(tmp_path)])
    assert launcher is not None
    assert launcher.config_names == ["arty_a7"]


def test_launcher_none_without_binary(tmp_path, monkeypatch, capsys):
    # A config exists but no openocd binary anywhere -> feature disabled.
    _isolate_fs(monkeypatch)
    monkeypatch.setattr(web_main.shutil, "which", lambda name: None)
    _write_cfg(tmp_path, "arty_a7.cfg")
    assert _build_openocd_launcher(None, None, [str(tmp_path)]) is None
    assert "stays disabled" in capsys.readouterr().err


def test_launcher_none_without_config(monkeypatch, capsys):
    _isolate_fs(monkeypatch)
    monkeypatch.setattr(web_main.shutil, "which", lambda name: "/usr/bin/openocd")
    assert _build_openocd_launcher(None, None, None) is None
    assert "stays disabled" in capsys.readouterr().err


def test_launcher_none_when_nothing_configured(monkeypatch):
    # No binary, no configs -> silent None (feature simply not requested).
    _isolate_fs(monkeypatch)
    monkeypatch.setattr(web_main.shutil, "which", lambda name: None)
    assert _build_openocd_launcher(None, None, None) is None


def test_launcher_defaults_to_example_configs(tmp_path, monkeypatch):
    # No configs given -> fall back to the bundled example board configs.
    monkeypatch.setattr(web_main.shutil, "which", lambda name: "/usr/bin/openocd")
    monkeypatch.setattr(
        web_main, "_default_cfg_dirs", lambda: [str(tmp_path)]
    )
    _write_cfg(tmp_path, "brs_100_gw1nr9.cfg")
    launcher = _build_openocd_launcher(None, None, None)
    assert launcher is not None
    assert launcher.config_names == ["brs_100_gw1nr9"]


# -- openocd binary discovery ---------------------------------------------


def test_is_shim():
    assert _is_shim("C:/x/openocd.CMD")
    assert _is_shim("/x/openocd.bat")
    assert _is_shim("/x/openocd.ps1")
    assert not _is_shim("C:/x/openocd.exe")
    assert not _is_shim("/usr/bin/openocd")


def test_find_openocd_explicit_wins(monkeypatch):
    monkeypatch.setattr(web_main.shutil, "which", lambda name: "/on/path/openocd")
    assert _find_openocd("/my/openocd") == "/my/openocd"


def test_find_openocd_prefers_real_exe_over_shim(tmp_path, monkeypatch):
    # which() returns only a .cmd shim; a real .exe lives in a search root.
    shim = tmp_path / "openocd.cmd"
    shim.write_text("@echo off\n")
    real = tmp_path / "xpack-openocd-0.12.0-7" / "bin" / "openocd.exe"
    real.parent.mkdir(parents=True)
    real.write_text("")
    monkeypatch.setattr(web_main.shutil, "which", lambda name: str(shim))
    monkeypatch.setattr(web_main, "_openocd_search_roots", lambda: [tmp_path])
    assert _find_openocd(None) == str(real)


def test_find_openocd_falls_back_to_shim(tmp_path, monkeypatch):
    # No real exe anywhere -> the shim is better than nothing.
    shim = tmp_path / "openocd.cmd"
    shim.write_text("@echo off\n")
    monkeypatch.setattr(web_main.shutil, "which", lambda name: str(shim))
    monkeypatch.setattr(web_main, "_openocd_search_roots", lambda: [])
    assert _find_openocd(None) == str(shim)


def test_find_openocd_uses_path_when_not_shim(monkeypatch):
    monkeypatch.setattr(web_main.shutil, "which", lambda name: "/usr/bin/openocd")
    monkeypatch.setattr(web_main, "_openocd_search_roots", lambda: [])
    assert _find_openocd(None) == "/usr/bin/openocd"


def test_default_cfg_dirs_finds_board_dirs(tmp_path, monkeypatch):
    ex = tmp_path / "examples"
    (ex / "arty_a7").mkdir(parents=True)
    (ex / "brs").mkdir(parents=True)
    (ex / "empty").mkdir(parents=True)  # no .cfg -> skipped
    (ex / "arty_a7" / "arty_a7.cfg").write_text("")
    (ex / "brs" / "brs.cfg").write_text("")
    monkeypatch.chdir(tmp_path)
    dirs = _default_cfg_dirs()
    assert [Path(d).name for d in dirs] == ["arty_a7", "brs"]


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
