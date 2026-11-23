# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""``fcapz --broker`` and ``fcapz broker status|stop`` on a fake transport.
``--port 1`` keeps a command that would run direct from finding a board."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_broker import broker_env  # noqa: E402, F401 - the fixture

from fcapz.broker import BrokerSession, TargetSpec  # noqa: E402
from fcapz.broker.runtime import read_info  # noqa: E402

from fcapz import cli  # noqa: E402

pytestmark = pytest.mark.usefixtures("broker_env")


def _cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["--port", "1", *argv])
    return code, out.getvalue(), err.getvalue()


def test_cli_capture_through_the_broker(monkeypatch, tmp_path):
    monkeypatch.setenv("FCAPZ_BROKER_FAKE_AUTO", "1")
    path = tmp_path / "cap.json"
    code, out, err = _cli("--broker", "capture", "--out", str(path),
                          "--pretrigger", "2", "--posttrigger", "4")
    assert code == 0, err
    assert "captured 7 samples" in out
    assert len(json.loads(path.read_text(encoding="utf-8"))["samples"]) == 7
    code, out, err = _cli("--broker", "eio-read", "--chain", "3")
    assert (code, out.strip()) == (0, "0xA5"), err
    code, out, err = _cli("--broker", "eio-write", "--chain", "3", "0x3C")
    assert code == 0 and "wrote 0x3C" in out, err
    code, out, _ = _cli("broker", "status", "--json")
    assert code == 0 and json.loads(out)["running"]
    code, out, _ = _cli("broker", "stop")
    assert code == 0 and "stopped broker" in out


def test_cli_status_and_stop_see_a_broker_that_is_still_closing_its_cables(
        broker_env, monkeypatch):  # noqa: F811 - the fixture
    # runtime.json goes before the cables are closed: "not running" then
    # would be wrong, and stop must not return before they are.
    rdir, _ = broker_env
    monkeypatch.setenv("FCAPZ_BROKER_FAKE_CLOSE_S", "2.0")
    with BrokerSession.connect(rdir) as s:
        assert s.eio(TargetSpec(), "read", chain=3)["value"] == 0xA5
        assert s.stop(wait=0) is False
        deadline = time.monotonic() + 10
        while read_info(rdir) is not None and time.monotonic() < deadline:
            time.sleep(0.02)
        code, out, _ = _cli("broker", "status")
        assert code == 1 and "shutting down" in out
        code, out, _ = _cli("broker", "status", "--json")
        assert code == 1 and json.loads(out) == {"running": False, "stopping": True}
        code, out, _ = _cli("broker", "stop")
        assert code == 0 and "it has stopped" in out
        assert not BrokerSession.shutting_down(rdir)
    code, out, _ = _cli("broker", "status", "--json")
    assert code == 1 and json.loads(out) == {"running": False, "stopping": False}


def test_cli_broker_env_and_refusals(monkeypatch):
    monkeypatch.setenv("FCAPZ_BROKER", "1")
    code, _, err = _cli("arm")
    assert code == 2 and "does not run through the broker" in err
    code, _, err = _cli("openocd-bridge")       # it would open the adapter itself
    assert code == 2 and "does not run through the broker" in err
    code, _, err = _cli("--program", "x.bit", "probe")
    assert code == 2 and "--program" in err
    code, out, _ = _cli("broker", "status")
    assert code == 1 and "no fcapz broker is running" in out
    assert not cli._use_broker(cli.build_parser().parse_args(["--no-broker", "probe"]))
