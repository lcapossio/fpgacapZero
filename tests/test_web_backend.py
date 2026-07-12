# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Web backend tests: the JSON-RPC-over-HTTP gateway against a fake transport.

The web server speaks the same ``cmd`` protocol as ``python -m fcapz.rpc``, so
these drive ``POST /api/rpc`` with command dicts.  Skips cleanly when the
optional ``[web]`` deps (fastapi) or httpx aren't installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from fcapz.analyzer import expected_ela_version_reg  # noqa: E402
from fcapz.rpc import RpcServer  # noqa: E402
from fcapz.transport import Transport  # noqa: E402
from fcapz.web import create_app  # noqa: E402


class FakeTransport(Transport):
    """ELA identity at 0x0000 and a shared-chain EIO at base 0x8000."""

    def __init__(self) -> None:
        self.regs = {
            0x0000: expected_ela_version_reg(),  # ELA VERSION ('LA')
            0x0008: 0x4,  # STATUS: DONE set so capture completes immediately
            0x000C: 8,  # SAMPLE_W
            0x0010: 64,  # DEPTH
            0x001C: 0,
            0x00A4: 6,  # NUM_CHANNELS
            0x8000: (4 << 16) | 0x494F,  # EIO VERSION ('IO')
            0x8004: 2,  # EIO IN_W
            0x8008: 6,  # EIO OUT_W
            0x8010: 0b01,  # EIO IN[0]
            0x8100: 0,  # EIO OUT[0]
        }
        self.data = list(range(10, 90))
        self.active_chain = 1

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def select_chain(self, chain: int) -> None:
        self.active_chain = chain

    def read_reg(self, addr: int) -> int:
        return self.regs.get(addr, 0)

    def write_reg(self, addr: int, value: int) -> None:
        self.regs[addr] = value

    def read_block(self, addr: int, words: int):
        if addr == 0x0100:
            return self.data[:words]
        return [0] * words


class FakeSegmentTransport(FakeTransport):
    def __init__(self) -> None:
        super().__init__()
        self.regs[0x00B8] = 2
        self.regs[0x0010] = 8
        self.segment = 0

    def write_reg(self, addr: int, value: int) -> None:
        super().write_reg(addr, value)
        if addr == 0x00C0:  # _ADDR_SEG_SEL
            self.segment = int(value)

    def read_block(self, addr: int, words: int):
        if addr == 0x0100:
            base = 0x10 if self.segment == 0 else 0x20
            return [base + i for i in range(words)]
        return [0] * words


class FakeAxiMonTransport(FakeTransport):
    """FakeTransport plus the AXI monitor identity/geometry registers."""

    def __init__(self, decode: bool = True) -> None:
        super().__init__()
        # AXI_MON_ID: "AM" magic | proto=1 (AXI4-Lite) | CAP_FLAGS bit0=DECODE_EN
        self.regs[0x00E8] = (0x414D << 16) | (1 << 8) | (1 if decode else 0)
        self.regs[0x00EC] = 32 | (32 << 8)  # AXI_GEOM: addr_w=32, data_w=32


def _client(monkeypatch, **app_kwargs) -> TestClient:
    monkeypatch.setattr(RpcServer, "_build_transport", lambda self, req: FakeTransport())
    return TestClient(create_app(**app_kwargs))


def _rpc(client: TestClient, cmd: str, **kw):
    return client.post("/api/rpc", json={"cmd": cmd, **kw})


_GOWIN = {"backend": "openocd", "tap": "GW1NR-9C.tap", "ir_table": "gowin", "chain": 1}


def test_connect_then_probe(monkeypatch):
    c = _client(monkeypatch)
    r = _rpc(c, "connect", **_GOWIN)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    p = _rpc(c, "probe").json()
    assert p["ok"] is True
    assert p["probe"]["sample_width"] == 8
    assert p["probe"]["depth"] == 64


def test_connect_echoes_resolved_ir_table(monkeypatch):
    c = _client(monkeypatch)
    # Explicit preset is echoed verbatim.
    r = _rpc(c, "connect", **_GOWIN).json()
    assert r["ok"] is True and r["ir_table"] == "gowin"
    # Omitted preset: the server infers it from the tap name — the one
    # authoritative copy of that mapping (clients no longer duplicate it).
    r = _rpc(c, "connect", backend="openocd", tap="GW1NR-9C.tap", chain=1).json()
    assert r["ok"] is True and r["ir_table"] == "gowin"
    r = _rpc(c, "connect", backend="openocd", tap="xcku040.tap", chain=1).json()
    assert r["ok"] is True and r["ir_table"] == "ultrascale"
    r = _rpc(c, "connect", backend="openocd", tap="xc7a100t.tap", chain=1).json()
    assert r["ok"] is True and r["ir_table"] == "xilinx7"


def test_capture_returns_samples(monkeypatch):
    c = _client(monkeypatch)
    _rpc(c, "connect", **_GOWIN)
    # The RPC protocol takes sample_width/depth explicitly (client reads them
    # from `probe` first), matching the hardware shape.
    r = _rpc(
        c, "capture", pretrigger=2, posttrigger=4, channel=0,
        sample_width=8, depth=64, timeout=0.2,
    ).json()
    assert r["ok"] is True, r
    assert r["sample_count"] == len(r["result"]["samples"])
    assert r["sample_count"] > 0


def test_capture_include_vcd(monkeypatch):
    c = _client(monkeypatch)
    _rpc(c, "connect", **_GOWIN)
    r = _rpc(
        c, "capture", pretrigger=2, posttrigger=4, channel=0,
        sample_width=8, depth=64, timeout=0.2, include_vcd=True,
    ).json()
    assert r["ok"] is True, r
    vcd = r["vcd"]
    # Valid-enough VCD for an embedded viewer (Surfer) to parse.
    assert "$timescale" in vcd
    assert "$enddefinitions $end" in vcd
    assert "$dumpvars" in vcd
    # Omitted by default so normal captures stay lean.
    bare = _rpc(
        c, "capture", pretrigger=2, posttrigger=4, channel=0,
        sample_width=8, depth=64, timeout=0.2,
    ).json()
    assert "vcd" not in bare


def test_capture_accepts_web_probe_defs_and_include_csv(monkeypatch):
    c = _client(monkeypatch)
    _rpc(c, "connect", **_GOWIN)
    r = _rpc(
        c, "capture", pretrigger=2, posttrigger=4, channel=0,
        sample_width=8, depth=64, timeout=0.2, include_vcd=True, include_csv=True,
        probes=[{"name": "lo", "width": 4, "lsb": 0}, {"name": "hi", "width": 4, "lsb": 4}],
    ).json()
    assert r["ok"] is True, r
    assert " lo " in r["vcd"]
    assert " hi " in r["vcd"]
    assert "index,value" in r["csv"]


def test_capture_accepts_trigger_sequence(monkeypatch):
    c = _client(monkeypatch)
    _rpc(c, "connect", **_GOWIN)
    r = _rpc(
        c, "capture", pretrigger=2, posttrigger=4, channel=0,
        sample_width=8, depth=64, timeout=0.2,
        sequence=[
            {
                "cmp_mode_a": 0,
                "value_a": "0x00",
                "mask_a": "0xFF",
                "is_final": True,
            }
        ],
    ).json()
    assert r["ok"] is False
    assert "trigger sequencer not present" in r["error"]


def test_segmented_capture_bundle(monkeypatch):
    monkeypatch.setattr(
        RpcServer, "_build_transport", lambda self, req: FakeSegmentTransport()
    )
    c = TestClient(create_app())
    _rpc(c, "connect", **_GOWIN)
    r = _rpc(
        c, "capture", pretrigger=0, posttrigger=0, channel=0,
        sample_width=8, depth=8, timeout=0.2, segments=True,
        include_vcd=True, include_csv=True,
    ).json()
    assert r["ok"] is True, r
    assert r["sample_count"] == 2
    assert len(r["result"]["segments"]) == 2
    assert len(r["segments"]) == 2
    assert "segment,index,value" in r["csv"]
    assert "$timescale" in r["vcd"]


def test_segmented_capture_vcd_contains_all_segments(monkeypatch):
    """include_vcd must return every segment's samples (concatenated, with a
    segment marker wire), not just segment 0's waveform."""
    monkeypatch.setattr(
        RpcServer, "_build_transport", lambda self, req: FakeSegmentTransport()
    )
    c = TestClient(create_app())
    _rpc(c, "connect", **_GOWIN)
    r = _rpc(
        c, "capture", pretrigger=0, posttrigger=0, channel=0,
        sample_width=8, depth=8, timeout=0.2, segments=True, include_vcd=True,
    ).json()
    assert r["ok"] is True, r
    vcd = r["vcd"]
    # FakeSegmentTransport: segment 0 samples start at 0x10, segment 1 at 0x20.
    assert f"b{0x10:08b} s" in vcd
    assert f"b{0x20:08b} s" in vcd
    assert " segment " in vcd  # boundary marker wire


def test_segmented_capture_honors_wide_format(monkeypatch):
    """format='vcd' (the client's >53-bit guard) must not attach JSON-number
    samples — a wide segmented capture downloaded as JSON would round."""
    monkeypatch.setattr(
        RpcServer, "_build_transport", lambda self, req: FakeSegmentTransport()
    )
    c = TestClient(create_app())
    _rpc(c, "connect", **_GOWIN)
    r = _rpc(
        c, "capture", pretrigger=0, posttrigger=0, channel=0,
        sample_width=8, depth=8, timeout=0.2, segments=True,
        format="vcd", include_vcd=True,
    ).json()
    assert r["ok"] is True, r
    assert r["format"] == "vcd"
    assert "result" not in r  # no JSON-number samples to mis-download
    assert all(s["format"] == "vcd" and "content" in s for s in r["segments"])
    assert "$timescale" in r["vcd"]


def test_capture_immediate(monkeypatch):
    c = _client(monkeypatch)
    _rpc(c, "connect", **_GOWIN)
    # "Trigger Immediate" rewrites the trigger to always-true; still returns samples.
    r = _rpc(
        c, "capture", pretrigger=2, posttrigger=4, channel=0,
        sample_width=8, depth=64, timeout=0.2, immediate=True,
    ).json()
    assert r["ok"] is True, r
    assert r["sample_count"] > 0


def test_errors_are_in_band_http_200(monkeypatch):
    c = _client(monkeypatch)
    r = _rpc(c, "capture", pretrigger=2, posttrigger=4)  # not connected
    assert r.status_code == 200  # JSON-RPC carries errors in-band
    body = r.json()
    assert body["ok"] is False
    assert "not connected" in body["error"]


def test_unknown_cmd_in_band(monkeypatch):
    c = _client(monkeypatch)
    _rpc(c, "connect", **_GOWIN)
    body = _rpc(c, "bogus").json()
    assert body["ok"] is False
    assert body["type"] == "ValueError"


def test_eio_shared_chain_over_rpc(monkeypatch):
    c = _client(monkeypatch)
    _rpc(c, "connect", **_GOWIN)
    r = _rpc(c, "eio_connect", **_GOWIN, base_addr=0x8000).json()
    assert r["ok"] is True
    assert (r["in_w"], r["out_w"]) == (2, 6)
    assert r["base_addr"] == 0x8000
    assert _rpc(c, "eio_write", value=0x15).json()["ok"] is True
    rd = _rpc(c, "eio_read").json()
    assert rd["ok"] is True
    assert rd["value"] == 0b01  # the EIO input register


def test_scan_targets_openocd(monkeypatch):
    monkeypatch.setattr("fcapz.rpc.list_openocd_taps", lambda **kw: ["GW1NR-9C.tap"])
    c = _client(monkeypatch)
    r = _rpc(c, "scan_targets", backend="openocd").json()
    assert r["ok"] is True
    assert r["targets"] == ["GW1NR-9C.tap"]
    assert r["backend"] == "openocd"


def test_list_cores_reports_ela_and_eio(monkeypatch):
    c = _client(monkeypatch)
    _rpc(c, "connect", **_GOWIN)
    r = _rpc(c, "list_cores").json()
    assert r["ok"] is True
    cores = r["cores"]
    assert [x["type"] for x in cores] == ["ela", "eio"]
    ela = cores[0]
    assert ela["name"] == "Embedded Logic Analyzer" and ela["chain"] == 1
    assert ela["info"]["sample_width"] == 8 and ela["info"]["depth"] == 64
    eio = cores[1]
    assert eio["name"] == "Embedded I/O"
    assert eio["chain"] == 1 and eio["base_addr"] == 0x8000
    assert (eio["info"]["in_w"], eio["info"]["out_w"]) == (2, 6)


def test_discover_boards_only_returns_compatible(monkeypatch):
    """Aggregate compatible taps across ports; skip unreachable ports/incompatible taps."""
    import fcapz.analyzer as az

    taps_by_port = {6666: ["GW1NR-9C.tap", "dummy.tap"], 6668: ["xc7a100t.tap"]}

    def fake_list_taps(*, host, port, timeout_sec):
        if port not in taps_by_port:
            raise OSError("nothing listening")  # e.g. port 6667 has no OpenOCD
        return taps_by_port[port]

    def fake_probe(*, host, port, tap, chain, timeout_sec):
        if tap == "dummy.tap":
            return None  # present tap, but not an fcapz ELA
        return {
            "backend": "openocd", "host": host, "port": port, "tap": tap,
            "ir_table": "gowin" if tap.startswith("GW") else "xilinx7",
            "identity": {"sample_width": 8, "depth": 64, "num_channels": 6,
                         "version_major": 0, "version_minor": 4},
            "label": f"{tap} @ :{port}",
        }

    monkeypatch.setattr(az, "list_openocd_taps", fake_list_taps)
    monkeypatch.setattr(az, "_probe_openocd_board", fake_probe)

    boards = az.discover_boards(ports=[6666, 6667, 6668])
    assert [b["tap"] for b in boards] == ["GW1NR-9C.tap", "xc7a100t.tap"]
    assert {b["port"] for b in boards} == {6666, 6668}


def test_caller_waits_are_clamped(monkeypatch):
    """Huge caller-supplied timeouts must be clamped: in the web gateway each
    request holds a threadpool worker for its full wait."""
    from fcapz.rpc import _MAX_WAIT_SEC, _wait_sec

    assert _wait_sec({"timeout": 999999}, "timeout", 5.0) == _MAX_WAIT_SEC
    assert _wait_sec({"timeout": -3}, "timeout", 5.0) == 0.0
    assert _wait_sec({}, "timeout", 5.0) == 5.0

    captured = {}

    def fake_list_taps(*, host, port, timeout_sec):
        captured["timeout"] = timeout_sec
        return []

    monkeypatch.setattr("fcapz.rpc.list_openocd_taps", fake_list_taps)
    c = _client(monkeypatch)
    r = _rpc(c, "scan_targets", backend="openocd", timeout=999999).json()
    assert r["ok"] is True
    assert captured["timeout"] == _MAX_WAIT_SEC


def test_discover_boards_budget_caps_sweep(monkeypatch):
    """budget_sec bounds the whole sweep so the server can't outlive the web
    client's abort while holding the gateway lock."""
    import fcapz.analyzer as az

    clock = {"t": 0.0}

    class _FakeTime:
        @staticmethod
        def monotonic() -> float:
            return clock["t"]

    def fake_list_taps(*, host, port, timeout_sec):
        assert timeout_sec <= 5.0  # per-step timeout clamped to what's left
        clock["t"] += 5.0  # this port costs the full per-step timeout
        return []

    monkeypatch.setattr(az, "time", _FakeTime())
    monkeypatch.setattr(az, "list_openocd_taps", fake_list_taps)
    boards = az.discover_boards(
        ports=[6666, 6667, 6668, 6669], timeout_sec=5.0, budget_sec=6.0
    )
    assert boards == []
    assert clock["t"] == 10.0  # ports 3 and 4 were never probed


def test_discover_boards_rpc_forwards_budget(monkeypatch):
    captured = {}

    def fake_discover(*, host, ports, timeout_sec, budget_sec=None):
        captured["budget"] = budget_sec
        return []

    monkeypatch.setattr("fcapz.rpc.discover_boards", fake_discover)
    c = _client(monkeypatch)
    r = _rpc(c, "discover_boards", backend="openocd", port=6666, budget=12).json()
    assert r["ok"] is True
    assert captured["budget"] == 12.0


def test_discover_boards_rpc_expands_port_span(monkeypatch):
    calls = {}

    def fake_discover(*, host, ports, timeout_sec, budget_sec=None):
        calls["ports"] = ports
        return [{
            "backend": "openocd", "host": host, "port": ports[0],
            "tap": "GW1NR-9C.tap", "ir_table": "gowin",
            "identity": {"sample_width": 8, "depth": 64, "num_channels": 6,
                         "version_major": 0, "version_minor": 4},
            "label": "GW1NR-9C.tap @ :6666",
        }]

    monkeypatch.setattr("fcapz.rpc.discover_boards", fake_discover)
    c = _client(monkeypatch)
    r = _rpc(c, "discover_boards", backend="openocd", port=6666, port_span=3).json()
    assert r["ok"] is True
    assert r["backend"] == "openocd"
    assert [b["tap"] for b in r["boards"]] == ["GW1NR-9C.tap"]
    assert calls["ports"] == [6666, 6667, 6668]  # port_span -> sweep


def test_discover_boards_rpc_empty_when_none(monkeypatch):
    """No compatible boards -> ok with an empty list (caller fails only then)."""
    monkeypatch.setattr("fcapz.rpc.discover_boards", lambda **kw: [])
    c = _client(monkeypatch)
    r = _rpc(c, "discover_boards", backend="openocd").json()
    assert r["ok"] is True
    assert r["boards"] == []


def _local_client(monkeypatch, **app_kwargs) -> TestClient:
    """A TestClient whose peer looks like loopback, so openocd_* isn't guarded."""
    monkeypatch.setattr(RpcServer, "_build_transport", lambda self, req: FakeTransport())
    return TestClient(create_app(**app_kwargs), client=("127.0.0.1", 50000))


class _FakeLauncher:
    def status(self):
        return {"enabled": True, "configs": ["brd"], "running": []}

    def start(self, *, name=None, port=6666, wait_sec=10.0):
        return {"started": True, "already_running": False, "port": port,
                "pid": 999, "config": name or "brd"}

    def stop(self, *, port=6666):
        return {"stopped": True, "port": port}

    def shutdown(self):
        pass


def test_openocd_stop_runs_under_session_lock():
    """openocd_stop kills the process the session may be using, so it must not
    run lock-free; start/status don't touch the live transport, so they may."""
    from fcapz.web.gateway import RpcGateway

    assert "openocd_stop" not in RpcGateway._LOCK_FREE_CMDS
    assert "openocd_start" in RpcGateway._LOCK_FREE_CMDS
    assert "openocd_status" in RpcGateway._LOCK_FREE_CMDS


def test_discover_boards_caps_port_span(monkeypatch):
    captured = {}

    def fake_discover(*, host, ports, timeout_sec, budget_sec=None):
        captured["ports"] = ports
        return []

    monkeypatch.setattr("fcapz.rpc.discover_boards", fake_discover)
    c = _client(monkeypatch)
    r = _rpc(c, "discover_boards", backend="openocd", port=6666, port_span=1000).json()
    assert r["ok"] is True
    assert len(captured["ports"]) == 64  # _MAX_DISCOVERY_PORTS


def test_discover_boards_rejects_invalid_port(monkeypatch):
    c = _client(monkeypatch)
    r = _rpc(c, "discover_boards", backend="openocd", port=99999).json()
    assert r["ok"] is False and "port out of range" in r["error"]


def test_host_header_rebinding_guard(monkeypatch):
    monkeypatch.setattr(RpcServer, "_build_transport", lambda self, req: FakeTransport())
    c = TestClient(create_app(bind_host="127.0.0.1"))
    # A loopback Host is accepted.
    ok = c.post("/api/rpc", json={"cmd": "connect", **_GOWIN}, headers={"Host": "127.0.0.1:8000"})
    assert ok.json()["ok"] is True
    # A foreign Host (DNS-rebinding shape) is rejected.
    bad = c.post("/api/rpc", json={"cmd": "probe"}, headers={"Host": "evil.example"})
    assert bad.json()["ok"] is False and bad.json()["type"] == "PermissionError"


def test_host_header_guard_disabled_for_non_loopback_bind(monkeypatch):
    # Bound to 0.0.0.0 we can't allow-list external names, so any Host passes
    # (those deployments rely on --token instead).
    monkeypatch.setattr(RpcServer, "_build_transport", lambda self, req: FakeTransport())
    c = TestClient(create_app(bind_host="0.0.0.0"))
    r = c.post("/api/rpc", json={"cmd": "connect", **_GOWIN}, headers={"Host": "anything.example"})
    assert r.json()["ok"] is True


def test_openocd_guard_localhost_only():
    from fcapz.web.app import _openocd_guard

    assert _openocd_guard({"cmd": "openocd_start"}, "10.0.0.5")["type"] == "PermissionError"
    assert _openocd_guard({"cmd": "openocd_start"}, "127.0.0.1") is None
    assert _openocd_guard({"cmd": "connect"}, "10.0.0.5") is None  # non-openocd unaffected


def test_is_loopback_forms():
    from fcapz.web.app import _is_loopback

    assert _is_loopback("127.0.0.1")
    assert _is_loopback("127.0.0.2")  # whole 127/8 block
    assert _is_loopback("::1")
    assert _is_loopback("localhost")
    # Dual-stack binds report local IPv4 clients as IPv4-mapped IPv6.
    assert _is_loopback("::ffff:127.0.0.1")
    assert not _is_loopback("192.168.1.10")
    assert not _is_loopback("::ffff:192.168.1.10")
    assert not _is_loopback("evil.example")
    assert not _is_loopback(None)


def test_ws_non_object_json_answers_in_band(monkeypatch):
    """Valid-JSON non-object payloads must get an in-band error, not kill the
    socket (the protocol promises errors arrive as {ok:false} envelopes)."""
    import json as _json

    c = _client(monkeypatch)
    with c.websocket_connect("/api/ws") as ws:
        for bad in ("42", '"probe"', "[1]"):
            ws.send_text(bad)
            r = ws.receive_json()
            assert r["ok"] is False and r["type"] == "TypeError"
        # The connection survives and still serves real requests.
        ws.send_text(_json.dumps({"cmd": "connect", **_GOWIN}))
        assert ws.receive_json()["ok"] is True


def test_openocd_status_disabled_without_launcher(monkeypatch):
    c = _local_client(monkeypatch)
    r = _rpc(c, "openocd_status").json()
    assert r["ok"] is True and r["enabled"] is False and r["configs"] == []


def test_openocd_start_disabled_errors(monkeypatch):
    c = _local_client(monkeypatch)
    r = _rpc(c, "openocd_start").json()
    assert r["ok"] is False and "not enabled" in r["error"]


def test_openocd_start_blocked_for_remote_client(monkeypatch):
    # Default TestClient host is "testclient" (non-loopback) -> guarded off.
    c = _client(monkeypatch)
    r = _rpc(c, "openocd_start").json()
    assert r["ok"] is False and r["type"] == "PermissionError"


def test_openocd_start_stop_via_launcher(monkeypatch):
    c = _local_client(monkeypatch, openocd_launcher=_FakeLauncher())
    s = _rpc(c, "openocd_status").json()
    assert s["enabled"] is True and s["configs"] == ["brd"]
    st = _rpc(c, "openocd_start", name="brd", port=6666).json()
    assert st["ok"] is True and st["started"] is True and st["port"] == 6666
    sp = _rpc(c, "openocd_stop", port=6666).json()
    assert sp["ok"] is True and sp["stopped"] is True


def test_eio_discover_finds_shared_chain(monkeypatch):
    c = _client(monkeypatch)
    _rpc(c, "connect", **_GOWIN)
    r = _rpc(c, "eio_discover", **_GOWIN).json()
    assert r["ok"] is True, r
    assert r["discovered"] is True
    assert r["chain"] == 1
    assert r["base_addr"] == 0x8000
    assert (r["in_w"], r["out_w"]) == (2, 6)


def test_axi_mon_probe_reports_geometry_and_probes(monkeypatch):
    monkeypatch.setattr(
        RpcServer, "_build_transport", lambda self, req: FakeAxiMonTransport(decode=True)
    )
    c = TestClient(create_app())
    _rpc(c, "connect", **_GOWIN)
    r = _rpc(c, "axi_mon_probe").json()
    assert r["ok"] is True and r["present"] is True
    assert r["proto"] == "AXI4LITE"
    assert r["decode"] is True
    assert (r["addr_w"], r["data_w"]) == (32, 32)
    assert r["sample_width"] == 160  # 152 + 8-bit events word
    names = [p["name"] for p in r["probes"]]
    assert "awaddr" in names and "any_err" in names  # fields + decode events


def test_axi_mon_probe_absent_on_plain_ela(monkeypatch):
    """A plain ELA (no AXI_MON_ID magic) reports present=False, not an error."""
    c = _client(monkeypatch)
    _rpc(c, "connect", **_GOWIN)
    r = _rpc(c, "axi_mon_probe").json()
    assert r["ok"] is True and r["present"] is False


def test_list_cores_reports_axi_mon(monkeypatch):
    monkeypatch.setattr(
        RpcServer, "_build_transport", lambda self, req: FakeAxiMonTransport(decode=False)
    )
    c = TestClient(create_app())
    _rpc(c, "connect", **_GOWIN)
    cores = _rpc(c, "list_cores").json()["cores"]
    mon = [x for x in cores if x["type"] == "axi_mon"]
    assert len(mon) == 1
    assert mon[0]["name"] == "AXI Monitor"
    assert mon[0]["info"]["proto"] == "AXI4LITE"
    assert mon[0]["info"]["decode"] is False
    assert mon[0]["info"]["sample_width"] == 152


def test_ir_table_mapping():
    assert RpcServer._ir_table("xilinx7") is None
    assert RpcServer._ir_table("gowin") is not None
    assert RpcServer._ir_table("ultrascale") is not None
    with pytest.raises(ValueError):
        RpcServer._ir_table("bogus")


def test_version_endpoint(monkeypatch):
    from fcapz import __version__

    c = _client(monkeypatch)
    r = c.get("/api/version")  # public metadata, no token required
    assert r.status_code == 200
    assert r.json()["version"] == __version__


def test_surfer_viewer_is_mounted(monkeypatch):
    import os

    from fcapz.web.app import _default_surfer_dir

    if not os.path.isdir(_default_surfer_dir()):
        pytest.skip("vendored Surfer build not present")
    c = _client(monkeypatch)
    r = c.get("/surfer/index.html")
    assert r.status_code == 200
    assert "integration.js" in r.text  # the postMessage LoadUrl bridge
    assert "serviceWorker" not in r.text  # SW registration stripped for offline embed
    w = c.get("/surfer/surfer_bg.wasm")
    assert w.status_code == 200
    assert w.headers["content-type"] == "application/wasm"


def test_token_auth(monkeypatch):
    c = _client(monkeypatch, token="secret")
    assert c.post("/api/rpc", json={"cmd": "probe"}).status_code == 401
    ok = c.post(
        "/api/rpc", json={"cmd": "probe"}, headers={"Authorization": "Bearer secret"}
    )
    assert ok.status_code == 200


def test_build_config_parses_wide_bit_vectors_without_rounding():
    """Wide trigger/stor-qual values must survive as base-prefixed strings.

    A JS ``Number`` is exact only to 53 bits, so the web path sends bit vectors
    as strings; the backend must parse them without rounding (regression for
    160-bit AXI-sample triggers).
    """
    big = (0xDEAD_BEEF_CAFE_F00D << 96) | 0x1234_5678_9ABC_DEF0_1122_3344
    mask = (1 << 160) - 1
    assert big > 2**53  # beyond JS-safe integer range
    cfg = RpcServer._build_config(
        {
            "trigger_mode": "value_match",
            "trigger_value": hex(big),
            "trigger_mask": hex(mask),
            "sample_width": 160,
            "stor_qual_value": hex(big),
            "stor_qual_mask": hex(mask),
        }
    )
    assert cfg.trigger.value == big
    assert cfg.trigger.mask == mask
    assert cfg.stor_qual_value == big
    assert cfg.stor_qual_mask == mask


def test_build_config_trigger_value_backward_compatible():
    """Plain ints and decimal strings still parse (older clients unaffected)."""
    assert RpcServer._build_config({"trigger_value": 255}).trigger.value == 255
    assert RpcServer._build_config({"trigger_value": "255"}).trigger.value == 255
    assert RpcServer._build_config({"trigger_value": "0x1F"}).trigger.value == 0x1F


def test_connect_tears_down_stale_side_sessions(monkeypatch):
    """Reconnect without `close` must release stale EIO/AXI/UART, not just the ELA."""

    class _Sess:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(RpcServer, "_build_transport", lambda self, req: FakeTransport())
    srv = RpcServer()
    old_analyzer = _Sess()
    srv._analyzer = old_analyzer
    srv._eio = _Sess()
    srv._axi = _Sess()
    srv._uart = _Sess()
    stale = [srv._eio, srv._axi, srv._uart]

    srv.handle({**_GOWIN, "cmd": "connect"})

    assert old_analyzer.closed and all(s.closed for s in stale)
    assert srv._eio is None and srv._axi is None and srv._uart is None
    assert srv._analyzer is not None  # a fresh session replaced them


def test_close_tears_down_all_hardware_sessions():
    """`close` (web/GUI Disconnect) must release EIO/AXI/UART, not just the ELA."""

    class _Sess:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    srv = RpcServer()
    srv._analyzer = _Sess()
    srv._eio = _Sess()
    srv._axi = _Sess()
    srv._axi_transport = _Sess()
    srv._uart = _Sess()
    srv._uart_transport = _Sess()
    analyzer, eio, axi, uart = srv._analyzer, srv._eio, srv._axi, srv._uart

    assert srv.handle({"cmd": "close"})["ok"] is True

    assert analyzer.closed and eio.closed and axi.closed and uart.closed
    assert srv._analyzer is None and srv._eio is None
    assert srv._axi is None and srv._axi_transport is None
    assert srv._uart is None and srv._uart_transport is None


def test_close_releases_bare_transport_from_partial_connect():
    """A transport opened without its controller (partial connect) is closed too."""

    class _Sess:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    srv = RpcServer()
    srv._axi_transport = _Sess()
    srv._uart_transport = _Sess()
    axi_t, uart_t = srv._axi_transport, srv._uart_transport

    srv.handle({"cmd": "close"})

    assert axi_t.closed and uart_t.closed
    assert srv._axi_transport is None and srv._uart_transport is None


class _FakeEio:
    def __init__(self, value: int = 0) -> None:
        self.value = value
        self.written: int | None = None

    def read_inputs(self) -> int:
        return self.value

    def write_outputs(self, v: int) -> None:
        self.written = v


def test_eio_wide_value_round_trips_via_value_hex_and_hex_string_write():
    """Multiword EIO (>53 bits) survives JSON via value_hex / hex-string write."""
    wide = (1 << 80) | (1 << 40) | 1  # bits set above 53 and above 31
    assert wide > 2**53

    srv = RpcServer()
    srv._analyzer = object()  # eio_* runs after the connected-analyzer guard
    srv._eio = _FakeEio(wide)

    rd = srv.handle({"cmd": "eio_read"})
    assert int(rd["value_hex"], 16) == wide  # full width preserved
    assert rd["value"] == wide  # numeric field kept for back-compat

    srv.handle({"cmd": "eio_write", "value": hex(wide)})
    assert srv._eio.written == wide  # hex string parsed exactly


def test_eio_write_accepts_plain_int_backward_compatible():
    srv = RpcServer()
    srv._analyzer = object()
    srv._eio = _FakeEio()
    srv.handle({"cmd": "eio_write", "value": 0x15})
    assert srv._eio.written == 0x15
