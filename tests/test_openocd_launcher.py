# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Unit tests for the server-side OpenOCD launcher (no real OpenOCD spawned)."""

from __future__ import annotations

import subprocess

import pytest

from fcapz.openocd_launcher import OpenOcdLauncher


class _FakeProc:
    def __init__(self, exit_code=None, pid=4321):
        self._exit = exit_code  # None = still running
        self.pid = pid
        self.returncode = exit_code
        self.terminated = False

    def poll(self):
        return self._exit

    def terminate(self):
        self.terminated = True
        self._exit = -15
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self._exit = -9


def _launcher(tmp_path, **kw):
    cfg = tmp_path / "brd.cfg"
    cfg.write_text("init\n")
    return OpenOcdLauncher(openocd="openocd", configs={"brd": str(cfg)}, **kw)


def test_config_names_and_unknown_config(tmp_path):
    launcher = _launcher(tmp_path)
    assert launcher.config_names == ["brd"]
    with pytest.raises(ValueError):
        launcher._resolve_config("nope")


def test_resolve_requires_name_when_multiple(tmp_path):
    (tmp_path / "a.cfg").write_text("init")
    (tmp_path / "b.cfg").write_text("init")
    launcher = OpenOcdLauncher(
        openocd="openocd",
        configs={"a": str(tmp_path / "a.cfg"), "b": str(tmp_path / "b.cfg")},
    )
    with pytest.raises(ValueError):
        launcher._resolve_config(None)  # ambiguous
    assert launcher._resolve_config("a")[0] == "a"


def test_start_noop_when_port_already_open(tmp_path, monkeypatch):
    launcher = _launcher(tmp_path)
    monkeypatch.setattr(launcher, "_port_open", lambda port, timeout=0.3: True)
    spawned = {"popen": False}
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: spawned.__setitem__("popen", True)
    )
    r = launcher.start(port=6666)
    assert r == {"started": False, "already_running": True, "mine": False, "port": 6666}
    assert spawned["popen"] is False  # nothing launched


def test_start_spawns_and_waits_for_port(tmp_path, monkeypatch):
    launcher = _launcher(tmp_path)
    state = {"spawned": False}
    monkeypatch.setattr(launcher, "_port_open", lambda port, timeout=0.3: state["spawned"])

    def fake_popen(*a, **k):
        state["spawned"] = True  # port comes up right after launch
        return _FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    r = launcher.start(port=6666, wait_sec=2.0)
    assert r["started"] is True and r["port"] == 6666 and r["config"] == "brd"
    status = launcher.status()
    assert status["enabled"] is True
    assert any(x["port"] == 6666 for x in status["running"])


def test_start_early_exit_raises_with_log(tmp_path, monkeypatch):
    launcher = _launcher(tmp_path)
    monkeypatch.setattr(launcher, "_port_open", lambda port, timeout=0.3: False)

    def fake_popen(*a, **k):
        logf = k.get("stdout")
        if logf is not None:
            logf.write(b"Error: unable to open ftdi device\n")
            logf.flush()
        return _FakeProc(exit_code=1)  # died immediately

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    with pytest.raises(RuntimeError) as ei:
        launcher.start(port=6666, wait_sec=1.0)
    assert "exited early" in str(ei.value)
    assert "ftdi" in str(ei.value)  # log tail surfaced


def test_start_waits_on_pending_spawn_instead_of_double_spawn(tmp_path, monkeypatch):
    """A second start on the same port during OpenOCD's bind window (spawned,
    TCL port not open yet) must not spawn again — that would orphan the first
    process — but wait on the pending one."""
    from fcapz.openocd_launcher import _Managed

    launcher = _launcher(tmp_path)
    pending = _FakeProc(pid=1111)
    log = tmp_path / "pending.log"
    log.write_text("")
    launcher._managed[6666] = _Managed(proc=pending, log_path=str(log), config="brd")

    calls = {"n": 0}

    def port_open(port, timeout=0.3):
        calls["n"] += 1
        return calls["n"] >= 2  # port opens while we wait

    monkeypatch.setattr(launcher, "_port_open", port_open)
    spawned = {"popen": False}
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: spawned.__setitem__("popen", True)
    )

    r = launcher.start(port=6666, wait_sec=2.0)
    assert spawned["popen"] is False  # no second OpenOCD
    assert r["started"] is False and r["already_running"] is True
    assert r["mine"] is True and r["pid"] == 1111


def test_stop_foreign_port_is_noop(tmp_path):
    launcher = _launcher(tmp_path)
    r = launcher.stop(port=6666)
    assert r["stopped"] is False  # we never started one here


def test_stop_terminates_what_we_started(tmp_path, monkeypatch):
    launcher = _launcher(tmp_path)
    state = {"spawned": False}
    monkeypatch.setattr(launcher, "_port_open", lambda port, timeout=0.3: state["spawned"])
    proc = _FakeProc()

    def fake_popen(*a, **k):
        state["spawned"] = True
        return proc

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    launcher.start(port=6666, wait_sec=2.0)
    r = launcher.stop(port=6666)
    assert r["stopped"] is True and proc.terminated is True
