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
        if addr == 0x00BC:
            self.segment = int(value)

    def read_block(self, addr: int, words: int):
        if addr == 0x0100:
            base = 0x10 if self.segment == 0 else 0x20
            return [base + i for i in range(words)]
        return [0] * words


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


def test_discover_boards_rpc_expands_port_span(monkeypatch):
    calls = {}

    def fake_discover(*, host, ports, timeout_sec):
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


def test_eio_discover_finds_shared_chain(monkeypatch):
    c = _client(monkeypatch)
    _rpc(c, "connect", **_GOWIN)
    r = _rpc(c, "eio_discover", **_GOWIN).json()
    assert r["ok"] is True, r
    assert r["discovered"] is True
    assert r["chain"] == 1
    assert r["base_addr"] == 0x8000
    assert (r["in_w"], r["out_w"]) == (2, 6)


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
