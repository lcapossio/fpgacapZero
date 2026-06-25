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


def test_ir_table_mapping():
    assert RpcServer._ir_table("xilinx7") is None
    assert RpcServer._ir_table("gowin") is not None
    assert RpcServer._ir_table("ultrascale") is not None
    with pytest.raises(ValueError):
        RpcServer._ir_table("bogus")


def test_token_auth(monkeypatch):
    c = _client(monkeypatch, token="secret")
    assert c.post("/api/rpc", json={"cmd": "probe"}).status_code == 401
    ok = c.post(
        "/api/rpc", json={"cmd": "probe"}, headers={"Authorization": "Bearer secret"}
    )
    assert ok.status_code == 200
