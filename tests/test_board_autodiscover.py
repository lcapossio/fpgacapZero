# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Unit tests for OpenOCD board auto-discovery (USB filter -> probe)."""

from __future__ import annotations

import fcapz.board_autodiscover as bad
from fcapz.board_autodiscover import (
    auto_discover_boards,
    candidate_configs,
    parse_cfg_vid_pids,
)


def _cfg(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body)
    return str(p)


# -- config VID/PID parsing ------------------------------------------------


def test_parse_single_vid_pid(tmp_path):
    p = _cfg(tmp_path, "arty.cfg", "adapter driver ftdi\nftdi vid_pid 0x0403 0x6010\n")
    assert parse_cfg_vid_pids(p) == {(0x0403, 0x6010)}


def test_parse_legacy_and_multiple_pairs(tmp_path):
    p = _cfg(tmp_path, "x.cfg", "ftdi_vid_pid 0x0403 0x6010 0x0403 0x6014\n")
    assert parse_cfg_vid_pids(p) == {(0x0403, 0x6010), (0x0403, 0x6014)}


def test_parse_ch347_and_bare_vid_pid(tmp_path):
    # Non-FTDI adapters (WCH CH347) and a bare vid_pid are honoured too.
    p = _cfg(
        tmp_path,
        "ch347.cfg",
        "adapter driver ch347\nch347 vid_pid 0x1a86 0x55dd\n",
    )
    assert parse_cfg_vid_pids(p) == {(0x1A86, 0x55DD)}


def test_parse_ignores_comments_and_missing(tmp_path):
    p = _cfg(tmp_path, "c.cfg", "# ftdi vid_pid 0x1111 0x2222\nsource [find hs3.cfg]\n")
    assert parse_cfg_vid_pids(p) == set()


def test_parse_unreadable_returns_empty(tmp_path):
    assert parse_cfg_vid_pids(str(tmp_path / "nope.cfg")) == set()


# -- candidate filtering ---------------------------------------------------


def test_candidates_none_usb_keeps_all(tmp_path):
    cfgs = {"a": _cfg(tmp_path, "a.cfg", "ftdi vid_pid 0x0403 0x6010\n")}
    assert candidate_configs(cfgs, None) == ["a"]


def test_candidates_filter_by_present_usb(tmp_path):
    cfgs = {
        "arty": _cfg(tmp_path, "arty.cfg", "ftdi vid_pid 0x0403 0x6010\n"),
        "other": _cfg(tmp_path, "other.cfg", "ftdi vid_pid 0x1234 0x5678\n"),
    }
    assert candidate_configs(cfgs, {(0x0403, 0x6010)}) == ["arty"]


def test_candidates_unknown_vidpid_always_kept(tmp_path):
    cfgs = {
        "hs3": _cfg(tmp_path, "hs3.cfg", "source [find hs3.cfg]\n"),  # no vid_pid
        "arty": _cfg(tmp_path, "arty.cfg", "ftdi vid_pid 0x9 0x9\n"),
    }
    # USB has neither; only the config that names no VID/PID survives.
    assert candidate_configs(cfgs, {(0x1, 0x1)}) == ["hs3"]


# -- orchestration ---------------------------------------------------------


class FakeLauncher:
    """Records start/stop calls; per-config board results feed discover_boards."""

    def __init__(self, configs, boards_by_port):
        self._configs = configs
        self.boards_by_port = boards_by_port  # port -> list[dict]
        self.started = []  # (name, port)
        self.stopped = []  # port
        self.fail_configs = set()

    @property
    def configs(self):
        return dict(self._configs)

    def start(self, *, name, port, wait_sec=10.0):
        if name in self.fail_configs:
            raise RuntimeError(f"adapter busy for {name}")
        self.started.append((name, port))
        return {"started": True, "port": port}

    def stop(self, *, port):
        self.stopped.append(port)
        return {"stopped": True, "port": port}


def _patch_discover(monkeypatch, launcher):
    def fake_discover(*, host, ports, chain, timeout_sec):
        out = []
        for p in ports:
            out.extend(launcher.boards_by_port.get(p, []))
        return out
    monkeypatch.setattr(bad, "discover_boards", fake_discover)


def test_auto_discover_single_board(tmp_path, monkeypatch):
    cfgs = {"arty": _cfg(tmp_path, "arty.cfg", "ftdi vid_pid 0x0403 0x6010\n")}
    board = {"backend": "openocd", "host": "127.0.0.1", "port": 6666, "tap": "t"}
    lch = FakeLauncher(cfgs, {6666: [board]})
    _patch_discover(monkeypatch, lch)

    found = auto_discover_boards(lch, present_usb={(0x0403, 0x6010)})
    assert len(found) == 1
    assert found[0]["config"] == "arty"
    assert found[0]["port"] == 6666
    assert lch.started == [("arty", 6666)]
    assert lch.stopped == []  # confirmed instance stays running


def test_auto_discover_stops_empty_probe(tmp_path, monkeypatch):
    cfgs = {"arty": _cfg(tmp_path, "arty.cfg", "ftdi vid_pid 0x0403 0x6010\n")}
    lch = FakeLauncher(cfgs, {})  # nothing answers
    _patch_discover(monkeypatch, lch)

    found = auto_discover_boards(lch, present_usb={(0x0403, 0x6010)})
    assert found == []
    assert lch.stopped == [6666]  # unproductive instance stopped


def test_auto_discover_ambiguous_first_wins(tmp_path, monkeypatch):
    # Two configs share the adapter; first claims it, second start() raises.
    cfgs = {
        "arty": _cfg(tmp_path, "arty.cfg", "ftdi vid_pid 0x0403 0x6010\n"),
        "brs": _cfg(tmp_path, "brs.cfg", "ftdi vid_pid 0x0403 0x6010\n"),
    }
    board = {"backend": "openocd", "port": 6666, "tap": "t"}
    lch = FakeLauncher(cfgs, {6666: [board]})
    lch.fail_configs = {"brs"}  # arty sorts first, claims 6666; brs busy on 6667
    _patch_discover(monkeypatch, lch)

    found = auto_discover_boards(lch, present_usb={(0x0403, 0x6010)})
    assert [b["config"] for b in found] == ["arty"]
    assert 6667 in lch.stopped  # busy probe cleaned up


def test_auto_discover_none_usb_probes_all(tmp_path, monkeypatch):
    cfgs = {
        "a": _cfg(tmp_path, "a.cfg", "ftdi vid_pid 0x1 0x1\n"),
        "b": _cfg(tmp_path, "b.cfg", "ftdi vid_pid 0x2 0x2\n"),
    }
    board = {"backend": "openocd", "port": 6667, "tap": "t"}
    lch = FakeLauncher(cfgs, {6667: [board]})  # board answers only on 2nd port
    _patch_discover(monkeypatch, lch)

    found = auto_discover_boards(lch, present_usb=None)  # skip filtering
    assert [name for name, _ in lch.started] == ["a", "b"]
    assert [b["config"] for b in found] == ["b"]
