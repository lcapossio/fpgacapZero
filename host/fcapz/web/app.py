# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""FastAPI app exposing the fcapz JSON-RPC protocol to the browser.

Two transports for the *same* command set:

* ``POST /api/rpc`` — body is one JSON-RPC request ``{"cmd": ...}``; returns the
  response envelope. Errors are in-band (``{"ok": false, ...}``) so a bad
  command still returns HTTP 200, matching the line-protocol semantics.
* ``WS /api/ws`` — a persistent channel: send request objects, receive response
  objects (lower latency; used for live polling like ``eio_read``).

Blocking JTAG runs in a threadpool so the event loop stays responsive while a
capture waits for its trigger.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .._version import __version__
from ..openocd_launcher import OpenOcdLauncher
from ..rpc import _SCHEMA_VERSION, RpcServer
from .gateway import RpcGateway


def _default_surfer_dir() -> str:
    """Vendored Surfer WASM build shipped under ``fcapz/web/vendor/surfer``."""
    return str(Path(__file__).resolve().parent / "vendor" / "surfer")


def _is_loopback(host: Optional[str]) -> bool:
    return host in ("127.0.0.1", "::1", "localhost")


def _openocd_guard(req: dict, client_host: Optional[str]) -> Optional[dict]:
    """Restrict ``openocd_*`` (process spawning) to loopback clients.

    Returns an in-band error envelope to send back, or ``None`` to allow.
    A remote client must not be able to launch processes on the server host,
    even with a valid token.
    """
    cmd = req.get("cmd", "")
    if isinstance(cmd, str) and cmd.startswith("openocd_") and not _is_loopback(client_host):
        return {
            "ok": False,
            "schema_version": _SCHEMA_VERSION,
            "error": "OpenOCD control is restricted to localhost clients.",
            "type": "PermissionError",
        }
    return None


_LOOPBACK_HOST_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})


def _host_name(host_header: Optional[str]) -> Optional[str]:
    """Hostname part of a ``Host`` header, stripping the port and IPv6 brackets."""
    if not host_header:
        return None
    h = host_header.strip()
    if h.startswith("["):  # [::1]:7373
        end = h.find("]")
        return h[1:end] if end != -1 else h
    return h.rsplit(":", 1)[0] if ":" in h else h


def _host_header_ok(host_header: Optional[str], bind_host: Optional[str]) -> bool:
    """Anti-DNS-rebinding gate.

    When the server is bound to loopback, only accept requests whose ``Host``
    header is a loopback name — a rebinding page reaches the API from its own
    (non-loopback) name. For non-loopback binds we cannot allow-list arbitrary
    external hostnames, so this is a no-op there and those deployments rely on
    ``--token`` (a rebinding origin cannot read the token). ``bind_host=None``
    (e.g. tests) also disables the check.
    """
    if not _is_loopback(bind_host):
        return True
    return _host_name(host_header) in _LOOPBACK_HOST_NAMES


def create_app(
    *,
    gateway: Optional[RpcGateway] = None,
    token: Optional[str] = None,
    static_dir: Optional[str] = None,
    surfer_dir: Optional[str] = None,
    cors_origins: Iterable[str] = (),
    openocd_launcher: Optional[OpenOcdLauncher] = None,
    bind_host: Optional[str] = None,
) -> FastAPI:
    """Build the fcapz web app.

    ``token`` (if set) is required as ``Authorization: Bearer <token>`` on
    ``/api/rpc`` and as ``?token=`` on the WebSocket.  ``static_dir`` is the
    built frontend served at ``/`` (optional).  ``surfer_dir`` is the vendored
    Surfer waveform viewer served at ``/surfer`` (defaults to the bundled copy);
    it lives outside ``static_dir`` so a frontend rebuild can't wipe it.
    """
    if gateway is None:
        gateway = RpcGateway(RpcServer(openocd_launcher=openocd_launcher))
    app = FastAPI(title="fpgacapZero web", version="1")
    app.state.gateway = gateway
    # OpenOCD instances this server starts are torn down on interpreter exit via
    # OpenOcdLauncher's atexit hook (uvicorn returns cleanly on SIGINT/SIGTERM),
    # so no FastAPI shutdown hook is needed here.
    # Cross-origin sharing is OFF by default: the bundled UI is same-origin (dev
    # proxies /api too), so no browser workflow needs it. Enable it only when a
    # frontend is served from a different origin — a wildcard here would let any
    # website drive the board via the API.
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cors_origins),
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def auth(authorization: Optional[str] = Header(default=None)) -> None:
        if token is None:
            return
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="invalid or missing token")

    @app.get("/api/version")
    async def version() -> dict:
        # Public metadata (no auth) so the UI can show the version pre-connect.
        return {"version": __version__}

    @app.post("/api/rpc")
    async def rpc(req: dict, request: Request, _: None = Depends(auth)):
        if not _host_header_ok(request.headers.get("host"), bind_host):
            return {
                "ok": False,
                "schema_version": _SCHEMA_VERSION,
                "error": "Host not allowed (possible DNS rebinding).",
                "type": "PermissionError",
            }
        blocked = _openocd_guard(req, request.client.host if request.client else None)
        if blocked is not None:
            return blocked
        return await run_in_threadpool(gateway.call, req)

    @app.websocket("/api/ws")
    async def ws(websocket: WebSocket):
        if not _host_header_ok(websocket.headers.get("host"), bind_host):
            await websocket.close(code=1008)
            return
        if token is not None and websocket.query_params.get("token") != token:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            while True:
                msg = await websocket.receive_text()
                try:
                    req = json.loads(msg)
                except json.JSONDecodeError as exc:
                    await websocket.send_json(
                        {"ok": False, "error": f"invalid JSON: {exc}", "type": "JSONDecodeError"}
                    )
                    continue
                blocked = _openocd_guard(
                    req, websocket.client.host if websocket.client else None
                )
                if blocked is not None:
                    await websocket.send_json(blocked)
                    continue
                resp = await run_in_threadpool(gateway.call, req)
                await websocket.send_json(resp)
        except WebSocketDisconnect:
            return

    # Vendored Surfer waveform viewer (WASM) at /surfer — mounted before "/" so
    # it isn't shadowed by the SPA catch-all.
    surfer = surfer_dir or _default_surfer_dir()
    if Path(surfer).is_dir():
        app.mount("/surfer", StaticFiles(directory=surfer, html=True), name="surfer")

    # Serve the built frontend last so /api and /surfer take precedence.
    if static_dir and Path(static_dir).is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app
