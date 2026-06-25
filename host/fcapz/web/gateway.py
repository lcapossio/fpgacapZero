# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Serialized JSON-RPC gateway shared by all web clients.

The web frontend speaks the **same** ``cmd``-based JSON-RPC protocol as
``python -m fcapz.rpc`` (stdin/stdout) — one unified API, just a different
transport.  This wraps a single :class:`~fcapz.rpc.RpcServer` behind a lock
(JTAG is one physical resource) and returns the identical success/error
envelopes the line-protocol server returns.
"""

from __future__ import annotations

import threading
import traceback
from typing import Any, Dict, Optional

from ..rpc import _SCHEMA_VERSION, RpcServer


class RpcGateway:
    """Thread-safe wrapper around one :class:`RpcServer`."""

    def __init__(self, server: Optional[RpcServer] = None) -> None:
        self._server = server or RpcServer()
        self._lock = threading.RLock()

    def call(self, req: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch one JSON-RPC request and return its response envelope.

        Errors are returned **in-band** as ``{"ok": false, ...}`` — exactly the
        shape ``fcapz.rpc.main`` emits — not raised, so every transport sees the
        same protocol.
        """
        with self._lock:
            try:
                return self._server.handle(req)
            except Exception as exc:  # noqa: BLE001 - mirror the line-protocol envelope
                return {
                    "ok": False,
                    "schema_version": _SCHEMA_VERSION,
                    "error": str(exc),
                    "type": exc.__class__.__name__,
                    "trace": traceback.format_exc(limit=1).strip(),
                }
