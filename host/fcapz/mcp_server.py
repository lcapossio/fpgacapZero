# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""MCP server for fpgacapZero lab automation.

The MCP SDK is an optional dependency. Import this module freely in the normal
package; the SDK is only imported when building/running the server.
"""

from __future__ import annotations

import argparse
import base64
import importlib.metadata
import os
import queue
import json
import sys
import threading
from threading import RLock
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ._version import __version__
from .rpc import _SCHEMA_VERSION, RpcServer


JsonDict = dict[str, Any]


@dataclass
class McpCapabilities:
    """Safety switches for MCP-exposed hardware operations."""

    allow_capture: bool = True
    allow_eio_write: bool = False
    allow_axi_write: bool = False
    allow_uart_send: bool = False
    allow_program: bool = False
    bitfile_root: Path | None = None
    rpc_timeout_sec: float = 30.0


class FcapzMcpError(RuntimeError):
    """Error raised for structured MCP/session failures."""

    def __init__(self, message: str, *, payload: JsonDict | None = None) -> None:
        super().__init__(message)
        self.payload = dict(payload or {"error": message})


@dataclass
class FcapzMcpSession:
    """Small stateful facade over :class:`RpcServer` for MCP tools."""

    rpc: RpcServer = field(default_factory=RpcServer)
    capabilities: McpCapabilities = field(default_factory=McpCapabilities)
    connected: bool = False
    eio_connected: bool = False
    axi_connected: bool = False
    uart_connected: bool = False
    last_probe: JsonDict | None = None
    last_capture: JsonDict | None = None
    last_capture_summary: JsonDict | None = None
    last_eio_read: JsonDict | None = None
    last_rpc_schema_version: str | None = _SCHEMA_VERSION
    _rpc_lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _active_rpc_worker: threading.Thread | None = field(default=None, init=False, repr=False)
    _active_rpc_cmd: str | None = field(default=None, init=False, repr=False)

    _CAPTURE_CONFIG_KEYS = frozenset({
        "pretrigger",
        "posttrigger",
        "trigger_mode",
        "trigger_value",
        "trigger_mask",
        "sample_width",
        "depth",
        "sample_clock_hz",
        "probes",
        "probe_file",
        "channel",
        "decimation",
        "ext_trigger_mode",
        "stor_qual_mode",
        "stor_qual_value",
        "stor_qual_mask",
        "startup_arm",
        "trigger_holdoff",
        "trigger_delay",
    })

    def _rpc_call(self, req: JsonDict) -> JsonDict:
        result_queue: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

        def run_call() -> None:
            try:
                result_queue.put((True, self.rpc.handle(req)))
            except BaseException as exc:
                result_queue.put((False, exc))

        worker = threading.Thread(target=run_call, name="fcapz-mcp-rpc", daemon=True)
        with self._rpc_lock:
            if self._active_rpc_worker is not None:
                if self._active_rpc_worker.is_alive():
                    raise RuntimeError(
                        f"previous fcapz RPC call {self._active_rpc_cmd!r} is still "
                        "running after a timeout; restart the MCP server before "
                        "issuing more hardware commands"
                    )
                self._active_rpc_worker = None
                self._active_rpc_cmd = None
            self._active_rpc_worker = worker
            self._active_rpc_cmd = str(req.get("cmd"))
            worker.start()
        worker.join(self.capabilities.rpc_timeout_sec)
        if worker.is_alive():
            raise TimeoutError(
                f"fcapz RPC call {req.get('cmd')!r} timed out after "
                f"{self.capabilities.rpc_timeout_sec:g}s"
            )
        with self._rpc_lock:
            # A timed-out worker may finish after a later call has reserved the slot.
            # Only the owner may clear the active marker.
            if self._active_rpc_worker is worker:
                self._active_rpc_worker = None
                self._active_rpc_cmd = None
        ok, result = result_queue.get_nowait()
        if not ok:
            raise result  # type: ignore[misc]
        return self._ok_response(result)  # type: ignore[arg-type]

    def _ok_response(self, response: JsonDict) -> JsonDict:
        if not response.get("ok", False):
            error = response.get("error", response)
            message = error if isinstance(error, str) else json.dumps(error, sort_keys=True)
            raise FcapzMcpError(message, payload=response)
        if "schema_version" in response:
            self.last_rpc_schema_version = str(response["schema_version"])
        return response

    @staticmethod
    def _server_version() -> str | None:
        try:
            return importlib.metadata.version("fpgacapzero")
        except importlib.metadata.PackageNotFoundError:
            return __version__ or None

    @staticmethod
    def _default_tap(backend: str) -> str:
        return "xc7a100t.tap" if backend == "openocd" else "xc7a100t"

    @staticmethod
    def _default_eio_chain(backend: str) -> int:
        if backend in ("usb_blaster", "spi"):
            return 0
        return 3

    @staticmethod
    def _reject_fields(backend: str, fields: dict[str, object | None]) -> None:
        present = sorted(name for name, value in fields.items() if value is not None)
        if present:
            raise ValueError(
                f"{', '.join(present)} not supported for backend {backend!r}"
            )

    def _add_connection_fields(
        self,
        req: JsonDict,
        *,
        backend: str,
        host: str | None,
        port: int | None,
        tap: str | None,
        hardware: str | None,
        quartus_stp: str | None,
        spi_url: str | None,
        spi_frequency: float | None,
        spi_cs: int | None,
        spi_timeout: float | None,
    ) -> None:
        if backend in ("hw_server", "openocd"):
            self._reject_fields(
                backend,
                {
                    "hardware": hardware,
                    "quartus_stp": quartus_stp,
                    "spi_url": spi_url,
                    "spi_frequency": spi_frequency,
                    "spi_cs": spi_cs,
                    "spi_timeout": spi_timeout,
                },
            )
            req["host"] = host or "127.0.0.1"
            req["tap"] = tap or self._default_tap(backend)
            if port is not None:
                req["port"] = int(port)
            return

        if backend == "usb_blaster":
            self._reject_fields(
                backend,
                {
                    "tap": tap,
                    "spi_url": spi_url,
                    "spi_frequency": spi_frequency,
                    "spi_cs": spi_cs,
                    "spi_timeout": spi_timeout,
                    "port": port,
                    "host": host,
                },
            )
            if hardware is not None:
                req["hardware"] = hardware
            if quartus_stp is not None:
                req["quartus_stp"] = quartus_stp
            return

        if backend == "spi":
            self._reject_fields(
                backend,
                {
                    "tap": tap,
                    "hardware": hardware,
                    "quartus_stp": quartus_stp,
                    "port": port,
                    "host": host,
                },
            )
            if spi_url is not None:
                req["spi_url"] = spi_url
            if spi_frequency is not None:
                req["spi_frequency"] = float(spi_frequency)
            if spi_cs is not None:
                req["spi_cs"] = int(spi_cs)
            if spi_timeout is not None:
                req["spi_timeout"] = float(spi_timeout)
            return

        raise ValueError(f"unknown backend: {backend}")

    def connect(
        self,
        *,
        backend: str = "hw_server",
        host: str | None = None,
        port: int | None = None,
        tap: str | None = None,
        program: str | None = None,
        single_chain_burst: bool = True,
        hardware: str | None = None,
        quartus_stp: str | None = None,
        spi_url: str | None = None,
        spi_frequency: float | None = None,
        spi_cs: int | None = None,
        spi_timeout: float | None = None,
    ) -> JsonDict:
        program_path = self._validated_program_path(program, backend=backend)
        if self.connected:
            self.close()
        req: JsonDict = {
            "cmd": "connect",
            "backend": backend,
        }
        self._add_connection_fields(
            req,
            backend=backend,
            host=host,
            port=port,
            tap=tap,
            hardware=hardware,
            quartus_stp=quartus_stp,
            spi_url=spi_url,
            spi_frequency=spi_frequency,
            spi_cs=spi_cs,
            spi_timeout=spi_timeout,
        )
        if backend == "hw_server":
            req["single_chain_burst"] = single_chain_burst
        elif single_chain_burst is not True:
            raise ValueError(f"single_chain_burst not supported for backend {backend!r}")
        if program_path is not None:
            req["program"] = str(program_path)
        response = self._rpc_call(req)
        self.connected = True
        return response

    def _validated_program_path(self, program: str | None, *, backend: str) -> Path | None:
        if not program:
            return None
        if not self.capabilities.allow_program:
            raise PermissionError(
                "FPGA programming is disabled; restart with --allow-program to enable it"
            )
        if backend != "hw_server":
            raise ValueError(
                "program= is only supported for backend 'hw_server' in this MCP server"
            )
        path = Path(program).expanduser().resolve()
        if path.suffix.lower() != ".bit":
            raise ValueError(f"program must be a .bit file, got {path}")
        if not path.is_file():
            raise FileNotFoundError(f"program bitfile not found: {path}")
        root = self.capabilities.bitfile_root
        if root is not None:
            root_resolved = root.expanduser().resolve()
            if path != root_resolved and root_resolved not in path.parents:
                raise ValueError(
                    f"program bitfile {path} is outside allowed root {root_resolved}"
                )
        return path

    def close(self) -> JsonDict:
        if not self.connected:
            self.last_probe = None
            self.last_capture = None
            self.last_capture_summary = None
            return {"ok": True}
        response = self._rpc_call({"cmd": "close"})
        self.connected = False
        self.last_probe = None
        self.last_capture = None
        self.last_capture_summary = None
        return response

    def drop_last_capture(self) -> JsonDict:
        # Captures may contain large sample payloads. Probe and EIO caches are small
        # enough to retain until overwritten or closed.
        had_capture = self.last_capture is not None
        self.last_capture = None
        self.last_capture_summary = None
        return {"ok": True, "had_capture": had_capture}

    def get_last_capture(self) -> JsonDict:
        if self.last_capture is None:
            return {"available": False}
        return dict(self.last_capture)

    def probe(self) -> JsonDict:
        response = self._rpc_call({"cmd": "probe"})
        self.last_probe = dict(response.get("probe", {}))
        return response

    def capture(
        self,
        *,
        config: JsonDict | None = None,
        timeout: float = 10.0,
        fmt: str = "json",
        include_event_summary: bool = False,
    ) -> JsonDict:
        if not self.capabilities.allow_capture:
            raise PermissionError("capture tools are disabled for this MCP server")
        req: JsonDict = {
            "cmd": "capture",
            "timeout": float(timeout),
            "format": fmt,
            # MCP names this by intent; RPC still uses its historical field.
            "summarize": bool(include_event_summary),
        }
        if config:
            unknown = sorted(set(config) - self._CAPTURE_CONFIG_KEYS)
            if unknown:
                raise ValueError(f"unsupported capture config field(s): {', '.join(unknown)}")
            req = {**config, **req}
        response = self._rpc_call(req)
        self.last_capture = response
        self.last_capture_summary = self._capture_summary()
        return dict(self.last_capture_summary or {})

    def configure(self, config: JsonDict | None = None) -> JsonDict:
        if not self.capabilities.allow_capture:
            raise PermissionError("configure tools are disabled for this MCP server")
        req: JsonDict = {"cmd": "configure"}
        if config:
            unknown = sorted(set(config) - self._CAPTURE_CONFIG_KEYS)
            if unknown:
                raise ValueError(f"unsupported capture config field(s): {', '.join(unknown)}")
            req.update(config)
        return self._rpc_call(req)

    def arm(self) -> JsonDict:
        if not self.capabilities.allow_capture:
            raise PermissionError("arm tools are disabled for this MCP server")
        return self._rpc_call({"cmd": "arm"})

    def _bridge_connect_req(
        self,
        *,
        cmd: str,
        backend: str,
        host: str | None,
        port: int | None,
        tap: str | None,
        chain: int | None,
        hardware: str | None,
        quartus_stp: str | None,
        spi_url: str | None,
        spi_frequency: float | None,
        spi_cs: int | None,
        spi_timeout: float | None,
    ) -> JsonDict:
        req: JsonDict = {
            "cmd": cmd,
            "backend": backend,
            "chain": 4 if chain is None else int(chain),
        }
        self._add_connection_fields(
            req,
            backend=backend,
            host=host,
            port=port,
            tap=tap,
            hardware=hardware,
            quartus_stp=quartus_stp,
            spi_url=spi_url,
            spi_frequency=spi_frequency,
            spi_cs=spi_cs,
            spi_timeout=spi_timeout,
        )
        return req

    def eio_connect(
        self,
        *,
        backend: str = "hw_server",
        host: str | None = None,
        port: int | None = None,
        tap: str | None = None,
        chain: int | None = None,
        hardware: str | None = None,
        quartus_stp: str | None = None,
        spi_url: str | None = None,
        spi_frequency: float | None = None,
        spi_cs: int | None = None,
        spi_timeout: float | None = None,
    ) -> JsonDict:
        if self.eio_connected:
            self.eio_close()
        req: JsonDict = {
            "cmd": "eio_connect",
            "backend": backend,
            "chain": self._default_eio_chain(backend) if chain is None else int(chain),
        }
        self._add_connection_fields(
            req,
            backend=backend,
            host=host,
            port=port,
            tap=tap,
            hardware=hardware,
            quartus_stp=quartus_stp,
            spi_url=spi_url,
            spi_frequency=spi_frequency,
            spi_cs=spi_cs,
            spi_timeout=spi_timeout,
        )
        response = self._rpc_call(req)
        self.eio_connected = True
        return response

    def eio_close(self) -> JsonDict:
        if not self.eio_connected:
            self.last_eio_read = None
            return {"ok": True}
        response = self._rpc_call({"cmd": "eio_close"})
        self.eio_connected = False
        self.last_eio_read = None
        return response

    def eio_read(self) -> JsonDict:
        response = self._rpc_call({"cmd": "eio_read"})
        self.last_eio_read = dict(response)
        return response

    def eio_write(self, value: int) -> JsonDict:
        if not self.capabilities.allow_eio_write:
            raise PermissionError(
                "EIO writes are disabled; restart with --allow-eio-write to enable them"
            )
        return self._rpc_call({"cmd": "eio_write", "value": int(value)})

    def axi_connect(
        self,
        *,
        backend: str = "hw_server",
        host: str | None = None,
        port: int | None = None,
        tap: str | None = None,
        chain: int | None = None,
        hardware: str | None = None,
        quartus_stp: str | None = None,
        spi_url: str | None = None,
        spi_frequency: float | None = None,
        spi_cs: int | None = None,
        spi_timeout: float | None = None,
    ) -> JsonDict:
        if self.axi_connected:
            self.axi_close()
        response = self._rpc_call(
            self._bridge_connect_req(
                cmd="axi_connect",
                backend=backend,
                host=host,
                port=port,
                tap=tap,
                chain=chain,
                hardware=hardware,
                quartus_stp=quartus_stp,
                spi_url=spi_url,
                spi_frequency=spi_frequency,
                spi_cs=spi_cs,
                spi_timeout=spi_timeout,
            )
        )
        self.axi_connected = True
        return response

    def axi_close(self) -> JsonDict:
        if not self.axi_connected:
            return {"ok": True}
        response = self._rpc_call({"cmd": "axi_close"})
        self.axi_connected = False
        return response

    def axi_read(self, addr: int) -> JsonDict:
        return self._rpc_call({"cmd": "axi_read", "addr": int(addr)})

    def axi_write(self, addr: int, data: int, wstrb: int = 0xF) -> JsonDict:
        if not self.capabilities.allow_axi_write:
            raise PermissionError(
                "AXI writes are disabled; restart with --allow-axi-write to enable them"
            )
        return self._rpc_call(
            {"cmd": "axi_write", "addr": int(addr), "data": int(data), "wstrb": int(wstrb)}
        )

    def axi_write_block(
        self,
        addr: int,
        data: list[int],
        *,
        burst: bool = False,
    ) -> JsonDict:
        if not self.capabilities.allow_axi_write:
            raise PermissionError(
                "AXI writes are disabled; restart with --allow-axi-write to enable them"
            )
        return self._rpc_call(
            {
                "cmd": "axi_write_block",
                "addr": int(addr),
                "data": [int(word) for word in data],
                "burst": bool(burst),
            }
        )

    def axi_dump(self, addr: int, count: int, *, burst: bool = False) -> JsonDict:
        return self._rpc_call(
            {"cmd": "axi_dump", "addr": int(addr), "count": int(count), "burst": bool(burst)}
        )

    def uart_connect(
        self,
        *,
        backend: str = "hw_server",
        host: str | None = None,
        port: int | None = None,
        tap: str | None = None,
        chain: int | None = None,
        hardware: str | None = None,
        quartus_stp: str | None = None,
        spi_url: str | None = None,
        spi_frequency: float | None = None,
        spi_cs: int | None = None,
        spi_timeout: float | None = None,
    ) -> JsonDict:
        if self.uart_connected:
            self.uart_close()
        response = self._rpc_call(
            self._bridge_connect_req(
                cmd="uart_connect",
                backend=backend,
                host=host,
                port=port,
                tap=tap,
                chain=chain,
                hardware=hardware,
                quartus_stp=quartus_stp,
                spi_url=spi_url,
                spi_frequency=spi_frequency,
                spi_cs=spi_cs,
                spi_timeout=spi_timeout,
            )
        )
        self.uart_connected = True
        return response

    def uart_close(self) -> JsonDict:
        if not self.uart_connected:
            return {"ok": True}
        response = self._rpc_call({"cmd": "uart_close"})
        self.uart_connected = False
        return response

    def uart_send(self, data_base64: str | None = None, text: str | None = None) -> JsonDict:
        if not self.capabilities.allow_uart_send:
            raise PermissionError(
                "UART sends are disabled; restart with --allow-uart-send to enable them"
            )
        if data_base64 is not None and text is not None:
            raise ValueError("provide only one of data_base64 or text")
        if data_base64 is None:
            if text is None:
                raise ValueError("provide either data_base64 or text")
            data_base64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        return self._rpc_call({"cmd": "uart_send", "data": data_base64})

    def uart_recv(self, count: int, timeout: float = 1.0) -> JsonDict:
        return self._rpc_call({"cmd": "uart_recv", "count": int(count), "timeout": float(timeout)})

    def uart_status(self) -> JsonDict:
        return self._rpc_call({"cmd": "uart_status"})

    def status(self) -> JsonDict:
        return {
            "mcp_server_version": self._server_version(),
            "rpc_schema_version": self.last_rpc_schema_version,
            "connected": self.connected,
            "eio_connected": self.eio_connected,
            "axi_connected": self.axi_connected,
            "uart_connected": self.uart_connected,
            "capabilities": {
                "allow_capture": self.capabilities.allow_capture,
                "allow_eio_write": self.capabilities.allow_eio_write,
                "allow_axi_write": self.capabilities.allow_axi_write,
                "allow_uart_send": self.capabilities.allow_uart_send,
                "allow_program": self.capabilities.allow_program,
                "bitfile_root": (
                    str(self.capabilities.bitfile_root)
                    if self.capabilities.bitfile_root is not None
                    else None
                ),
            },
            "last_probe": dict(self.last_probe) if self.last_probe is not None else None,
            "last_capture_summary": (
                dict(self.last_capture_summary)
                if self.last_capture_summary is not None
                else None
            ),
            "last_eio_read": (
                dict(self.last_eio_read) if self.last_eio_read is not None else None
            ),
        }

    def _capture_summary(self) -> JsonDict | None:
        if self.last_capture is None:
            return None
        # Keep tool results compact while allowing newly added top-level metadata
        # to surface automatically. Update this set when RPC adds bulky payloads.
        bulky_keys = {
            "content",
            "csv",
            "data",
            "raw_dump",
            "result",
            "samples",
            "timestamps",
            "vcd",
            "words",
        }
        summary: JsonDict = {
            key: value for key, value in self.last_capture.items() if key not in bulky_keys
        }
        summary.setdefault("ok", True)
        return summary

    def shutdown(self) -> None:
        include_trace = os.environ.get("FCAPZ_MCP_DEBUG_SHUTDOWN", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        errors: list[JsonDict] = []
        for name, close in (
            ("close", self.close),
            ("eio_close", self.eio_close),
            ("axi_close", self.axi_close),
            ("uart_close", self.uart_close),
        ):
            try:
                close()
            except Exception as exc:
                error: JsonDict = {
                    "step": name,
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                }
                if include_trace:
                    error["traceback"] = traceback.format_exc()
                errors.append(error)
        if errors:
            print(
                json.dumps(
                    {
                        "event": "shutdown_errors",
                        "errors": errors,
                    },
                    separators=(",", ":"),
                ),
                file=sys.stderr,
            )


def build_mcp_server(session: FcapzMcpSession):
    """Build and return a FastMCP app.

    Kept separate so unit tests can cover :class:`FcapzMcpSession` without the
    optional MCP SDK installed.
    """

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "The MCP SDK is required for `fcapz-mcp`. Install with "
            "`pip install fpgacapzero[mcp]` or `pip install mcp`."
        ) from exc

    mcp = FastMCP("fpgacapZero")

    def tool(**annotations: Any):
        def decorate(fn: Callable[..., Any]):
            return mcp.tool(annotations=annotations)(fn)

        return decorate

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=False)
    def fcapz_connect(
        backend: str = "hw_server",
        host: str | None = None,
        port: int | None = None,
        tap: str | None = None,
        program: str | None = None,
        single_chain_burst: bool = True,
        hardware: str | None = None,
        quartus_stp: str | None = None,
        spi_url: str | None = None,
        spi_frequency: float | None = None,
        spi_cs: int | None = None,
        spi_timeout: float | None = None,
    ) -> JsonDict:
        """Connect to an ELA core.

        Supported by this branch's RPC layer: backend="hw_server" and
        backend="openocd". Backend-specific parameters are accepted and
        forwarded for compatibility with newer transports: hardware selects a
        Quartus cable, quartus_stp selects the Quartus STP executable, spi_url
        selects a pyftdi SPI adapter, spi_frequency is in Hz, spi_cs is the SPI
        chip-select index, and spi_timeout is in seconds. Other timeout values
        are also seconds. Backend-irrelevant fields are rejected instead of
        forwarded. program is hw_server-only, disabled unless fcapz-mcp was
        started with --allow-program, and must be an existing .bit file.
        """

        return session.connect(
            backend=backend,
            host=host,
            port=port,
            tap=tap,
            program=program,
            single_chain_burst=single_chain_burst,
            hardware=hardware,
            quartus_stp=quartus_stp,
            spi_url=spi_url,
            spi_frequency=spi_frequency,
            spi_cs=spi_cs,
            spi_timeout=spi_timeout,
        )

    @tool(destructiveHint=False, idempotentHint=True, readOnlyHint=False)
    def fcapz_close() -> JsonDict:
        """Close the active ELA connection."""

        return session.close()

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=True)
    def fcapz_probe() -> JsonDict:
        """Read ELA identity, dimensions, and feature registers."""

        return session.probe()

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=False)
    def fcapz_capture(
        config: JsonDict | None = None,
        timeout: float = 10.0,
        format: str = "json",
        include_event_summary: bool = False,
    ) -> JsonDict:
        """Configure, arm, and capture samples from the ELA.

        timeout is in seconds. format is "json", "csv", or "vcd".
        include_event_summary asks the RPC layer to add decoded event metadata
        to the capture result. config may contain capture fields only:
        pretrigger, posttrigger, trigger_mode, trigger_value, trigger_mask,
        sample_width, depth, sample_clock_hz, probes, probe_file, channel,
        decimation, ext_trigger_mode, stor_qual_mode/value/mask, startup_arm,
        trigger_holdoff, trigger_delay. The tool returns summary metadata only;
        use fcapz_get_last_capture or fcapz://last-capture for full payloads.
        """

        return session.capture(
            config=config,
            timeout=timeout,
            fmt=format,
            include_event_summary=include_event_summary,
        )

    @tool(destructiveHint=False, idempotentHint=True, readOnlyHint=False)
    def fcapz_drop_last_capture() -> JsonDict:
        """Forget the cached full capture payload exposed by fcapz://last-capture."""

        return session.drop_last_capture()

    @tool(destructiveHint=False, idempotentHint=True, readOnlyHint=True)
    def fcapz_get_last_capture() -> JsonDict:
        """Return the cached full capture payload for clients without resource support.

        This can be large enough to flood model context after deep captures. Prefer
        fcapz://last-capture when the MCP client supports resources.
        """

        return session.get_last_capture()

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=False)
    def fcapz_configure(config: JsonDict | None = None) -> JsonDict:
        """Configure the connected ELA without arming it.

        config accepts the same capture fields as fcapz_capture. This is useful
        when an agent must configure trigger settings and arm later in a
        separate step.
        """

        return session.configure(config=config)

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=False)
    def fcapz_arm() -> JsonDict:
        """Arm the connected ELA using the current hardware configuration."""

        return session.arm()

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=False)
    def fcapz_eio_connect(
        backend: str = "hw_server",
        host: str | None = None,
        port: int | None = None,
        tap: str | None = None,
        chain: int | None = None,
        hardware: str | None = None,
        quartus_stp: str | None = None,
        spi_url: str | None = None,
        spi_frequency: float | None = None,
        spi_cs: int | None = None,
        spi_timeout: float | None = None,
    ) -> JsonDict:
        """Connect to an Embedded I/O core.

        chain defaults by backend: 3 for hw_server/openocd, 0 for
        usb_blaster/spi. Pass chain explicitly for non-default JTAG USER chains,
        Intel virtual JTAG instance indices, or managed core slots. Backend
        fields mirror fcapz_connect: hardware/quartus_stp for Quartus USB
        Blaster sessions and spi_url/spi_frequency/spi_cs/spi_timeout for SPI
        register transports.
        """

        return session.eio_connect(
            backend=backend,
            host=host,
            port=port,
            tap=tap,
            chain=chain,
            hardware=hardware,
            quartus_stp=quartus_stp,
            spi_url=spi_url,
            spi_frequency=spi_frequency,
            spi_cs=spi_cs,
            spi_timeout=spi_timeout,
        )

    @tool(destructiveHint=False, idempotentHint=True, readOnlyHint=False)
    def fcapz_eio_close() -> JsonDict:
        """Close the active EIO connection."""

        return session.eio_close()

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=True)
    def fcapz_eio_read() -> JsonDict:
        """Read the current EIO input vector."""

        return session.eio_read()

    @tool(destructiveHint=True, idempotentHint=False, readOnlyHint=False)
    def fcapz_eio_write(value: int) -> JsonDict:
        """Write the EIO output vector when write access is enabled."""

        return session.eio_write(value)

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=False)
    def fcapz_axi_connect(
        backend: str = "hw_server",
        host: str | None = None,
        port: int | None = None,
        tap: str | None = None,
        chain: int | None = None,
        hardware: str | None = None,
        quartus_stp: str | None = None,
        spi_url: str | None = None,
        spi_frequency: float | None = None,
        spi_cs: int | None = None,
        spi_timeout: float | None = None,
    ) -> JsonDict:
        """Connect to an eJTAG-to-AXI4 bridge.

        chain defaults to 4. Backend fields mirror fcapz_connect and are
        validated before reaching the RPC layer.
        """

        return session.axi_connect(
            backend=backend,
            host=host,
            port=port,
            tap=tap,
            chain=chain,
            hardware=hardware,
            quartus_stp=quartus_stp,
            spi_url=spi_url,
            spi_frequency=spi_frequency,
            spi_cs=spi_cs,
            spi_timeout=spi_timeout,
        )

    @tool(destructiveHint=False, idempotentHint=True, readOnlyHint=False)
    def fcapz_axi_close() -> JsonDict:
        """Close the active AXI bridge connection."""

        return session.axi_close()

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=True)
    def fcapz_axi_read(addr: int) -> JsonDict:
        """Read one 32-bit AXI word from a byte address.

        addr is an integer byte address, not a word index. Use decimal JSON
        integers; convert hex strings such as "0x40000000" before calling.
        """

        return session.axi_read(addr)

    @tool(destructiveHint=True, idempotentHint=False, readOnlyHint=False)
    def fcapz_axi_write(
        addr: int,
        data: int,
        wstrb: int = 0xF,
    ) -> JsonDict:
        """Write one 32-bit AXI word when AXI write access is enabled.

        addr is an integer byte address. data is a 32-bit integer word. wstrb is
        a 4-bit integer byte-lane mask where bit 0 controls addr[7:0].
        """

        return session.axi_write(addr, data, wstrb)

    @tool(destructiveHint=True, idempotentHint=False, readOnlyHint=False)
    def fcapz_axi_write_block(
        addr: int,
        data: list[int],
        burst: bool = False,
    ) -> JsonDict:
        """Write 32-bit AXI words starting at an integer byte address.

        data is a list of integer words. When burst is false, words are written
        sequentially; when true, the bridge uses its burst write path.
        """

        return session.axi_write_block(addr, data, burst=burst)

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=True)
    def fcapz_axi_dump(addr: int, count: int, burst: bool = False) -> JsonDict:
        """Read count 32-bit AXI words starting at an integer byte address.

        count is measured in 32-bit words, not bytes.
        """

        return session.axi_dump(addr, count, burst=burst)

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=False)
    def fcapz_uart_connect(
        backend: str = "hw_server",
        host: str | None = None,
        port: int | None = None,
        tap: str | None = None,
        chain: int | None = None,
        hardware: str | None = None,
        quartus_stp: str | None = None,
        spi_url: str | None = None,
        spi_frequency: float | None = None,
        spi_cs: int | None = None,
        spi_timeout: float | None = None,
    ) -> JsonDict:
        """Connect to an eJTAG-UART bridge.

        chain defaults to 4. Backend fields mirror fcapz_connect and are
        validated before reaching the RPC layer.
        """

        return session.uart_connect(
            backend=backend,
            host=host,
            port=port,
            tap=tap,
            chain=chain,
            hardware=hardware,
            quartus_stp=quartus_stp,
            spi_url=spi_url,
            spi_frequency=spi_frequency,
            spi_cs=spi_cs,
            spi_timeout=spi_timeout,
        )

    @tool(destructiveHint=False, idempotentHint=True, readOnlyHint=False)
    def fcapz_uart_close() -> JsonDict:
        """Close the active UART bridge connection."""

        return session.uart_close()

    @tool(destructiveHint=True, idempotentHint=False, readOnlyHint=False)
    def fcapz_uart_send(
        data_base64: str | None = None,
        text: str | None = None,
    ) -> JsonDict:
        """Send bytes over eJTAG-UART when UART send access is enabled.

        Pass data_base64 for arbitrary bytes or text for UTF-8 text.
        """

        return session.uart_send(data_base64=data_base64, text=text)

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=True)
    def fcapz_uart_recv(count: int, timeout: float = 1.0) -> JsonDict:
        """Receive up to count bytes from eJTAG-UART; timeout is in seconds."""

        return session.uart_recv(count, timeout)

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=True)
    def fcapz_uart_status() -> JsonDict:
        """Return eJTAG-UART status counters and FIFO state."""

        return session.uart_status()

    @tool(destructiveHint=False, idempotentHint=True, readOnlyHint=True)
    def fcapz_status() -> JsonDict:
        """Return current MCP server session status."""

        return session.status()

    @mcp.resource("fcapz://status")
    def fcapz_status_resource() -> str:
        """Current MCP server session status."""

        return json.dumps(session.status(), separators=(",", ":"))

    @mcp.resource("fcapz://last-probe")
    def fcapz_last_probe() -> str:
        """Last ELA probe response."""

        payload = session.last_probe if session.last_probe is not None else {"available": False}
        return json.dumps(payload, separators=(",", ":"))

    @mcp.resource("fcapz://last-capture")
    def fcapz_last_capture() -> str:
        """Last capture response."""

        payload = session.last_capture if session.last_capture is not None else {"available": False}
        return json.dumps(payload, separators=(",", ":"))

    @mcp.resource("fcapz://last-eio-read")
    def fcapz_last_eio_read() -> str:
        """Last EIO read response."""

        payload = (
            session.last_eio_read
            if session.last_eio_read is not None
            else {"available": False}
        )
        return json.dumps(payload, separators=(",", ":"))

    return mcp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fcapz-mcp",
        description="Run an MCP server for fpgacapZero lab automation",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help=(
            "Disable capture/configure/arm and write/send tools; "
            "probe/read/status tools remain available"
        ),
    )
    parser.add_argument(
        "--allow-eio-write",
        action="store_true",
        help="Allow fcapz_eio_write to drive fabric outputs",
    )
    parser.add_argument(
        "--allow-axi-write",
        action="store_true",
        help="Allow fcapz_axi_write and fcapz_axi_write_block to modify AXI memory/registers",
    )
    parser.add_argument(
        "--allow-uart-send",
        action="store_true",
        help="Allow fcapz_uart_send to transmit bytes into the target",
    )
    parser.add_argument(
        "--allow-program",
        action="store_true",
        help="Allow fcapz_connect(program=...) to program a .bit file",
    )
    parser.add_argument(
        "--bitfile-root",
        type=Path,
        default=None,
        metavar="DIR",
        help="Only allow programming .bit files under this directory",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.read_only and (
        args.allow_eio_write
        or args.allow_axi_write
        or args.allow_uart_send
        or args.allow_program
    ):
        parser.error(
            "--read-only cannot be combined with write/program enable flags"
        )
    if args.bitfile_root is not None and not args.allow_program:
        parser.error("--bitfile-root requires --allow-program")
    capabilities = McpCapabilities(
        allow_capture=not args.read_only,
        allow_eio_write=bool(args.allow_eio_write),
        allow_axi_write=bool(args.allow_axi_write),
        allow_uart_send=bool(args.allow_uart_send),
        allow_program=bool(args.allow_program),
        bitfile_root=args.bitfile_root,
    )
    session = FcapzMcpSession(capabilities=capabilities)
    server = build_mcp_server(session)
    run: Callable[..., Any] = server.run
    try:
        run(transport="stdio")
    except Exception as exc:
        print(f"fcapz-mcp: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    finally:
        session.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
