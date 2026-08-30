# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""fpgacapZero web frontend backend.

A small FastAPI server that exposes the **same** JSON-RPC command protocol as
``python -m fcapz.rpc`` (the unified fcapz API) over HTTP + WebSocket, so the
board can be driven from a browser — locally or from another machine — and
serves the built browser UI as static files.

Run with the ``fcapz-web`` console script or ``python -m fcapz.web``.
"""

from .app import create_app
from .gateway import RpcGateway

__all__ = ["create_app", "RpcGateway"]
