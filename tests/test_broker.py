# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""The broker: codec, identities, the operations engine, and the runtime and
its clients as real processes (on a fake transport, no board)."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from broker_fake import FakeElaTransport  # noqa: E402

from fcapz.analyzer import (  # noqa: E402
    CaptureConfig,
    CaptureNotReady,
    CaptureResult,
    ProbeSpec,
    SequencerStage,
    TriggerConfig,
)
from fcapz.broker import (  # noqa: E402
    BrokerConnectionLost,
    BrokerNotRunning,
    BrokerSession,
    BrokerStartError,
    CoreBusy,
    ImageChanged,
    JobCancelled,
    TargetMismatch,
    TargetSpec,
)
from fcapz.broker import wire  # noqa: E402
from fcapz.broker.operations import Engine  # noqa: E402
from fcapz.broker.runtime import EXIT_ALREADY_RUNNING, Runtime, read_info  # noqa: E402

TESTS_DIR = Path(__file__).resolve().parent


def _cfg(**kw) -> CaptureConfig:
    return CaptureConfig(
        pretrigger=2, posttrigger=4, trigger=TriggerConfig("value_match", 0, 0), **kw
    )


def _wait_for(pred, timeout=10.0, what="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = pred()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


# ---- codec and identities ---------------------------------------------------


def test_config_and_result_round_trip_through_json():
    cfg = _cfg(
        probes=[ProbeSpec("a", 4, 0), ProbeSpec("b", 4, 4)],
        sequence=[SequencerStage(cmp_mode_a=2, is_final=True, value_a=7)],
        rle=True, post_clocks=9, startup_arm=True,
    )
    res = CaptureResult(config=cfg, samples=[1, 2, 3], run_lengths=[4, 5, 6], seq=3,
                        after_gap=True, lost=2)
    raw = wire.encode({"r": wire.result_to_dict(res)})
    back = wire.result_from_dict(wire.decode(raw)["r"])
    assert back == res
    assert wire.config_from_dict(wire.config_to_dict(_cfg())) == _cfg()


def test_unknown_config_field_is_refused():
    d = wire.config_to_dict(_cfg())
    d["bogus"] = 1
    with pytest.raises(ValueError, match="bogus"):
        wire.config_from_dict(d)


def test_errors_map_back_by_name_and_unknown_ones_stay_visible():
    assert isinstance(wire.error_from_dict(wire.error_dict(CoreBusy("x"))), CoreBusy)
    err = wire.error_from_dict({"type": "WeirdError", "message": "boom"})
    assert isinstance(err, wire.BrokerRemoteError)
    assert "WeirdError: boom" in str(err)


def test_target_identity_folds_the_same_board_spelled_differently():
    a = TargetSpec(backend="hw_server", host="localhost", port=6666, tap="xc7a100t.tap")
    b = TargetSpec(backend="hw_server", host="127.0.0.1", port=3121, tap="xc7a100t")
    assert a.identity() == b.identity()
    assert TargetSpec(backend="usb_blaster", tap="").identity() == \
        TargetSpec(backend="usb_blaster", tap="auto").identity()
    assert TargetSpec(backend="openocd", port=6666).identity() != \
        TargetSpec(backend="openocd", port=6667).identity()


def test_runtime_refuses_other_settings_and_ambiguous_usb_adapters(tmp_path):
    rt = Runtime(tmp_path, transport_factory=lambda s: FakeElaTransport())
    eng = rt.engine_for(TargetSpec())
    assert rt.engine_for(TargetSpec(host="localhost", port=3121)) is eng
    with pytest.raises(TargetMismatch, match="settings"):
        rt.engine_for(TargetSpec(no_burst=True))
    rt.engine_for(TargetSpec(backend="ftdi", hardware="A"))
    with pytest.raises(TargetMismatch, match="same ftdi adapter"):
        rt.engine_for(TargetSpec(backend="ftdi"))


# ---- engine -----------------------------------------------------------------


@pytest.fixture
def engine():
    t = FakeElaTransport()
    eng = Engine(TargetSpec(), lambda spec: t, authority="local:test")
    eng.fake = t
    yield eng
    eng.close(timeout=2.0)


def _capture(eng, owner, events=None, **params):
    params.setdefault("config", _cfg())
    params.setdefault("timeout", 10.0)
    queue_timeout = params.pop("queue_timeout", 10.0)
    expect_gen = params.pop("expect_gen", None)
    return eng.submit("capture", params, owner=owner, queue_timeout=queue_timeout,
                      expect_gen=expect_gen,
                      on_event=None if events is None else events.append)


def _state(job, state):
    return lambda: job.state == state


def test_same_slot_jobs_run_one_at_a_time_in_order(engine):
    t = engine.fake
    events = []
    a = _capture(engine, "a")
    _wait_for(_state(a, "running"), what="a running")
    b = _capture(engine, "b", events)
    _wait_for(lambda: any(e["event"] == "queued" for e in events), what="b queued")
    queued = next(e for e in events if e["event"] == "queued")
    assert queued["behind"]["job"] == a.id and queued["behind"]["owner"] == "a"
    time.sleep(0.1)
    assert t.arms[0] == 1, "b must not arm while a owns the core"
    t.trigger(0)
    ra = a.wait(5)
    _wait_for(_state(b, "running"), what="b running")
    assert t.arms[0] == 2
    t.trigger(0)
    rb = b.wait(5)
    assert ra["core"].slot == rb["core"].slot == 0
    assert ra["result"].samples and rb["result"].samples


def test_implicit_and_explicit_slot_share_one_queue(engine):
    a = _capture(engine, "a")                  # slot left out: binds slot 0
    _wait_for(_state(a, "running"))
    b = _capture(engine, "b", instance=0)
    _wait_for(_state(b, "queued"))
    engine.fake.trigger(0)
    a.wait(5)
    _wait_for(_state(b, "running"))
    engine.fake.trigger(0)
    b.wait(5)


def test_queue_deadline_gives_core_busy_and_leaves_the_holder(engine):
    a = _capture(engine, "a")
    _wait_for(_state(a, "running"))
    b = _capture(engine, "b", queue_timeout=0.3)
    with pytest.raises(CoreBusy, match=f"behind job {a.id}"):
        b.wait(5)
    assert a.state == "running"
    engine.fake.trigger(0)
    a.wait(5)


def test_other_slots_run_while_one_waits_for_its_trigger(engine):
    a = _capture(engine, "a", instance=0)
    _wait_for(_state(a, "running"))
    b = _capture(engine, "b", instance=1)
    _wait_for(_state(b, "running"))
    engine.fake.trigger(1)
    rb = b.wait(5)
    assert rb["core"].slot == 1 and a.state == "running"
    engine.fake.trigger(0)
    a.wait(5)


def test_cancelling_a_client_stops_only_its_jobs(engine):
    a = _capture(engine, "x")
    _wait_for(_state(a, "running"))
    b = _capture(engine, "y")
    c = _capture(engine, "x")
    _wait_for(lambda: b.state == "queued" and c.state == "queued")
    assert engine.cancel_owner("x") == 2
    with pytest.raises(JobCancelled):
        a.wait(5)
    with pytest.raises(JobCancelled):
        c.wait(5)
    _wait_for(_state(b, "running"), what="b takes the core")
    engine.fake.trigger(0)
    b.wait(5)
    assert engine.image_gen == 1


def test_a_missing_trigger_does_not_reconnect(engine):
    a = _capture(engine, "a", timeout=0.2)
    with pytest.raises(CaptureNotReady):
        a.wait(5)
    assert engine.status()["connected"] and engine.image_gen == 1
    engine.fake.auto = True
    assert _capture(engine, "a").wait(5)["core"].image_gen == 1


def test_a_link_failure_reconnects_with_a_new_generation(engine):
    t = engine.fake
    t.auto = True
    first = _capture(engine, "a").wait(5)["core"]
    assert first.image_gen == 1
    t.fail_io = True            # one glitch: the VERSION check passes
    with pytest.raises(OSError):
        _capture(engine, "a").wait(5)
    assert engine.status()["connected"] and engine.image_gen == 1
    t.fail_io = "always"        # a dead cable: the check fails too
    with pytest.raises(OSError):
        _capture(engine, "a").wait(5)
    assert not engine.status()["connected"]
    t.fail_io = False
    stale = _capture(engine, "a", expect_gen=1)
    with pytest.raises(ImageChanged, match="1 -> 2"):
        stale.wait(5)
    again = _capture(engine, "a").wait(5)["core"]
    assert again.image_gen == 2 and t.connects == 2


def test_the_last_capture_is_published_with_its_core(engine):
    engine.fake.auto = True
    r = _capture(engine, "a").wait(5)
    snap = engine.last_capture({"chain": 1})
    assert snap["result"] is r["result"] and snap["owner"] == "a"
    assert snap["core"].image_gen == 1


def test_eio_operations_run_as_jobs(engine):
    eio = {"chain": 3}
    probe = engine.submit("eio", {**eio, "op": "probe"}, owner="a").wait(5)
    assert (probe["in_w"], probe["out_w"]) == (8, 8)
    assert engine.submit("eio", {**eio, "op": "read"}, owner="a").wait(5)["value"] == 0xA5
    engine.submit("eio", {**eio, "op": "write", "value": 0x0F}, owner="a").wait(5)
    engine.submit("eio", {**eio, "op": "set_bit", "bit": 7, "level": 1}, owner="a").wait(5)
    out = engine.submit("eio", {**eio, "op": "read_outputs"}, owner="a").wait(5)
    assert out["value"] == 0x8F


# ---- runtime and sessions, as processes -------------------------------------


@pytest.fixture
def broker_env(tmp_path, monkeypatch):
    """A private runtime directory with the fake transport; stops the runtime
    the test started."""
    rdir = tmp_path / "rt"
    ctl = tmp_path / "ctl"
    ctl.mkdir()
    monkeypatch.setenv("FCAPZ_BROKER_DIR", str(rdir))
    monkeypatch.setenv("FCAPZ_BROKER_TRANSPORT_FACTORY", "broker_fake:make_transport")
    monkeypatch.setenv("FCAPZ_BROKER_FAKE_DIR", str(ctl))
    monkeypatch.delenv("FCAPZ_BROKER_FAKE_AUTO", raising=False)
    monkeypatch.setenv("FCAPZ_BROKER_IDLE_EXIT", "30")
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join(p for p in (str(TESTS_DIR), os.environ.get("PYTHONPATH", "")) if p),
    )
    yield rdir, ctl
    info = read_info(rdir)
    if info:
        try:
            with BrokerSession.connect(rdir, autostart=False) as s:
                s.stop(force=True)
        except Exception:  # noqa: BLE001 - kill it instead
            with contextlib.suppress(OSError):
                os.kill(int(info["pid"]), signal.SIGTERM)
        _wait_for(lambda: read_info(rdir) is None or not _alive(int(info["pid"])),
                  what="runtime exit")


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_first_client_starts_the_runtime_and_status_stop_do_not(broker_env):
    rdir, _ = broker_env
    with pytest.raises(BrokerNotRunning):
        BrokerSession.connect(rdir, autostart=False)
    with BrokerSession.connect(rdir, name="t1") as s:
        st = s.status()
        assert [c["name"] for c in st["clients"]] == ["t1"]
        assert st["runtime_id"] == read_info(rdir)["runtime_id"]
        pid = s.runtime_pid
        s.stop()
    _wait_for(lambda: not _alive(pid), what="runtime exit")
    assert read_info(rdir) is None
    with pytest.raises(BrokerNotRunning):
        BrokerSession.connect(rdir, autostart=False)


def test_a_second_runtime_loses_the_election(broker_env):
    rdir, _ = broker_env
    with BrokerSession.connect(rdir) as s:
        proc = subprocess.run(
            [sys.executable, "-m", "fcapz.broker", "--dir", str(rdir)],
            capture_output=True, timeout=30,
        )
        assert proc.returncode == EXIT_ALREADY_RUNNING
        assert s.status()["runtime_id"] == read_info(rdir)["runtime_id"]


def test_concurrent_starters_share_one_runtime_and_leave_no_spare(broker_env):
    rdir, _ = broker_env
    sessions: list = []
    errors: list = []

    def start():
        try:
            sessions.append(BrokerSession.connect(rdir))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=start) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(30)
    assert not errors, errors
    assert len({s.runtime_id for s in sessions}) == 1
    pid = sessions[0].runtime_pid
    sessions[0].stop()
    for s in sessions:
        s.close()
    _wait_for(lambda: not _alive(pid), what="runtime exit")
    # A spare spawn that reached the election late would take over now.
    time.sleep(1.5)
    assert read_info(rdir) is None


def test_a_starter_that_finds_another_runtime_stops_its_own_spawn(broker_env, monkeypatch):
    rdir, _ = broker_env
    from fcapz.broker import session as session_mod

    spawned = []
    real_spawn = session_mod.spawn_runtime

    def spy(directory, spawn_id=None):
        proc = real_spawn(directory, spawn_id)
        spawned.append(proc)
        return proc

    with BrokerSession.connect(rdir) as first:
        monkeypatch.setattr(session_mod, "spawn_runtime", spy)
        # As a second starter that raced the first: it spawned too, then
        # found the first one's runtime.
        conn, info = BrokerSession._start(rdir, 20)
        conn.close()
        assert info["runtime_id"] == first.runtime_id
        assert spawned and spawned[0].poll() is not None, "spare spawn still running"


def test_the_runtime_exits_when_idle(broker_env, monkeypatch):
    rdir, _ = broker_env
    monkeypatch.setenv("FCAPZ_BROKER_IDLE_EXIT", "0.5")
    with BrokerSession.connect(rdir) as s:
        pid = s.runtime_pid
        time.sleep(1.0)
        assert _alive(pid), "a connected client keeps it alive"
    _wait_for(lambda: not _alive(pid), timeout=15, what="idle exit")
    assert read_info(rdir) is None


def test_a_runtime_that_cannot_start_says_why(broker_env, monkeypatch):
    rdir, _ = broker_env
    monkeypatch.setenv("FCAPZ_BROKER_TRANSPORT_FACTORY", "no_such_module_fcapz:make")
    with pytest.raises(BrokerStartError, match="no_such_module_fcapz"):
        BrokerSession.connect(rdir, start_timeout=20)


def test_capture_and_probe_through_the_runtime(broker_env, monkeypatch):
    rdir, _ = broker_env
    monkeypatch.setenv("FCAPZ_BROKER_FAKE_AUTO", "1")
    with BrokerSession.connect(rdir) as s:
        assert s.probe(TargetSpec())["sample_width"] == 8
        cap = s.capture(TargetSpec(), _cfg(probes=[ProbeSpec("x", 8, 0)]))
        assert cap.core.authority == f"local:{s.runtime_id}"
        assert cap.result.config.probes == [ProbeSpec("x", 8, 0)]
        assert len(cap.result.samples) == 7
        last = s.last_capture(TargetSpec())
        assert last.result == cap.result and last.job == cap.job
        assert s.eio(TargetSpec(), "read", chain=3)["value"] == 0xA5


def test_a_killed_client_cancels_only_its_own_job(broker_env):
    rdir, ctl = broker_env
    holder = subprocess.Popen(
        [sys.executable, "-c", (
            "from fcapz.broker import BrokerSession, TargetSpec\n"
            "from fcapz.analyzer import CaptureConfig, TriggerConfig\n"
            "s = BrokerSession.connect(name='holder')\n"
            "s.capture(TargetSpec(), CaptureConfig(pretrigger=2, posttrigger=4,"
            " trigger=TriggerConfig('value_match', 0, 0)), timeout=60)\n"
        )],
        env=os.environ.copy(),
    )
    try:
        with BrokerSession.connect(rdir, name="waiter") as s:
            def holder_running():
                for t in s.status()["targets"]:
                    for core in t["cores"]:
                        if core["holder"] and core["holder"]["state"] == "running":
                            return core["holder"]
                return None

            first = _wait_for(holder_running, timeout=20, what="holder's capture")
            out: dict = {}

            def wait_turn():
                try:
                    out["cap"] = s.capture(TargetSpec(), _cfg(), queue_timeout=30, timeout=30)
                except BaseException as exc:  # noqa: BLE001
                    out["err"] = exc

            th = threading.Thread(target=wait_turn)
            th.start()
            _wait_for(lambda: any(
                core["queued"] for t in s.status()["targets"] for core in t["cores"]
            ), what="waiter queued")
            holder.kill()
            holder.wait(10)
            second = _wait_for(
                lambda: (h := holder_running()) and h["job"] != first["job"] and h,
                timeout=20, what="waiter takes the core",
            )
            assert second["owner"] != first["owner"]
            (ctl / "trigger-0").write_text("")
            th.join(20)
            assert "err" not in out, out.get("err")
            assert out["cap"].result.samples
    finally:
        if holder.poll() is None:
            holder.kill()


def test_a_runtime_crash_is_reported_and_the_next_one_is_new(broker_env):
    rdir, _ = broker_env
    s = BrokerSession.connect(rdir)
    first_id, pid = s.runtime_id, s.runtime_pid
    out: dict = {}

    def capture():
        try:
            s.capture(TargetSpec(), _cfg(), timeout=60)
        except BaseException as exc:  # noqa: BLE001
            out["err"] = exc

    th = threading.Thread(target=capture)
    th.start()
    _wait_for(lambda: any(t["jobs"] for t in s.status()["targets"]) if not out else True,
              what="capture running")
    os.kill(pid, signal.SIGTERM)
    th.join(20)
    assert isinstance(out.get("err"), BrokerConnectionLost)
    s.close()
    _wait_for(lambda: not _alive(pid), what="crashed runtime gone")
    with BrokerSession.connect(rdir) as s2:
        assert s2.runtime_id != first_id
        assert s2.probe(TargetSpec())["core"].authority == f"local:{s2.runtime_id}"
