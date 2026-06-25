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

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .gateway import RpcGateway


def create_app(
    *,
    gateway: Optional[RpcGateway] = None,
    token: Optional[str] = None,
    static_dir: Optional[str] = None,
    cors_origins: Iterable[str] = ("*",),
) -> FastAPI:
    """Build the fcapz web app.

    ``token`` (if set) is required as ``Authorization: Bearer <token>`` on
    ``/api/rpc`` and as ``?token=`` on the WebSocket.  ``static_dir`` is the
    built frontend served at ``/`` (optional).
    """
    gateway = gateway or RpcGateway()
    app = FastAPI(title="fpgacapZero web", version="1")
    app.state.gateway = gateway
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

    @app.post("/api/rpc")
    async def rpc(req: dict, _: None = Depends(auth)):
        return await run_in_threadpool(gateway.call, req)

    @app.websocket("/api/ws")
    async def ws(websocket: WebSocket):
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
                resp = await run_in_threadpool(gateway.call, req)
                await websocket.send_json(resp)
        except WebSocketDisconnect:
            return

    # Serve the built frontend last so /api routes take precedence.
    if static_dir and Path(static_dir).is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app
