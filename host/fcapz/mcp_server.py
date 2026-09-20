# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""MCP server for fpgacapZero lab automation.

The MCP SDK is an optional dependency. Import this module freely in the normal
package; the SDK is only imported when building/running the server.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import functools
import importlib.metadata
import inspect
import math
import os
import stat
import queue
import json
import sys
import threading
import time
from threading import RLock
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Optional

try:
    from pydantic import ConfigDict, ValidationError
except ImportError:  # pragma: no cover - no SDK installed
    ConfigDict = dict  # type: ignore[assignment,misc]

    class ValidationError(Exception):  # type: ignore[no-redef]
        pass

try:
    # pydantic -- and so the MCP tool schema -- refuses typing.TypedDict on
    # Python < 3.12, and the project supports 3.10. typing_extensions ships
    # with pydantic, so it is there whenever a schema is actually built; the
    # fallback only keeps this module importable without the MCP extra.
    from typing_extensions import NotRequired, TypedDict
except ImportError:  # pragma: no cover - no SDK installed
    from typing import TypedDict

    # typing.NotRequired is 3.11+, and this branch has to stay importable on
    # 3.10. Nothing evaluates the annotation without pydantic, so the name
    # only has to exist.
    try:
        from typing import NotRequired  # type: ignore[attr-defined]
    except ImportError:
        NotRequired = Optional  # type: ignore[assignment,misc]

from ._version import __version__
from .analyzer import CaptureNotReady
from .axi_decode import FAULT_FLAGS, PAIRING_ASSUMPTION
from .probes import load_probe_text
from .rpc import (
    _SCHEMA_VERSION,
    NotConnectedError,
    NotEnabledError,
    RpcError,
    RpcServer,
)


JsonDict = dict[str, Any]

# Closed sets, spelled so the MCP client sees them as `enum` in the tool
# schema and can reject a bad value before spending a round trip on it. The
# session still validates: a schema is the client's contract, not the
# server's guarantee.
Backend = Literal["hw_server", "openocd", "usb_blaster"]
CaptureFormat = Literal["json", "csv", "vcd"]
SampleRadix = Literal["hex", "int"]
TransactionKind = Literal["read", "write"]
TriggerMode = Literal["value_match", "edge_detect", "both"]
ExtTriggerMode = Literal[0, 1, 2]  # 0=disabled, 1=OR, 2=AND


class ProbeEntry(TypedDict):
    """One named sub-signal of the packed sample word."""

    name: str
    width: int
    # Optional: the probe parser defaults it to 0 (rpc._parse_probes).
    # Declaring it required would reject a map the CLI and web UI accept.
    lsb: NotRequired[int]


# ---------------------------------------------------------------------------
# Result shapes.
#
# A declared outputSchema is not documentation: FastMCP validates the return
# against it and drops anything the schema does not name from
# `structuredContent`. So only the payloads this module builds end to end are
# typed here. Everything else is an RPC response passed through verbatim --
# its keys vary with backend and core revision, and naming a subset would
# quietly delete the rest for any client reading structured output. Those
# tools keep an open `JsonDict` on purpose.
# ---------------------------------------------------------------------------


# Every field of these is always present. An optional TypedDict field is not
# actually optional on the wire: FastMCP dumps the validated model, so an
# absent field comes back as an injected null anyway -- and is advertised with
# a `"default": null` that contradicts its own declared type. One complete
# shape is both honest and easier to consume than two.


class SamplePage(TypedDict):
    """One page of `fcapz_get_capture_samples`."""

    available: bool
    reason: str | None
    total: int
    start: int
    count: int
    next_start: int | None
    radix: SampleRadix
    sample_width: int | None
    trigger_index: int | None
    # Sample records are shaped by the capture's probe map, so they stay open.
    samples: list[dict[str, Any]]
    segments: int | None
    fields: list[str] | None


class AxiTransactionPage(TypedDict):
    """One page of `fcapz_axi_transactions`."""

    available: bool
    reason: str | None
    total: int
    start: int
    count: int
    next_start: int | None
    filters: dict[str, Any] | None
    # On every page, not just the first, and not only when the trace happened
    # to prove the assumption false. AXI4-Lite has no transaction IDs, so a
    # window that opened mid-transaction yields addresses that look perfectly
    # ordinary and are wrong. A reader who is shown the rows without the
    # caveat has no way to know that.
    pairing: dict[str, Any] | None
    # How the capture was taken, when it decides what can be reconstructed
    # (decimation and storage qualification drop cycles, and with them
    # handshakes). Null when no decode is cached.
    sampling: dict[str, Any] | None
    transactions: list[dict[str, Any]]


class CaptureChunk(TypedDict):
    """One byte window of `fcapz_get_last_capture_chunk`."""

    available: bool
    reason: str | None
    encoding: str | None
    offset: int
    max_bytes: int | None
    size_bytes: int
    chunk: str
    next_offset: int | None
    eof: bool


class SessionStatus(TypedDict):
    """Everything `fcapz_status` reports. Every field is always present."""

    mcp_server_version: str | None
    rpc_schema_version: str | None
    session_state: Literal["ready", "busy", "poisoned"]
    rpc_busy: bool
    active_rpc_cmd: str | None
    connected: bool
    eio_connected: bool
    axi_connected: bool
    uart_connected: bool
    capabilities: dict[str, Any]
    last_probe: dict[str, Any] | None
    last_capture_summary: dict[str, Any] | None
    last_capture_size_bytes: int | None
    last_eio_read: dict[str, Any] | None


class CaptureConfigDict(TypedDict, total=False):
    """Capture fields an agent may set.

    A TypedDict rather than `dict[str, Any]` so the tool schema names every
    field and its type instead of accepting anything and explaining the
    rejection afterwards. Bit vectors accept a base-prefixed string as well as
    an integer, because a value wider than 53 bits cannot survive a JSON
    number in a JavaScript client.

    `extra="forbid"` is load-bearing, not tidiness. Pydantic validates a
    TypedDict by *filtering*: without it `{"posttriger": 9}` is dropped before
    the call is made, the capture runs with the default posttrigger, the
    session's own unknown-key check never sees the typo, and the agent is
    told it succeeded. Forbidding extras puts `additionalProperties: false`
    in the published schema and names the offending field instead.
    """

    __pydantic_config__ = ConfigDict(extra="forbid")

    pretrigger: int
    posttrigger: int
    trigger_mode: TriggerMode
    trigger_value: int | str
    trigger_mask: int | str
    sample_width: int
    depth: int
    sample_clock_hz: int
    probes: list[ProbeEntry] | str
    probe_file: str
    channel: int
    decimation: int
    ext_trigger_mode: ExtTriggerMode
    stor_qual_mode: int
    stor_qual_value: int | str
    stor_qual_mask: int | str
    startup_arm: bool
    trigger_holdoff: int
    trigger_delay: int


_DEFAULT_CAPTURE_CHUNK_BYTES = 64 * 1024
_DEFAULT_FULL_CAPTURE_MAX_BYTES = 1024 * 1024
# Ceiling on AXI block ops: a single tool call reads/writes at most this many
# 32-bit words. Bounds both the JTAG round-trip time (watchdog) and the size of
# a dump landing straight in model context; larger transfers must be chunked.
_MAX_AXI_WORDS = 4096
_RPC_CANCEL_GRACE_SEC = 1.0
# How often a still-running hardware call reports that it is still running.
# Short enough that a client's progress bar moves, long enough that a 300 s
# capture does not produce a notification storm.
_PROGRESS_INTERVAL_SEC = 1.0
# The RPC layer caps every wait-bearing command at this many seconds
# (rpc._MAX_WAIT_SEC); callers are rejected above it rather than silently
# clamped, so the watchdog and the docstrings stay honest.
_MAX_WAIT_SEC = 300.0


@dataclass
class McpCapabilities:
    """Safety switches for MCP-exposed hardware operations."""

    allow_capture: bool = True
    allow_eio_write: bool = False
    allow_axi_write: bool = False
    allow_uart_send: bool = False
    allow_program: bool = False
    bitfile_root: Path | None = None
    probe_root: Path | None = None
    # Hosts the agent may point a backend at. Empty means loopback only:
    # `host` otherwise lets an agent reach any hw_server/OpenOCD on the LAN.
    allowed_hosts: tuple[str, ...] = ()
    rpc_timeout_sec: float = 30.0
    rpc_cancel_grace_sec: float = _RPC_CANCEL_GRACE_SEC


class FcapzMcpError(RuntimeError):
    """Error raised for structured MCP/session failures."""

    def __init__(
        self,
        message: str,
        *,
        payload: JsonDict | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.payload = dict(payload or {"error": message})
        self.code = code


# What a caller should do about each failure. MCP has no structured error
# channel -- a tool error reaches the agent as text -- so every failure is
# rendered as one compact JSON object instead of prose the agent has to
# pattern-match. `retryable` says whether repeating the identical call could
# ever work; `action` says what to do first when it could not.
_ERROR_ACTIONS: dict[str, tuple[bool, str]] = {
    "busy": (
        True,
        "wait for the running command to finish (fcapz_status shows "
        "active_rpc_cmd); JTAG runs one command at a time",
    ),
    "session_recovering": (
        True,
        "wait for the session to finish tearing down the abandoned command "
        "(fcapz_status shows session_state), then reconnect",
    ),
    "watchdog_timeout": (
        True,
        "the board session was torn down; call fcapz_connect again before "
        "retrying",
    ),
    "capture_not_ready": (
        True,
        "the trigger has not fired yet and the core is still armed; keep "
        "polling with fcapz_capture_wait, or widen the trigger",
    ),
    "timeout": (
        True,
        "the wait expired without the hardware finishing; retry with a larger "
        "timeout, or check that the trigger can fire",
    ),
    "not_connected": (True, "call the matching connect tool first"),
    "not_permitted": (
        False,
        "the operator must restart fcapz-mcp with the capability flag named "
        "in the message; no call can enable it",
    ),
    "invalid_argument": (False, "fix the argument named in the message"),
    "not_found": (False, "check the path; it does not exist on the server"),
    "unknown_tool": (
        False,
        "this server does not publish that tool; list the tools again -- the "
        "surface depends on which capability flags the operator enabled",
    ),
    "hardware_error": (
        True,
        "the board or backend rejected the command; check the connection and "
        "the core's state (fcapz_status, fcapz_probe)",
    ),
    "internal": (False, "report this; it is a bug in fcapz-mcp"),
}


class UnknownToolError(LookupError):
    """A call for a tool this server does not publish."""


class McpWatchdogTimeout(TimeoutError):
    """The MCP watchdog gave up on a still-running RPC worker.

    Distinct from a plain ``TimeoutError`` delivered *through* the worker (an
    RPC-layer wait that expired but returned control cleanly): a watchdog
    timeout means the worker is or was abandoned, so callers that treat an
    RPC-side timeout as normal polling can re-raise this one instead.
    """


# JSON numbers are IEEE-754 doubles in most MCP clients (Claude Code and any
# other JS/TS host parse with `JSON.parse`), so integers above 2**53-1 are
# silently rounded. A 160-bit AXI-monitor sample would lose its low bits --
# exactly the awaddr/wdata/wstrb an agent is trying to read. Encode anything
# too wide as a hex string instead, and say so in the payload.
_JSON_SAFE_INT_MAX = (1 << 53) - 1
_WIDE_VALUE_KEYS = ("samples", "timestamps")


def _is_wide_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and (
        value > _JSON_SAFE_INT_MAX or value < -_JSON_SAFE_INT_MAX
    )


def _hex_int(value: int) -> str:
    return f"-0x{-value:x}" if value < 0 else f"0x{value:x}"


def _encode_wide_ints(obj: Any) -> tuple[Any, bool]:
    """Recursively hex-encode ints that exceed JSON's exact-integer range.

    Returns ``(converted, changed)``. Within a ``samples``/``timestamps`` list
    the encoding is all-or-nothing: if any entry is too wide every entry in
    that list is encoded, so an agent never has to handle a list that mixes
    ints and hex strings.
    """
    if isinstance(obj, dict):
        out: JsonDict = {}
        changed = False
        for key, value in obj.items():
            if key in _WIDE_VALUE_KEYS and isinstance(value, list):
                value, sub = _encode_value_list(value)
            else:
                value, sub = _encode_wide_ints(value)
            changed = changed or sub
            out[key] = value
        return out, changed
    if isinstance(obj, list):
        items = [_encode_wide_ints(item) for item in obj]
        changed = any(sub for _, sub in items)
        return [item for item, _ in items], changed
    if _is_wide_int(obj):
        return _hex_int(obj), True
    return obj, False


def _encode_value_list(entries: list[Any]) -> tuple[list[Any], bool]:
    """Hex-encode a samples/timestamps list uniformly if any value is too wide."""
    if not any(
        _is_wide_int(e.get("value")) for e in entries if isinstance(e, dict)
    ):
        return entries, False
    out = []
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("value"), int):
            entry = {**entry, "value": _hex_int(entry["value"])}
        out.append(entry)
    return out, True


class _CommandState:
    """Lifecycle of one hardware command, guarded by the session state lock."""

    PENDING = "pending"    # queued or running
    COMMITTED = "committed"  # finished and session state updated; reply posted
    ABANDONED = "abandoned"  # watchdog gave up; owner must recover, not commit
    RECONCILED = "reconciled"  # owner finished tearing the abandoned call down


@dataclass
class _HardwareCommand:
    """One RPC request plus the state commit that must be atomic with it.

    The commit runs on the owner thread while the command still holds the
    hardware, so a caller can never observe (or interleave with) a completed
    RPC whose session state has not been written yet.
    """

    req: JsonDict
    commit: Callable[..., Any]
    # Optional heavy derivation from the response (a capture's JSON snapshot),
    # run on the owner thread *before* the lock is taken. Its result is handed
    # to ``commit`` as a second argument.
    prepare: Callable[[JsonDict], Any] | None = None
    reply: "queue.Queue[tuple[bool, object]]" = field(
        default_factory=lambda: queue.Queue(maxsize=1)
    )
    done: threading.Event = field(default_factory=threading.Event)
    state: str = _CommandState.PENDING


@dataclass(frozen=True)
class _CaptureCache:
    """Immutable snapshot of the last capture, published by a single assignment.

    Every derived view — the JSON text, its UTF-8 bytes, the byte size, and the
    compact summary — is computed once at store time and never mutated. A reader
    that grabs one ``_capture_cache`` reference therefore sees a fully
    consistent set even if a new capture lands concurrently (FastMCP runs sync
    tools/resources in a thread pool, so stores and reads can interleave).
    """

    payload: JsonDict
    json_text: str
    json_bytes: bytes
    size_bytes: int
    summary: JsonDict


def _error_code(exc: BaseException) -> str:
    """Classify a failure into one of the codes callers can act on.

    The RPC layer is called in-process, so its exceptions arrive as
    themselves rather than as an ``{"ok": false}`` envelope. Both routes are
    classified here: an ordinary "not connected" must read the same whichever
    way it came, and must never be reported as an internal bug.
    """
    if isinstance(exc, PermissionError):
        return "not_permitted"
    if isinstance(exc, FileNotFoundError):
        return "not_found"
    if isinstance(exc, UnknownToolError):
        return "unknown_tool"
    if isinstance(exc, NotEnabledError):
        return "not_permitted"
    if isinstance(exc, NotConnectedError):
        return "not_connected"
    if isinstance(exc, McpWatchdogTimeout):
        return "watchdog_timeout"
    if isinstance(exc, CaptureNotReady):
        return "capture_not_ready"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, FcapzMcpError):
        if exc.code:
            return exc.code
        # An RPC refusal relayed as an envelope. "not connected" is the one
        # worth separating: the common first-call mistake, obvious remedy.
        if _reads_as_not_connected(exc):
            return "not_connected"
        return "hardware_error"
    if isinstance(exc, ValidationError):
        # Argument validation, raised by the schema before the tool ran.
        return "invalid_argument"
    if isinstance(exc, ValueError):
        return "invalid_argument"
    if isinstance(exc, (RpcError, ConnectionError, OSError)):
        # The board or the backend refused, or the link failed. Not a bug in
        # this server, and retrying after a reconnect can work.
        return "hardware_error"
    if _reads_as_not_connected(exc):
        return "not_connected"
    return "internal"


def _reads_as_not_connected(exc: BaseException) -> bool:
    """Last-resort match for a backend that reports it in prose only."""
    return "not connected" in str(exc).lower()


def _coded_error(exc: BaseException) -> Exception:
    """Re-render a failure as one machine-readable JSON object.

    A tool error reaches the agent as the exception's text and nothing else,
    so the code, whether a retry could help, and what to do instead all have
    to travel in it.
    """
    code = _error_code(exc)
    retryable, action = _ERROR_ACTIONS.get(code, _ERROR_ACTIONS["internal"])
    body: JsonDict = {
        "code": code,
        "message": str(exc),
        "retryable": retryable,
        "action": action,
    }
    detail = getattr(exc, "payload", None)
    if isinstance(detail, dict):
        rpc_error = detail.get("error")
        if rpc_error is not None:
            body["detail"] = rpc_error
    text = json.dumps(body, ensure_ascii=False, sort_keys=True)
    try:
        # Preserve the class where we can: callers (and tests) catch by type.
        coded = type(exc)(text)
    except Exception:  # noqa: BLE001
        # Not every exception takes a single message argument -- pydantic's
        # ValidationError does not. The body is what has to survive.
        coded = FcapzMcpError(text)
    # So the call_tool seam can tell an already-coded failure from one that
    # never reached a tool body, and pass the former through untouched.
    coded._fcapz_coded = body  # type: ignore[attr-defined]
    return coded


def _coded_body(exc: BaseException) -> JsonDict | None:
    """The coded body already attached somewhere in this exception's chain."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        body = getattr(cur, "_fcapz_coded", None)
        if isinstance(body, dict):
            return body
        cur = cur.__cause__ or cur.__context__
    return None


def _coded_call_failure(name: str, exc: BaseException) -> JsonDict:
    """One coded body for any failure of a tool call, however it arose.

    Two things can fail: the tool body, already coded by :func:`_coded`, and
    argument validation, which runs *before* the body and would otherwise
    reach the agent as pydantic prose with no code, no ``retryable`` and no
    remedy. Both end up here so a client can parse one shape unconditionally.
    """
    body = _coded_body(exc)
    if body is None:
        cause = exc.__cause__ or exc.__context__ or exc
        coded = _coded_error(cause)
        body = getattr(coded, "_fcapz_coded")
    return {**body, "tool": name}


def _coded(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Give a tool's failures a code and retry guidance."""

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def guarded_async(*args: Any, **kwargs: Any) -> Any:
            try:
                return await fn(*args, **kwargs)
            except Exception as exc:
                raise _coded_error(exc) from exc

        return guarded_async

    @functools.wraps(fn)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            raise _coded_error(exc) from exc

    return guarded


def _offloaded(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Run a blocking tool in a worker thread.

    FastMCP awaits a sync tool directly on the event loop, so every JTAG
    round trip froze the whole server -- a 300 s capture made it answer
    nothing at all, not even a status poll, for five minutes. Hardware access
    is still serialized by the owner thread; this only keeps the loop free to
    serve the calls that do not need hardware.
    """
    if inspect.iscoroutinefunction(fn):
        return fn

    @functools.wraps(fn)
    async def offloaded(*args: Any, **kwargs: Any) -> Any:
        import anyio.to_thread

        return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))

    return offloaded


async def _with_progress(ctx: Any, label: str, call: Callable[[], Any], total: float):
    """Run a blocking call, saying it is still running while it runs.

    There is no progress to report from inside a JTAG readout, so the honest
    measure is elapsed time against the timeout the caller set -- enough for a
    client to show that the server is alive and how much of the budget is
    gone.
    """
    import anyio

    outcome: dict[str, Any] = {}

    async with anyio.create_task_group() as tg:

        async def worker() -> None:
            try:
                outcome["value"] = await anyio.to_thread.run_sync(call)
            except BaseException as exc:  # noqa: BLE001 - re-raised below
                outcome["error"] = exc
            finally:
                tg.cancel_scope.cancel()

        async def ticker() -> None:
            started = time.monotonic()
            while True:
                await anyio.sleep(_PROGRESS_INTERVAL_SEC)
                elapsed = time.monotonic() - started
                try:
                    await ctx.report_progress(
                        min(elapsed, total),
                        total,
                        f"{label}: {elapsed:.0f}s elapsed of up to {total:.0f}s",
                    )
                except Exception:  # noqa: BLE001
                    # No progress token, or a client that will not take one.
                    # Saying so is optional; finishing the capture is not.
                    return

        tg.start_soon(worker)
        tg.start_soon(ticker)

    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


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
    last_eio_read: JsonDict | None = None
    last_rpc_schema_version: str | None = _SCHEMA_VERSION
    _capture_cache: "_CaptureCache | None" = field(default=None, init=False, repr=False)
    # One lock guards session state, the active-command slot and every command
    # state transition, so a commit and a watchdog giveup cannot interleave.
    _rpc_lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _active_rpc_cmd: str | None = field(default=None, init=False, repr=False)
    _poisoned: bool = field(default=False, init=False, repr=False)
    _owner: threading.Thread | None = field(default=None, init=False, repr=False)
    _command_q: "queue.Queue[_HardwareCommand | None]" = field(
        default_factory=queue.Queue, init=False, repr=False
    )

    # Derived from the schema the agent is shown, so the two cannot drift.
    _CAPTURE_CONFIG_KEYS = frozenset(CaptureConfigDict.__annotations__)

    @property
    def last_capture(self) -> JsonDict | None:
        """The last capture's raw payload, or None. Read-only view of the cache."""
        cache = self._capture_cache
        return cache.payload if cache is not None else None

    def _worker_join_timeout(self, req: JsonDict) -> float:
        """Seconds to let the RPC worker run before the watchdog declares a timeout.

        Wait-bearing commands (``capture``/``capture_wait``/``uart_recv``) carry
        their own ``timeout``; the watchdog must outlast it. Otherwise a caller
        that legitimately waits longer than ``rpc_timeout_sec`` for a trigger
        would trip the watchdog, orphan the still-running worker, and — because
        the real RPC layer has no ``cancel_active`` — wedge the whole session
        behind the "previous call still running" guard until it self-heals.

        The extra headroom on top of the caller's own ``timeout`` is a full
        ``rpc_timeout_sec`` window, not a small constant: the RPC call also has
        to *read back* the samples after the trigger fires, and on the slow
        transports (quartus_stp per-register fallback, OpenOCD) a deep capture's
        readback can take many seconds. A fixed margin would trip mid-readback.
        """
        base = self.capabilities.rpc_timeout_sec
        wait = req.get("timeout")
        if wait is None:
            return base
        try:
            wait = float(wait)
        except (TypeError, ValueError):
            return base
        return max(base, wait + base)

    # ---- single hardware owner ---------------------------------------
    #
    # The JTAG transport is strictly single-threaded, and the RPC call plus the
    # session-state write that follows it must be one indivisible step. Both
    # are therefore done on one long-lived owner thread fed by a queue, rather
    # than on a thread spawned per call: a caller can no longer slip between a
    # finished RPC and its commit (losing a close, or publishing an older
    # capture over a newer one), and an abandoned command can be reconciled
    # instead of silently leaving the wrapper's view of the board wrong.

    def _ensure_owner(self) -> None:
        """Start the owner thread on first use. Caller holds ``_rpc_lock``."""
        if self._owner is not None and self._owner.is_alive():
            return
        self._owner = threading.Thread(
            target=self._owner_loop, name="fcapz-mcp-hardware", daemon=True
        )
        self._owner.start()

    def _owner_loop(self) -> None:
        while True:
            cmd = self._command_q.get()
            if cmd is None:  # shutdown sentinel
                return
            self._run_command(cmd)

    def _run_command(self, cmd: _HardwareCommand) -> None:
        try:
            raw: object = self.rpc.handle(cmd.req)
            failure: BaseException | None = None
        except BaseException as exc:  # noqa: BLE001 - relayed to the caller
            raw, failure = None, exc

        # Response checking and any heavy derivation happen off the lock: they
        # read only this response, and holding the hardware lock through a
        # megabyte of json.dumps would stall fcapz_status and delay a
        # concurrent caller's "busy" reply for exactly as long.
        checked: JsonDict | None = None
        prepared: Any = None
        if failure is None:
            try:
                checked = self._ok_response(raw)  # type: ignore[arg-type]
                if cmd.prepare is not None:
                    prepared = cmd.prepare(checked)
            except BaseException as exc:  # noqa: BLE001
                failure = exc

        with self._rpc_lock:
            if cmd.state == _CommandState.ABANDONED:
                # The watchdog already gave up and told the caller so. Do not
                # commit: the session must be reconciled, not quietly advanced.
                recover = True
            else:
                recover = False
                if failure is not None:
                    outcome: tuple[bool, object] = (False, failure)
                else:
                    try:
                        outcome = (
                            True,
                            cmd.commit(checked, prepared)
                            if cmd.prepare is not None
                            else cmd.commit(checked),
                        )
                    except BaseException as exc:  # noqa: BLE001
                        outcome = (False, exc)
                cmd.state = _CommandState.COMMITTED
                cmd.reply.put(outcome)
                self._active_rpc_cmd = None

        if recover:
            self._recover_after_abandoned(cmd)
        cmd.done.set()

    def _recover_after_abandoned(self, cmd: _HardwareCommand) -> None:
        """Reconcile after a command the caller stopped waiting for.

        The RPC layer may have connected, closed, or captured in the meantime,
        so the only safe assumption is that nothing is where the wrapper left
        it. Tear the board session down for real, wipe wrapper state, and only
        then accept new commands.
        """
        # Teardown runs on this thread, so a transport that blocks here would
        # wedge the owner for good. Give the abort hook a second chance from a
        # timer thread rather than trusting the close to return on its own.
        nudge = self._recovery_nudge()
        try:
            self.rpc.handle({"cmd": "close"})
        except Exception as exc:  # noqa: BLE001 - best effort teardown
            self._emit_rpc_error("recover_teardown", "close", exc)
        finally:
            if nudge is not None:
                nudge.cancel()
        with self._rpc_lock:
            # Ordering matters: whichever of this and _poison() takes the lock
            # first, the session ends up usable. Taking it second clears the
            # flag; taking it first marks the command reconciled so _poison()
            # knows not to set one.
            self._reset_session_state()
            self._active_rpc_cmd = None
            self._poisoned = False
            cmd.state = _CommandState.RECONCILED

    def _recovery_nudge(self) -> "threading.Timer | None":
        """Arm a delayed second abort in case the teardown close hangs."""
        cancel = getattr(self.rpc, "cancel_active", None)
        if not callable(cancel):
            return None

        def _again() -> None:
            try:
                cancel()
            except Exception as exc:  # noqa: BLE001
                self._emit_rpc_error("recover_nudge", "close", exc)

        timer = threading.Timer(self.capabilities.rpc_cancel_grace_sec, _again)
        timer.daemon = True
        timer.start()
        return timer

    def _rpc_call(
        self,
        req: JsonDict,
        commit: Callable[..., Any] | None = None,
        prepare: Callable[[JsonDict], Any] | None = None,
    ) -> Any:
        """Run one hardware command on the owner thread and commit it atomically.

        ``commit`` runs on the owner thread with the hardware still held, and
        its return value is what this call returns (default: the response).
        ``prepare`` runs first, without the lock, for work too expensive to do
        under it; its result becomes ``commit``'s second argument.
        """
        cmd = _HardwareCommand(
            req=req,
            commit=commit or (lambda response: response),
            prepare=prepare,
        )
        name = str(req.get("cmd"))
        with self._rpc_lock:
            if self._poisoned:
                raise FcapzMcpError(
                    f"fcapz session is recovering from an abandoned "
                    f"{self._active_rpc_cmd!r} call and is not accepting hardware "
                    "commands; retry shortly (fcapz_status shows session_state)",
                    code="session_recovering",
                )
            if self._active_rpc_cmd is not None:
                raise FcapzMcpError(
                    f"fcapz is busy running {self._active_rpc_cmd!r}; the JTAG "
                    "transport takes one command at a time — wait for it to "
                    "finish (fcapz_status shows session_state)",
                    code="busy",
                )
            self._active_rpc_cmd = name
            self._ensure_owner()
        self._command_q.put(cmd)

        timeout = self._worker_join_timeout(req)
        try:
            ok, value = cmd.reply.get(timeout=timeout)
        except queue.Empty:
            return self._handle_watchdog_timeout(cmd, name, timeout)
        if not ok:
            raise value  # type: ignore[misc]
        return value

    def _handle_watchdog_timeout(
        self, cmd: _HardwareCommand, name: str, timeout: float
    ) -> Any:
        """Decide what to do about a command that outran its watchdog."""
        cancel = getattr(self.rpc, "cancel_active", None)
        if callable(cancel):
            # A transport that can abort: stop it, then give it the grace
            # window to unwind. The result is not trustworthy either way.
            with self._rpc_lock:
                if cmd.state == _CommandState.PENDING:
                    cmd.state = _CommandState.ABANDONED
            if cmd.state == _CommandState.ABANDONED:
                try:
                    cancel()
                except Exception as exc:  # noqa: BLE001
                    self._emit_rpc_error("cancel_active", name, exc)
                cmd.done.wait(self.capabilities.rpc_cancel_grace_sec)
                if self._reconciled(cmd):
                    raise McpWatchdogTimeout(
                        f"fcapz RPC call {name!r} was cancelled after {timeout:g}s; "
                        "the board session was torn down — reconnect before retrying"
                    )
                self._poison(cmd, name, timeout)
            # It committed while we were deciding: fall through and take it.
        else:
            # No abort hook. The call may simply be a slow readback finishing
            # late, so allow the grace window and salvage a real result rather
            # than throwing away a completed capture.
            try:
                ok, value = cmd.reply.get(timeout=self.capabilities.rpc_cancel_grace_sec)
            except queue.Empty:
                with self._rpc_lock:
                    if cmd.state == _CommandState.PENDING:
                        cmd.state = _CommandState.ABANDONED
                        self._poison(cmd, name, timeout)
            else:
                if not ok:
                    raise value  # type: ignore[misc]
                return value
        ok, value = cmd.reply.get_nowait()
        if not ok:
            raise value  # type: ignore[misc]
        return value

    def _reconciled(self, cmd: _HardwareCommand) -> bool:
        with self._rpc_lock:
            return cmd.state == _CommandState.RECONCILED

    def _poison(self, cmd: _HardwareCommand, name: str, timeout: float) -> None:
        """Refuse further hardware commands until the owner has reconciled.

        ``done.wait()`` can miss its deadline by a hair while recovery is
        finishing, so the flag is only raised for a command the owner has not
        already reconciled — otherwise nothing would ever clear it again and
        the session would refuse hardware for the rest of its life.
        """
        with self._rpc_lock:
            if cmd.state == _CommandState.RECONCILED:
                raise McpWatchdogTimeout(
                    f"fcapz RPC call {name!r} was cancelled after {timeout:g}s; "
                    "the board session was torn down — reconnect before retrying"
                )
            self._poisoned = True
        raise McpWatchdogTimeout(
            f"fcapz RPC call {name!r} timed out after {timeout:g}s and is still "
            "running; the session will be torn down and reset when it returns "
            "(fcapz_status shows session_state) — reconnect after that"
        )

    def _ok_response(self, response: JsonDict) -> JsonDict:
        if not response.get("ok", False):
            error = response.get("error", response)
            if isinstance(error, str):
                message = error
            elif isinstance(error, dict) and isinstance(error.get("message"), str):
                # Prefer the sentence over a dump of the whole error object;
                # the object still travels as `detail` (see _coded_error).
                message = error["message"]
            else:
                message = json.dumps(error, sort_keys=True)
            raise FcapzMcpError(message, payload=response)
        if "schema_version" in response:
            self.last_rpc_schema_version = str(response["schema_version"])
        return response

    @staticmethod
    def _emit_rpc_error(step: str, cmd: str, exc: BaseException) -> None:
        payload = {
            "event": "rpc_cancel_error",
            "errors": [
                {
                    "step": step,
                    "cmd": cmd,
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                }
            ],
        }
        print(json.dumps(payload, separators=(",", ":")), file=sys.stderr)

    # ---- commits ------------------------------------------------------
    # Each runs on the owner thread, under the session lock, while the command
    # still holds the hardware. Keep them small and non-blocking.

    def _commit_connected(self, response: JsonDict) -> JsonDict:
        self.connected = True
        return response

    def _commit_closed(self, response: JsonDict) -> JsonDict:
        self._reset_session_state()
        return response

    def _commit_probe(self, response: JsonDict) -> JsonDict:
        self.last_probe = dict(response.get("probe", {}))
        return response

    def _commit_eio_connected(self, response: JsonDict) -> JsonDict:
        self.eio_connected = True
        return response

    def _commit_eio_closed(self, response: JsonDict) -> JsonDict:
        self.eio_connected = False
        self.last_eio_read = None
        return response

    def _commit_eio_read(self, response: JsonDict) -> JsonDict:
        response = dict(response)
        value = response.get("value")
        if _is_wide_int(value):
            # RPC sends both `value` (a JSON number) and `value_hex`. Past 53
            # bits a JS client rounds the number, so the same register would
            # read two different ways in one response. Hand over the exact
            # one and say so.
            response["value"] = _hex_int(value)
            response["value_encoding"] = "hex"
        self.last_eio_read = dict(response)
        return response

    def _commit_axi_connected(self, response: JsonDict) -> JsonDict:
        self.axi_connected = True
        return response

    def _commit_axi_closed(self, response: JsonDict) -> JsonDict:
        self.axi_connected = False
        return response

    def _commit_uart_connected(self, response: JsonDict) -> JsonDict:
        self.uart_connected = True
        return response

    def _commit_uart_closed(self, response: JsonDict) -> JsonDict:
        self.uart_connected = False
        return response

    def _reset_session_state_after_cancel(self) -> None:
        self._reset_session_state()

    def _reset_session_state(self) -> None:
        """Drop every connection flag and cached readout in one place."""
        self.connected = False
        self.eio_connected = False
        self.axi_connected = False
        self.uart_connected = False
        self.last_probe = None
        self._capture_cache = None
        self.last_eio_read = None

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
        if backend == "usb_blaster":
            return 0
        return 3

    @staticmethod
    def _reject_fields(backend: str, fields: dict[str, object | None]) -> None:
        present = sorted(name for name, value in fields.items() if value is not None)
        if present:
            raise ValueError(
                f"{', '.join(present)} not supported for backend {backend!r}"
            )

    @staticmethod
    def _validated_port(port: int) -> int:
        port_i = int(port)
        if not 1 <= port_i <= 65535:
            raise ValueError(f"port must be in 1..65535, got {port_i}")
        return port_i

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
    ) -> None:
        if backend in ("hw_server", "openocd"):
            self._reject_fields(
                backend,
                {
                    "hardware": hardware,
                    "quartus_stp": quartus_stp,
                },
            )
            req["host"] = self._validated_host(host)
            req["tap"] = tap or self._default_tap(backend)
            if port is not None:
                req["port"] = self._validated_port(port)
            return

        if backend == "usb_blaster":
            self._reject_fields(
                backend,
                {
                    "tap": tap,
                    "port": port,
                    "host": host,
                },
            )
            if hardware is not None:
                req["hardware"] = hardware
            if quartus_stp is not None:
                # quartus_stp names a host executable that gets spawned
                # (transport -> subprocess). Letting an agent pick an arbitrary
                # path would sidestep the whole capability model, including
                # --read-only. Require the same opt-in as programming; the
                # operator-configured default is still used when omitted.
                if not self.capabilities.allow_program:
                    raise PermissionError(
                        "naming a quartus_stp executable is disabled; restart "
                        "fcapz-mcp with --allow-program to allow it, or omit "
                        "quartus_stp to use the server's configured toolchain"
                    )
                req["quartus_stp"] = quartus_stp
            return

        raise ValueError(f"unknown backend: {backend}")

    def connect(
        self,
        *,
        backend: Backend = "hw_server",
        host: str | None = None,
        port: int | None = None,
        tap: str | None = None,
        chain: int | None = None,
        program: str | None = None,
        single_chain_burst: bool = True,
        hardware: str | None = None,
        quartus_stp: str | None = None,
    ) -> JsonDict:
        program_path = self._validated_program_path(program, backend=backend)
        if self.connected:
            self.close()
        req: JsonDict = {
            "cmd": "connect",
            "backend": backend,
        }
        if chain is not None:
            req["chain"] = int(chain)
        self._add_connection_fields(
            req,
            backend=backend,
            host=host,
            port=port,
            tap=tap,
            hardware=hardware,
            quartus_stp=quartus_stp,
        )
        if backend == "hw_server":
            req["single_chain_burst"] = single_chain_burst
        elif single_chain_burst is not True:
            raise ValueError(f"single_chain_burst not supported for backend {backend!r}")
        if program_path is not None:
            req["program"] = str(program_path)
        return self._rpc_call(req, commit=self._commit_connected)

    _LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

    def _validated_host(self, host: str | None) -> str:
        """Confine backend connections to loopback unless told otherwise.

        `host` reaches a network client (hw_server / OpenOCD), so without this
        an agent could point the server at any such daemon on the network.
        """
        if not host:
            return "127.0.0.1"
        host = str(host)
        if host in self._LOOPBACK_HOSTS or host in self.capabilities.allowed_hosts:
            return host
        allowed = ", ".join(sorted(self.capabilities.allowed_hosts))
        raise PermissionError(
            f"host {host!r} is not allowed; this MCP server connects to "
            "loopback only"
            + (f" plus: {allowed}" if allowed else "")
            + " (start it with --allow-host HOST to permit another)"
        )

    def _confined_probe_path(self, probe_file: object) -> Path:
        """Keep `probe_file` from becoming an arbitrary server-side file read.

        Require an explicit --probe-root, and keep the path inside it.
        """
        path = Path(str(probe_file)).expanduser()
        root = self.capabilities.probe_root
        if root is None:
            raise PermissionError(
                "probe_file reads a file on the MCP server's filesystem and is "
                "disabled; start fcapz-mcp with --probe-root DIR to allow it, "
                "or pass the probe definitions inline via `probes`"
            )
        root_resolved = root.expanduser().resolve()
        if not path.is_absolute():
            path = root_resolved / path
        resolved = path.resolve()
        if resolved != root_resolved and root_resolved not in resolved.parents:
            raise PermissionError(
                f"probe file {resolved} is outside allowed root {root_resolved}"
            )
        if not resolved.is_file():
            raise ValueError(f"probe file {resolved} does not exist")
        return resolved

    def _inlined_probe_file(self, config: JsonDict) -> JsonDict:
        """Replace `probe_file` with the probe map it names.

        Handing the RPC layer a path meant the file was checked here and
        opened there, a queue hop and a thread handoff later: anyone able to
        write inside --probe-root could swap the file, or an ancestor, in
        between and have different content loaded than was approved. Reading
        it once, here, removes the second open altogether.
        """
        if config.get("probes") is not None:
            raise ValueError("probes and probe_file are mutually exclusive")
        resolved = self._confined_probe_path(config["probe_file"])
        parsed = load_probe_text(self._read_confined(resolved), source=resolved)

        inlined = {k: v for k, v in config.items() if k != "probe_file"}
        inlined["probes"] = [
            {"name": spec.name, "width": spec.width, "lsb": spec.lsb}
            for spec in parsed.probes
        ]
        # The file's values are defaults the caller may override, which is
        # what RPC did when it loaded the file itself.
        if parsed.sample_width is not None and "sample_width" not in config:
            inlined["sample_width"] = parsed.sample_width
        if parsed.sample_clock_hz is not None and "sample_clock_hz" not in config:
            inlined["sample_clock_hz"] = parsed.sample_clock_hz
        return inlined

    @staticmethod
    def _read_confined(resolved: Path) -> str:
        """Read an already-approved path, and check it stayed the same file.

        ``resolved`` carries no symlink components as of the check above, so a
        swap has to land in the microseconds before this open. Comparing the
        opened file's identity against the path afterwards catches that.
        """
        with open(resolved, encoding="utf-8") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise ValueError(f"probe file {resolved} is not a regular file")
            text = handle.read()
        after = os.stat(resolved)
        if (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
            raise PermissionError(
                f"probe file {resolved} was replaced while it was being read; "
                "refusing to use it"
            )
        return text

    def _validated_capture_config(self, config: JsonDict | None) -> JsonDict | None:
        if not config:
            return config
        unknown = sorted(set(config) - self._CAPTURE_CONFIG_KEYS)
        if unknown:
            raise ValueError(f"unsupported capture config field(s): {', '.join(unknown)}")
        if config.get("probe_file") is not None:
            config = self._inlined_probe_file(config)
        return config

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
        """Close the whole board session: ELA plus any EIO/AXI/UART controller.

        RPC ``close`` is ``_close_all()`` — it tears down every controller, not
        just the analyzer. So this must run whenever *any* subsystem is open
        (not only when the ELA is), and must clear every wrapper flag
        afterwards; otherwise the session reports subsystems as connected whose
        hardware handle the RPC layer has already released, or silently leaves
        a side-only EIO/AXI/UART session open on the board.
        """
        if self._closed_locally(
            *self._SUBSYSTEM_FLAGS, reset=self._reset_session_state
        ):
            return {"ok": True}
        try:
            return self._rpc_call({"cmd": "close"}, commit=self._commit_closed)
        except FcapzMcpError:
            # RPC close releases every controller even when it reports a
            # failure part way through (each teardown is individually
            # guarded), so the wrapper must not keep advertising stale
            # connections on the error path either.
            with self._rpc_lock:
                self._reset_session_state()
            raise

    def _closed_locally(self, *flags: str, reset: Callable[[], None]) -> bool:
        """Settle a close with no RPC when nothing is open — atomically.

        The flags only describe reality while the owner is idle. With a
        command in flight they describe the *pre-command* world — a connect
        that has not committed yet still reads as disconnected — so a close
        must not conclude it has nothing to do; returning False sends it to
        ``_rpc_call``, which arbitrates (busy) instead of silently dropping
        it.

        The decision and ``reset`` run under one hold of the lock. Splitting
        them let a connect commit in between, leaving the board connected and
        the wrapper reporting otherwise — a state no serial ordering of the
        two calls could produce.
        """
        with self._rpc_lock:
            if self._active_rpc_cmd is not None:
                return False
            if any(getattr(self, flag) for flag in flags):
                return False
            reset()
            return True

    _SUBSYSTEM_FLAGS = (
        "connected",
        "eio_connected",
        "axi_connected",
        "uart_connected",
    )

    def drop_last_capture(self) -> JsonDict:
        # Captures may contain large sample payloads. Probe and EIO caches are small
        # enough to retain until overwritten or closed.
        had_capture = self._capture_cache is not None
        self._capture_cache = None
        return {"ok": True, "had_capture": had_capture}

    def get_last_capture(self, max_bytes: int | None = _DEFAULT_FULL_CAPTURE_MAX_BYTES) -> JsonDict:
        cache = self._capture_cache  # one consistent snapshot for this call
        if cache is None:
            return {"available": False}
        if max_bytes is not None and int(max_bytes) < 0:
            raise ValueError("max_bytes must be >= 0 or null")
        size_bytes = cache.size_bytes
        if max_bytes is not None and size_bytes > int(max_bytes):
            return {
                "available": True,
                "truncated": True,
                "size_bytes": size_bytes,
                "max_bytes": int(max_bytes),
                "summary": self._bounded_capture_summary(cache.summary),
                "message": (
                    "cached capture is larger than max_bytes; use "
                    "fcapz_get_last_capture_chunk for bounded retrieval"
                ),
            }
        response = dict(cache.payload)
        response.setdefault("available", True)
        response.setdefault("truncated", False)
        response.setdefault("size_bytes", size_bytes)
        return response

    _AXI_MAX_PAGE = 256
    _SAMPLES_MAX_PAGE = 512

    @staticmethod
    def _capture_results(payload: JsonDict) -> list[JsonDict]:
        """Every result block in a capture, in order.

        A plain capture has one; a segmented capture has one per segment.
        Returning only the first would silently hide the rest.
        """
        result = payload.get("result")
        if not isinstance(result, dict):
            return []
        if isinstance(result.get("samples"), list):
            return [result]
        segments = result.get("segments")
        if isinstance(segments, list):
            return [
                seg for seg in segments
                if isinstance(seg, dict) and isinstance(seg.get("samples"), list)
            ]
        return []

    @staticmethod
    def _as_int(value: Any) -> int | None:
        """Sample values are ints, or hex strings when too wide for JSON."""
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value, 16 if value.lower().startswith(("0x", "-0x")) else 10)
            except ValueError:
                return None
        return None

    def capture_samples(
        self,
        *,
        start: int = 0,
        count: int = 128,
        fields: list[str] | None = None,
        radix: SampleRadix = "hex",
    ) -> SamplePage:
        """Page the cached capture's samples as whole, self-contained records.

        Unlike the byte-chunked payload, each page is valid JSON on its own
        and carries the context needed to read it (total, trigger_index).
        """
        if radix not in ("hex", "int"):
            raise ValueError(f"radix must be 'hex' or 'int'; got {radix!r}")
        cache = self._capture_cache  # one consistent snapshot for this call
        if cache is None:
            return self._empty_sample_page(radix, None)
        results = self._capture_results(cache.payload)
        if not results:
            return self._empty_sample_page(
                radix,
                "the cached capture has no JSON sample list; capture with "
                'format="json" to page samples',
            )
        start_i, count_i = int(start), int(count)
        if start_i < 0:
            raise ValueError("start must be >= 0")
        if count_i <= 0:
            raise ValueError("count must be > 0")
        count_i = min(count_i, self._SAMPLES_MAX_PAGE)

        probes = self._selected_probes(cache.payload, fields)
        multi = len(results) > 1
        entries: list[tuple[int | None, Any]] = []
        for position, result in enumerate(results):
            segment = result.get("segment", position) if multi else None
            entries.extend((segment, entry) for entry in result["samples"])

        page = entries[start_i : start_i + count_i]
        next_start = start_i + len(page)
        rendered = []
        for segment, entry in page:
            sample = self._render_sample(entry, probes, radix)
            if segment is not None:
                sample["segment"] = segment
            rendered.append(sample)

        first = results[0]
        out: SamplePage = {
            "available": True,
            "total": len(entries),
            "start": start_i,
            "count": len(page),
            "next_start": next_start if next_start < len(entries) else None,
            "radix": radix,
            "sample_width": first.get("sample_width"),
            # Index of the trigger sample, or null when it cannot be trusted.
            # Meaningless once segments are concatenated, so withheld there.
            "trigger_index": (
                None if multi else self._trigger_index(first, len(entries))
            ),
            "samples": rendered,
            "reason": None,
            "segments": len(results) if multi else None,
            "fields": [name for name, _, _ in probes] if probes is not None else None,
        }
        return out

    @staticmethod
    def _empty_sample_page(radix: SampleRadix, reason: str | None) -> SamplePage:
        """A page with nothing in it, in the same shape as a full one."""
        return {
            "available": False,
            "reason": reason,
            "total": 0,
            "start": 0,
            "count": 0,
            "next_start": None,
            "radix": radix,
            "sample_width": None,
            "trigger_index": None,
            "samples": [],
            "segments": None,
            "fields": None,
        }

    @staticmethod
    def _trigger_index(result: JsonDict, sample_count: int) -> int | None:
        """Index of the trigger sample, or None when the layout is unknown.

        The trigger sits after the pretrigger samples — but only in a
        full-length capture. The analyzer takes the real length from the
        hardware CAPTURE_LEN register, which can come back short (a truncated
        capture, storage qualification dropping samples), and then the
        pretrigger count no longer locates the trigger. Return None rather
        than a number that points at the wrong sample.
        """
        pre = result.get("pretrigger")
        post = result.get("posttrigger")
        if not isinstance(pre, int) or not isinstance(post, int):
            return None
        if sample_count != pre + post + 1:
            return None
        return pre

    @staticmethod
    def _capture_probe_map(payload: JsonDict) -> list[Any]:
        """The capture's probe map, plain or segmented.

        A segmented capture has no top-level `probes`: RPC attaches one map
        per segment (they all come from the same config). Reading only the
        top level made named fields vanish on exactly the captures that need
        paging most.
        """
        probes = payload.get("probes")
        if isinstance(probes, list) and probes:
            return probes
        for segment in payload.get("segments") or []:
            if isinstance(segment, dict):
                probes = segment.get("probes")
                if isinstance(probes, list) and probes:
                    return probes
        return []

    def _selected_probes(
        self, payload: JsonDict, fields: list[str] | None
    ) -> list[tuple[str, int, int]] | None:
        """Resolve requested field names against the capture's probe map."""
        if fields is not None and not fields:
            # Explicitly empty: the caller wants the packed value, not fields.
            return None
        available = self._capture_probe_map(payload)
        if not available:
            if fields:
                raise ValueError(
                    "this capture carries no probe map, so named fields are "
                    "unavailable; omit `fields` to read raw sample values"
                )
            return None
        specs = {
            str(p["name"]): (int(p["lsb"]), int(p["width"]))
            for p in available
            if isinstance(p, dict) and {"name", "lsb", "width"} <= set(p)
        }
        names = list(fields) if fields else list(specs)
        unknown = [n for n in names if n not in specs]
        if unknown:
            raise ValueError(
                f"unknown field(s): {', '.join(sorted(unknown))}; "
                f"this capture has {', '.join(sorted(specs))}"
            )
        return [(n, specs[n][0], specs[n][1]) for n in names]

    def _render_sample(
        self, entry: Any, probes: list[tuple[str, int, int]] | None, radix: str
    ) -> JsonDict:
        if not isinstance(entry, dict):
            return {"value": entry}
        value = self._as_int(entry.get("value"))
        out: JsonDict = {"index": entry.get("index")}
        if value is None:
            out["value"] = entry.get("value")
            return out
        if probes is None:
            out["value"] = self._fmt(value, radix)
            return out
        for name, lsb, width in probes:
            out[name] = self._fmt((value >> lsb) & ((1 << width) - 1), radix)
        return out

    @staticmethod
    def _fmt(value: int, radix: str) -> Any:
        # Wide values always go out as hex: a JSON number would round.
        if radix == "int" and not _is_wide_int(value):
            return value
        return _hex_int(value)

    def axi_transactions(
        self,
        *,
        start: int = 0,
        count: int = 64,
        only_anomalies: bool = False,
        kind: TransactionKind | None = None,
    ) -> AxiTransactionPage:
        """Page the decoded AXI transactions of the cached capture.

        Returns whole transactions, so every page is valid on its own — unlike
        the byte-chunked raw payload, which has to be concatenated before it
        parses.

        Read `pairing` on every page before trusting an address. AXI4-Lite has
        no transaction IDs, so responses are matched to requests in order;
        that is only right if nothing was already outstanding when the window
        opened, which a finite trace cannot prove. `only_anomalies` keeps the
        transactions the bus got wrong (an error response, a misaligned
        address) -- not the ones clipped by the window's edges, which are
        flagged but legal.
        """
        cache = self._capture_cache  # one consistent snapshot for this call
        if cache is None:
            return self._empty_axi_page(None)
        sections = self._axi_sections(cache.payload)
        if not sections:
            return self._empty_axi_page(
                "the cached capture carries no AXI decode; capture with an "
                "AXI monitor probe map (fcapz_list_cores shows the monitor)"
            )
        if kind not in (None, "read", "write"):
            raise ValueError(f"kind must be 'read' or 'write'; got {kind!r}")
        start_i, count_i = int(start), int(count)
        if start_i < 0:
            raise ValueError("start must be >= 0")
        if count_i <= 0:
            raise ValueError("count must be > 0")
        count_i = min(count_i, self._AXI_MAX_PAGE)

        selected: list[JsonDict] = []
        for segment, section in sections:
            for txn in section.get("transactions") or []:
                if only_anomalies and not FAULT_FLAGS.intersection(
                    txn.get("flags") or ()
                ):
                    continue
                if kind is not None and txn.get("kind") != kind:
                    continue
                if segment is not None:
                    txn = {**txn, "segment": segment}
                selected.append(txn)

        page = selected[start_i : start_i + count_i]
        next_start = start_i + len(page)
        return {
            "available": True,
            "reason": None,
            "total": len(selected),
            "start": start_i,
            "count": len(page),
            "next_start": next_start if next_start < len(selected) else None,
            "filters": {"only_anomalies": only_anomalies, "kind": kind},
            "pairing": self._merged_pairing(sections),
            "sampling": self._merged_sampling(sections),
            "transactions": page,
        }

    @staticmethod
    def _merged_pairing(
        sections: list[tuple[int | None, JsonDict]],
    ) -> dict[str, Any]:
        """The pairing caveat for a page, across every segment it drew from."""
        observed: set[str] = set()
        for _, section in sections:
            pairing = section.get("pairing")
            if isinstance(pairing, dict):
                observed.update(pairing.get("pre_window_traffic_observed") or ())
        return {
            "method": "in-order",
            "assumes": PAIRING_ASSUMPTION,
            "pre_window_traffic_observed": sorted(observed),
            "pre_window_traffic_proven": bool(observed),
        }

    @staticmethod
    def _merged_sampling(
        sections: list[tuple[int | None, JsonDict]],
    ) -> dict[str, Any] | None:
        for _, section in sections:
            sampling = section.get("sampling")
            if isinstance(sampling, dict):
                return dict(sampling)
        return None

    @staticmethod
    def _empty_axi_page(reason: str | None) -> AxiTransactionPage:
        """A page with nothing in it, in the same shape as a full one."""
        return {
            "available": False,
            "reason": reason,
            "total": 0,
            "start": 0,
            "count": 0,
            "next_start": None,
            "filters": None,
            "pairing": None,
            "sampling": None,
            "transactions": [],
        }

    def get_last_capture_chunk(
        self,
        *,
        offset: int = 0,
        max_bytes: int = _DEFAULT_CAPTURE_CHUNK_BYTES,
    ) -> CaptureChunk:
        cache = self._capture_cache  # one consistent snapshot for this call
        if cache is None:
            return {
                "available": False,
                "reason": "no capture is cached",
                "encoding": None,
                "offset": 0,
                "max_bytes": None,
                "size_bytes": 0,
                "chunk": "",
                "next_offset": None,
                # True so a paging loop stops rather than retrying forever.
                "eof": True,
            }
        offset_i = int(offset)
        max_bytes_i = int(max_bytes)
        if offset_i < 0:
            raise ValueError("offset must be >= 0")
        if max_bytes_i <= 0:
            raise ValueError("max_bytes must be > 0")
        payload_bytes = cache.json_bytes
        size_bytes = cache.size_bytes
        start = min(offset_i, size_bytes)
        if start < size_bytes and not self._is_utf8_start_byte(payload_bytes[start]):
            raise ValueError("offset must point to a UTF-8 character boundary")
        end = min(size_bytes, start + max_bytes_i)
        while end > start:
            try:
                chunk = payload_bytes[start:end].decode("utf-8")
                break
            except UnicodeDecodeError:
                end -= 1
        else:
            # No whole character fit in the window. Returning an empty chunk
            # with next_offset == offset would loop a caller forever, so name
            # the real requirement instead (a UTF-8 character is <= 4 bytes).
            raise ValueError(
                f"max_bytes={max_bytes_i} is too small for the character at "
                f"offset {start}; use max_bytes >= 4"
            )
        return {
            "available": True,
            "reason": None,
            "encoding": "json-utf8",
            "offset": start,
            "max_bytes": max_bytes_i,
            "size_bytes": size_bytes,
            "chunk": chunk,
            "next_offset": None if end >= size_bytes else end,
            "eof": end >= size_bytes,
        }

    def probe(self) -> JsonDict:
        return self._rpc_call({"cmd": "probe"}, commit=self._commit_probe)

    @staticmethod
    def _validated_capture_format(fmt: str) -> str:
        if fmt not in ("json", "csv", "vcd"):
            raise ValueError(f"format must be one of json, csv, vcd; got {fmt!r}")
        return fmt

    @staticmethod
    def _validated_wait_timeout(timeout: float) -> float:
        # The RPC layer clamps waits at _MAX_WAIT_SEC and would otherwise raise a
        # generic "did not complete" long before a large caller value elapsed.
        # Reject up front so the failure names the real ceiling.
        seconds = float(timeout)
        # NaN slips past every comparison below and then makes Queue.get()
        # busy-wait forever instead of expiring, so reject it explicitly.
        if not math.isfinite(seconds):
            raise ValueError(f"timeout must be a finite number, got {timeout!r}")
        if seconds < 0:
            raise ValueError(f"timeout must be >= 0, got {seconds:g}")
        if seconds > _MAX_WAIT_SEC:
            raise ValueError(
                f"timeout must be <= {_MAX_WAIT_SEC:g}s (the RPC layer's cap), "
                f"got {seconds:g}"
            )
        return seconds

    @classmethod
    def _prepare_capture(cls, response: JsonDict) -> _CaptureCache:
        """Build the capture snapshot. Expensive, and needs no lock.

        Runs on the owner thread before the hardware lock is taken, so a
        multi-megabyte capture does not serialize with everyone else's status
        polls or delay a concurrent caller's "busy" reply.
        """
        # Make wide sample values survive a JS client's JSON.parse before the
        # payload is serialized or cached (see _encode_wide_ints).
        response, encoded = _encode_wide_ints(response)
        if encoded:
            response["value_encoding"] = "hex"
        json_text = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
        json_bytes = json_text.encode("utf-8")
        return _CaptureCache(
            payload=response,
            json_text=json_text,
            json_bytes=json_bytes,
            size_bytes=len(json_bytes),
            summary=cls._capture_summary(response),
        )

    def _commit_capture(self, _response: JsonDict, cache: _CaptureCache) -> JsonDict:
        """Publish a prepared snapshot with one assignment (see _CaptureCache)."""
        self._capture_cache = cache
        return dict(cache.summary)

    def _store_capture(self, response: JsonDict) -> JsonDict:
        """Prepare and publish in one step, for callers outside the owner."""
        return self._commit_capture(response, self._prepare_capture(response))

    def capture(
        self,
        *,
        config: CaptureConfigDict | None = None,
        timeout: float = 10.0,
        fmt: str = "json",
        include_event_summary: bool = False,
        immediate: bool = False,
        segments: bool = False,
    ) -> JsonDict:
        if not self.capabilities.allow_capture:
            raise PermissionError("capture tools are disabled for this MCP server")
        req: JsonDict = {
            "cmd": "capture",
            "timeout": self._validated_wait_timeout(timeout),
            # Harmless when the capture is not an AXI monitor's.
            "decode_axi": True,
            "format": self._validated_capture_format(fmt),
            # MCP names this by intent; RPC still uses its historical field.
            "summarize": bool(include_event_summary),
        }
        if immediate:
            # RPC rewrites the config to an always-true trigger and fires now.
            req["immediate"] = True
        if segments:
            # Without this RPC reads segment 0 only, so a segmented core
            # silently loses every other segment's samples.
            req["segments"] = True
        config = self._validated_capture_config(config)
        if config:
            req = {**config, **req}
        return self._rpc_call(
            req, commit=self._commit_capture, prepare=self._prepare_capture
        )

    def capture_wait(
        self,
        *,
        timeout: float = 10.0,
        fmt: str = "json",
        include_event_summary: bool = False,
        segments: bool = False,
    ) -> JsonDict:
        if not self.capabilities.allow_capture:
            raise PermissionError("capture tools are disabled for this MCP server")
        req: JsonDict = {
            "cmd": "capture_wait",
            "timeout": self._validated_wait_timeout(timeout),
            # Harmless when the capture is not an AXI monitor's.
            "decode_axi": True,
            "format": self._validated_capture_format(fmt),
            "summarize": bool(include_event_summary),
        }
        if segments:
            req["segments"] = True
        try:
            return self._rpc_call(
                req, commit=self._commit_capture, prepare=self._prepare_capture
            )
        except McpWatchdogTimeout:
            # The watchdog abandoned the worker — a real fault, not "still
            # waiting". Let it propagate so the caller stops polling.
            raise
        except CaptureNotReady:
            # The one expected timeout: the trigger has not fired and the core
            # is still armed. The documented poll loop treats this as normal,
            # so report it as data, not an error.
            #
            # Deliberately NOT `except TimeoutError`. A timeout raised by the
            # transport while reading status or sample data means the link may
            # be wedged; calling that "still armed" sends the agent into a
            # poll loop against a session that will never answer.
            return {"ok": True, "triggered": False, "still_armed": True}

    def capture_status(self) -> JsonDict:
        return self._rpc_call({"cmd": "capture_status"})

    def configure(self, config: JsonDict | None = None) -> JsonDict:
        if not self.capabilities.allow_capture:
            raise PermissionError("configure tools are disabled for this MCP server")
        req: JsonDict = {"cmd": "configure"}
        config = self._validated_capture_config(config)
        if config:
            req.update(config)
        return self._rpc_call(req)

    def arm(self) -> JsonDict:
        if not self.capabilities.allow_capture:
            raise PermissionError("arm tools are disabled for this MCP server")
        return self._rpc_call({"cmd": "arm"})

    def disarm(self) -> JsonDict:
        if not self.capabilities.allow_capture:
            raise PermissionError("disarm tools are disabled for this MCP server")
        return self._rpc_call({"cmd": "disarm"})

    def list_cores(self) -> JsonDict:
        return self._rpc_call({"cmd": "list_cores"})

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
        )
        return req

    def eio_connect(
        self,
        *,
        backend: Backend = "hw_server",
        host: str | None = None,
        port: int | None = None,
        tap: str | None = None,
        chain: int | None = None,
        hardware: str | None = None,
        quartus_stp: str | None = None,
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
        )
        return self._rpc_call(req, commit=self._commit_eio_connected)

    def eio_close(self) -> JsonDict:
        def _forget() -> None:
            self.last_eio_read = None

        if self._closed_locally("eio_connected", reset=_forget):
            return {"ok": True}
        return self._rpc_call({"cmd": "eio_close"}, commit=self._commit_eio_closed)

    def eio_read(self) -> JsonDict:
        return self._rpc_call({"cmd": "eio_read"}, commit=self._commit_eio_read)

    def eio_write(self, value: int | str) -> JsonDict:
        if not self.capabilities.allow_eio_write:
            raise PermissionError(
                "EIO writes are disabled; restart with --allow-eio-write to enable them"
            )
        return self._rpc_call({"cmd": "eio_write", "value": self._eio_value(value)})

    @staticmethod
    def _eio_value(value: int | str) -> int | str:
        """Keep an output vector exact on the way down as well as up.

        RPC already parses base-prefixed strings; typing this `int` only meant
        a JS client could not express an output wider than 53 bits at all.
        """
        if isinstance(value, str):
            try:
                int(value, 0)
            except ValueError as exc:
                raise ValueError(
                    f"value must be an integer or a base-prefixed string "
                    f"(e.g. \"0xdeadbeef\"), got {value!r}"
                ) from exc
            return value
        return int(value)

    def axi_connect(
        self,
        *,
        backend: Backend = "hw_server",
        host: str | None = None,
        port: int | None = None,
        tap: str | None = None,
        chain: int | None = None,
        hardware: str | None = None,
        quartus_stp: str | None = None,
    ) -> JsonDict:
        if self.axi_connected:
            self.axi_close()
        return self._rpc_call(
            self._bridge_connect_req(
                cmd="axi_connect",
                backend=backend,
                host=host,
                port=port,
                tap=tap,
                chain=chain,
                hardware=hardware,
                quartus_stp=quartus_stp,
            ),
            commit=self._commit_axi_connected,
        )

    def axi_close(self) -> JsonDict:
        if self._closed_locally("axi_connected", reset=lambda: None):
            return {"ok": True}
        return self._rpc_call({"cmd": "axi_close"}, commit=self._commit_axi_closed)

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
        words = [int(word) for word in data]
        if len(words) > _MAX_AXI_WORDS:
            raise ValueError(
                f"data has {len(words)} words; the per-call limit is "
                f"{_MAX_AXI_WORDS} — split the write into smaller blocks"
            )
        return self._rpc_call(
            {
                "cmd": "axi_write_block",
                "addr": int(addr),
                "data": words,
                "burst": bool(burst),
            }
        )

    def axi_dump(self, addr: int, count: int, *, burst: bool = False) -> JsonDict:
        count_i = int(count)
        if count_i < 0:
            raise ValueError(f"count must be >= 0, got {count_i}")
        if count_i > _MAX_AXI_WORDS:
            raise ValueError(
                f"count is {count_i}; the per-call limit is {_MAX_AXI_WORDS} "
                "words — dump in smaller chunks with successive addresses"
            )
        return self._rpc_call(
            {"cmd": "axi_dump", "addr": int(addr), "count": count_i, "burst": bool(burst)}
        )

    def uart_connect(
        self,
        *,
        backend: Backend = "hw_server",
        host: str | None = None,
        port: int | None = None,
        tap: str | None = None,
        chain: int | None = None,
        hardware: str | None = None,
        quartus_stp: str | None = None,
    ) -> JsonDict:
        if self.uart_connected:
            self.uart_close()
        return self._rpc_call(
            self._bridge_connect_req(
                cmd="uart_connect",
                backend=backend,
                host=host,
                port=port,
                tap=tap,
                chain=chain,
                hardware=hardware,
                quartus_stp=quartus_stp,
            ),
            commit=self._commit_uart_connected,
        )

    def uart_close(self) -> JsonDict:
        if self._closed_locally("uart_connected", reset=lambda: None):
            return {"ok": True}
        return self._rpc_call({"cmd": "uart_close"}, commit=self._commit_uart_closed)

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
        else:
            # RPC decodes with validate=False, which silently DROPS non-alphabet
            # characters and transmits whatever garbage remains. Reject it here
            # instead of mangling the payload onto the wire.
            try:
                base64.b64decode(data_base64, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError(f"data_base64 is not valid base64: {exc}") from exc
        return self._rpc_call({"cmd": "uart_send", "data": data_base64})

    def uart_recv(self, count: int, timeout: float = 1.0) -> JsonDict:
        count_i = int(count)
        if count_i < 0:
            raise ValueError(f"count must be >= 0, got {count_i}")
        return self._rpc_call(
            {
                "cmd": "uart_recv",
                "count": count_i,
                "timeout": self._validated_wait_timeout(timeout),
            }
        )

    def uart_status(self) -> JsonDict:
        return self._rpc_call({"cmd": "uart_status"})

    def status(self) -> SessionStatus:
        # Everything is read under one hold of the lock. Commits run under it
        # too, so this cannot straddle one and report a busy slot alongside
        # the connection flags from after that command landed -- a state the
        # session was never actually in.
        with self._rpc_lock:
            active_rpc_cmd = self._active_rpc_cmd
            rpc_busy = active_rpc_cmd is not None
            if self._poisoned:
                session_state = "poisoned"
            elif rpc_busy:
                session_state = "busy"
            else:
                session_state = "ready"
            return self._status_snapshot(session_state, rpc_busy, active_rpc_cmd)

    def _status_snapshot(
        self, session_state: str, rpc_busy: bool, active_rpc_cmd: str | None
    ) -> SessionStatus:
        """Render the status body. Caller holds ``_rpc_lock``."""
        cache = self._capture_cache
        return {
            "mcp_server_version": self._server_version(),
            "rpc_schema_version": self.last_rpc_schema_version,
            "session_state": session_state,
            "rpc_busy": rpc_busy,
            "active_rpc_cmd": active_rpc_cmd,
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
                "rpc_timeout_sec": self.capabilities.rpc_timeout_sec,
                "rpc_cancel_grace_sec": self.capabilities.rpc_cancel_grace_sec,
                "probe_root": (
                    str(self.capabilities.probe_root)
                    if self.capabilities.probe_root is not None
                    else None
                ),
                "allowed_hosts": list(self.capabilities.allowed_hosts),
                "bitfile_root": (
                    str(self.capabilities.bitfile_root)
                    if self.capabilities.bitfile_root is not None
                    else None
                ),
            },
            "last_probe": dict(self.last_probe) if self.last_probe is not None else None,
            "last_capture_summary": (
                dict(cache.summary) if cache is not None else None
            ),
            "last_capture_size_bytes": (
                cache.size_bytes if cache is not None else None
            ),
            "last_eio_read": (
                dict(self.last_eio_read) if self.last_eio_read is not None else None
            ),
        }

    def last_capture_json_text(self) -> str:
        cache = self._capture_cache
        if cache is None:
            return json.dumps(
                {"available": False},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        return cache.json_text

    @staticmethod
    def _is_utf8_start_byte(byte: int) -> bool:
        return byte < 0x80 or 0xC2 <= byte <= 0xF4

    @staticmethod
    def _capture_summary(payload: JsonDict) -> JsonDict:
        # Keep tool results compact while allowing newly added top-level metadata
        # to surface automatically. Update this set when RPC adds bulky payloads.
        bulky_keys = {
            "content",
            "csv",
            "data",
            "raw_dump",
            "result",
            "samples",
            "segments",
            "timestamps",
            "vcd",
            "words",
            "axi",
        }
        summary: JsonDict = {
            key: value for key, value in payload.items() if key not in bulky_keys
        }
        axi = FcapzMcpSession._axi_headline(payload)
        if axi is not None:
            summary["axi"] = axi
        summary.setdefault("ok", True)
        return summary

    @staticmethod
    def _axi_sections(payload: JsonDict) -> list[tuple[int | None, JsonDict]]:
        """Every decoded AXI section in a capture, with its segment index.

        A plain capture carries one at the top level; a segmented capture
        carries one per segment.
        """
        section = payload.get("axi")
        if isinstance(section, dict):
            return [(None, section)]
        out: list[tuple[int | None, JsonDict]] = []
        for index, segment in enumerate(payload.get("segments") or []):
            if isinstance(segment, dict) and isinstance(segment.get("axi"), dict):
                out.append((segment.get("segment", index), segment["axi"]))
        return out

    @staticmethod
    def _axi_headline(payload: JsonDict) -> JsonDict | None:
        """Counts only — the transactions themselves are paged separately."""
        sections = FcapzMcpSession._axi_sections(payload)
        if not sections:
            return None
        totals: JsonDict = {"protocol": sections[0][1].get("protocol")}
        for key in (
            "transaction_count",
            "write_count",
            "read_count",
            "error_count",
            "anomaly_count",
        ):
            totals[key] = sum(int(sec.get(key) or 0) for _, sec in sections)
        latencies = [
            sec.get("max_latency") for _, sec in sections if sec.get("max_latency") is not None
        ]
        totals["max_latency"] = max(latencies) if latencies else None
        totals["flagged_count"] = sum(
            int(sec.get("flagged_count") or 0) for _, sec in sections
        )
        # The counts above are the first thing an agent reads about a
        # capture, so the caveat travels with them rather than waiting for
        # the first page of transactions.
        totals["pairing"] = FcapzMcpSession._merged_pairing(sections)
        totals["sampling"] = FcapzMcpSession._merged_sampling(sections)
        undecodable = [
            sec.get("unavailable_reason")
            for _, sec in sections
            if sec.get("decoded") is False and sec.get("unavailable_reason")
        ]
        if undecodable:
            totals["unavailable_reason"] = undecodable[0]
        totals["hint"] = (
            "decoded AXI transactions are available via fcapz_axi_transactions"
        )
        return totals

    def _bounded_capture_summary(self, summary: JsonDict, max_bytes: int = 8192) -> JsonDict:
        summary = dict(summary)
        payload = json.dumps(summary, separators=(",", ":")).encode("utf-8")
        if len(payload) <= max_bytes:
            return summary
        return {
            "summary_status": {
                "truncated": True,
                "size_bytes": len(payload),
                "max_bytes": max_bytes,
            },
        }

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
        self._stop_owner()

    def _stop_owner(self) -> None:
        """Retire the hardware owner thread after the closes above."""
        with self._rpc_lock:
            owner = self._owner
            self._owner = None
        if owner is None or not owner.is_alive():
            return
        self._command_q.put(None)
        # Bounded: an abandoned command may still hold the transport, and the
        # thread is a daemon, so never block process exit on it.
        owner.join(timeout=self.capabilities.rpc_cancel_grace_sec)


def build_mcp_server(session: FcapzMcpSession):
    """Build and return a FastMCP app.

    Kept separate so unit tests can cover :class:`FcapzMcpSession` without the
    optional MCP SDK installed.
    """

    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.server.fastmcp.exceptions import ToolError
    except ImportError as exc:
        raise RuntimeError(
            "The MCP SDK is required for `fcapz-mcp`. Install with "
            "`pip install fpgacapzero[mcp]` or `pip install mcp`."
        ) from exc

    class _CodedFastMCP(FastMCP):
        """FastMCP whose every tool failure is one machine-readable object.

        Each tool body is already wrapped in :func:`_coded`, but two things
        happen outside it. Argument validation runs *before* the body, so a
        wrong enum or an unknown config field failed as pydantic prose with
        no code and no remedy. And FastMCP prefixes whatever the body raised
        with "Error executing tool <name>: ", so even a coded failure did not
        arrive as parseable JSON. Overriding the one seam above validation
        and below the protocol fixes both, and adds the tool's name to the
        body where it is a field rather than a prefix.

        The handler is bound at construction, so this has to be a subclass;
        rebinding `call_tool` on the instance afterwards would not be seen.
        """

        # Accepted argument names per tool, read once from the published
        # schema. Registration is done before the first call, so this never
        # goes stale.
        _accepted: dict[str, frozenset[str]] = {}

        def _reject_unknown_arguments(
            self, name: str, arguments: dict[str, Any] | None
        ) -> None:
            """Fail a misspelled argument instead of running without it.

            Pydantic ignores unknown keys when validating a tool's argument
            model, so `fcapz_capture(formatt="csv")` used to run a default
            capture and report success. The nested config has
            `extra="forbid"`, but the model FastMCP generates from the
            function signature is not ours to configure, so the check lives
            here.
            """
            known = self._accepted.get(name)
            if known is None:
                tool = self._tool_manager.get_tool(name)
                if tool is None:
                    raise UnknownToolError(f"unknown tool: {name}")
                known = frozenset(tool.parameters.get("properties") or ())
                self._accepted[name] = known
            unknown = sorted(set(arguments or ()) - known)
            if unknown:
                raise ValueError(
                    f"{name} has no argument(s) {', '.join(unknown)}; "
                    f"it accepts: {', '.join(sorted(known)) or '(none)'}"
                )

        async def call_tool(self, name, arguments):  # type: ignore[override]
            try:
                self._reject_unknown_arguments(name, arguments)
                return await super().call_tool(name, arguments)
            except Exception as exc:
                body = _coded_call_failure(name, exc)
                raise ToolError(
                    json.dumps(body, ensure_ascii=False, sort_keys=True)
                ) from exc

    mcp = _CodedFastMCP("fpgacapZero")

    def tool(*, requires: bool = True, **annotations: Any):
        """Register a tool, unless its capability is switched off.

        A tool that can only ever answer PermissionError is worse than absent:
        the agent plans around it, spends a call discovering the refusal, and
        pays for its schema in every request's context. Gate registration on
        the capability so the advertised surface is what this server can
        actually do. The session-level checks stay as the real enforcement.
        """

        def decorate(fn: Callable[..., Any]):
            if not requires:
                return fn
            return mcp.tool(annotations=annotations)(_offloaded(_coded(fn)))

        return decorate

    caps = session.capabilities

    # `program=` can reflash the FPGA, but only when the server was started
    # with --allow-program. Annotations are static per registration, and the
    # capability is known here, so advertise the truth for this server rather
    # than a blanket hint either way.
    @tool(
        destructiveHint=session.capabilities.allow_program,
        idempotentHint=False,
        readOnlyHint=False,
    )
    def fcapz_connect(
        backend: Backend = "hw_server",
        host: str | None = None,
        port: int | None = None,
        tap: str | None = None,
        chain: int | None = None,
        program: str | None = None,
        single_chain_burst: bool = True,
        hardware: str | None = None,
        quartus_stp: str | None = None,
    ) -> JsonDict:
        """Connect to an ELA core.

        Backends: "hw_server" (AMD/Xilinx hw_server, the default), "openocd"
        (any OpenOCD-supported adapter), and "usb_blaster" (Intel/Altera via
        Quartus). For usb_blaster, `hardware` selects the Quartus cable and
        `quartus_stp` names the quartus_stp executable — the latter spawns a
        host process, so it is rejected unless fcapz-mcp was started with
        --allow-program (omit it to use the server's configured toolchain).
        `hardware`/`quartus_stp` are rejected for the other backends, and
        host/port/tap are rejected for usb_blaster. `chain` selects the JTAG
        USER chain the ELA sits on; omit it to probe the default and autodetect.
        All timeout values are in seconds. `program` is hw_server-only, disabled
        unless started with --allow-program, and must be an existing .bit file.
        """

        return session.connect(
            backend=backend,
            host=host,
            port=port,
            tap=tap,
            chain=chain,
            program=program,
            single_chain_burst=single_chain_burst,
            hardware=hardware,
            quartus_stp=quartus_stp,
        )

    @tool(destructiveHint=False, idempotentHint=True, readOnlyHint=False)
    def fcapz_close() -> JsonDict:
        """Close the active ELA connection."""

        return session.close()

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=True)
    def fcapz_probe() -> JsonDict:
        """Read ELA identity, dimensions, and feature registers."""

        return session.probe()

    @tool(destructiveHint=False, idempotentHint=True, readOnlyHint=True)
    def fcapz_list_cores() -> JsonDict:
        """List debug cores discovered on the connected board.

        Read-only orientation: reports each core's type, JTAG USER `chain`, and
        identity. Covers the connected ELA and the EIO if one is discoverable;
        AXI/UART bridges are not auto-scanned yet, so their `chain` still has
        to be supplied. Requires an active connection.
        """

        return session.list_cores()

    @tool(
        requires=caps.allow_capture,
        destructiveHint=False,
        idempotentHint=False,
        readOnlyHint=False,
    )
    async def fcapz_capture(
        config: CaptureConfigDict | None = None,
        timeout: float = 10.0,
        format: CaptureFormat = "json",
        include_event_summary: bool = False,
        immediate: bool = False,
        segments: bool = False,
    ) -> JsonDict:
        """Configure, arm, and capture samples from the ELA.

        timeout is in seconds and may exceed the server's --rpc-timeout (up to a
        300 s server cap) — the watchdog waits out the capture.
        immediate=true rewrites the trigger to fire now (no waiting), for a
        snapshot of current state. include_event_summary asks the RPC layer to
        add decoded event metadata to the capture result.
        segments=true reads back every segment of a segmented core instead of
        segment 0 alone (fcapz_probe reports num_segments).
        The tool returns summary metadata only; use fcapz_get_last_capture or
        fcapz://last-capture for full payloads.
        """

        return await _with_progress(
            mcp.get_context(),
            "capture",
            lambda: session.capture(
                config=config,
                timeout=timeout,
                fmt=format,
                include_event_summary=include_event_summary,
                immediate=immediate,
                segments=segments,
            ),
            timeout,
        )

    @tool(destructiveHint=False, idempotentHint=True, readOnlyHint=False)
    def fcapz_drop_last_capture() -> JsonDict:
        """Forget the cached full capture payload exposed by fcapz://last-capture."""

        return session.drop_last_capture()

    @tool(destructiveHint=False, idempotentHint=True, readOnlyHint=True)
    def fcapz_get_last_capture(
        max_bytes: int | None = _DEFAULT_FULL_CAPTURE_MAX_BYTES,
    ) -> JsonDict:
        """Return the cached full capture payload for clients without resource support.

        max_bytes defaults to 1 MiB. Larger captures return a compact truncated
        marker plus summary metadata instead of flooding model context. Pass
        max_bytes=null to force the full payload, or prefer
        fcapz_get_last_capture_chunk / fcapz://last-capture for large captures.
        """

        return session.get_last_capture(max_bytes=max_bytes)

    @tool(destructiveHint=False, idempotentHint=True, readOnlyHint=True)
    def fcapz_get_capture_samples(
        start: int = 0,
        count: int = 128,
        fields: list[str] | None = None,
        radix: SampleRadix = "hex",
    ) -> SamplePage:
        """Page the cached capture's samples as whole records.

        Prefer this over fcapz_get_last_capture_chunk for inspecting sample
        data: each page is valid JSON on its own and carries `total` and
        `trigger_index` (the index of the trigger sample), so a page can be
        read without reassembling anything. The chunk tool remains for
        exporting a whole payload verbatim, or for csv/vcd captures.

        `fields` selects named signals from the capture's probe map (all of
        them by default when the capture has one); omit the probe map and you
        get the packed `value` instead. `radix` is "hex" (default) or "int" —
        values too wide for an exact JSON number are always hex regardless.
        Page with the returned `next_start` until it is null; `count` is
        capped at 512. For an AXI monitor capture, prefer
        fcapz_axi_transactions — transactions beat cycles for bus debugging.
        """

        return session.capture_samples(
            start=start, count=count, fields=fields, radix=radix
        )

    @tool(destructiveHint=False, idempotentHint=True, readOnlyHint=True)
    def fcapz_axi_transactions(
        start: int = 0,
        count: int = 64,
        only_anomalies: bool = False,
        kind: TransactionKind | None = None,
    ) -> AxiTransactionPage:
        """Read the cached capture as AXI transactions instead of raw samples.

        Reassembles the per-cycle AXI4-Lite bus trace into whole transactions:
        address, data, byte strobes, response, the cycle each beat landed on,
        latency, stall counts, and protocol anomaly `flags`. Available
        whenever the capture used an AXI monitor probe map.

        Prefer this over paging raw samples when debugging bus behaviour: it
        is orders of magnitude smaller and each page is valid JSON on its own.
        `only_anomalies=true` returns just the flagged transactions — start
        there. `kind` filters to "read" or "write". Page with the returned
        `next_start` until it is null; `count` is capped at 256.

        Flags worth knowing: `error_response` (SLVERR/DECERR), `partial_write`
        / `write_strobe_zero` (byte strobes), `data_before_address`,
        `write_missing_data` / `write_missing_address` (a half-formed write —
        the shape a dropped or scrambled command leaves), `unaligned_address`,
        and the benign window-edge cases `request_before_window` /
        `no_response_in_window`, which mean the transaction straddled the
        start or end of the capture rather than that anything went wrong.
        """

        return session.axi_transactions(
            start=start, count=count, only_anomalies=only_anomalies, kind=kind
        )

    @tool(destructiveHint=False, idempotentHint=True, readOnlyHint=True)
    def fcapz_get_last_capture_chunk(
        offset: int = 0,
        max_bytes: int = _DEFAULT_CAPTURE_CHUNK_BYTES,
    ) -> CaptureChunk:
        """Return a bounded JSON text chunk of the cached capture payload.

        Use this for large captures when the client has no MCP resource support.
        The returned next_offset is null when the chunk reaches EOF.
        """

        return session.get_last_capture_chunk(offset=offset, max_bytes=max_bytes)

    @tool(
        requires=caps.allow_capture,
        destructiveHint=False,
        idempotentHint=False,
        readOnlyHint=False,
    )
    def fcapz_configure(config: CaptureConfigDict | None = None) -> JsonDict:
        """Configure the connected ELA without arming it.

        config accepts the same capture fields as fcapz_capture. Use this to
        stage a trigger, then fcapz_arm to arm once, fcapz_capture_status to
        poll, and fcapz_capture_wait to read the result out — the manual flow
        that holds one hardware arm across many polls (fcapz_capture instead
        reconfigures and re-arms on every call). fcapz_disarm stops an arm.
        """

        return session.configure(config=config)

    @tool(
        requires=caps.allow_capture,
        destructiveHint=False,
        idempotentHint=False,
        readOnlyHint=False,
    )
    def fcapz_arm() -> JsonDict:
        """Arm the connected ELA using the current hardware configuration.

        Pairs with fcapz_configure; read the result out with fcapz_capture_wait.
        """

        return session.arm()

    @tool(
        requires=caps.allow_capture,
        destructiveHint=False,
        idempotentHint=False,
        readOnlyHint=False,
    )
    async def fcapz_capture_wait(
        timeout: float = 10.0,
        format: CaptureFormat = "json",
        include_event_summary: bool = False,
        segments: bool = False,
    ) -> JsonDict:
        """Read out an already-armed capture without reconfiguring or re-arming.

        Pairs with fcapz_configure + fcapz_arm: arm once, then poll here.
        timeout is in seconds (it may exceed --rpc-timeout, up to a 300 s server
        cap). If the trigger has not fired the tool returns
        {"triggered": false, "still_armed": true} rather than erroring, so it is
        safe to call in a poll loop; the core stays armed. On a hit it returns
        summary metadata only — use fcapz_get_last_capture or
        fcapz://last-capture for the full payload.
        """

        return await _with_progress(
            mcp.get_context(),
            "capture_wait",
            lambda: session.capture_wait(
                timeout=timeout,
                fmt=format,
                include_event_summary=include_event_summary,
                segments=segments,
            ),
            timeout,
        )

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=True)
    def fcapz_capture_status() -> JsonDict:
        """Poll an armed ELA without transferring samples.

        Returns the capture FSM state (waiting-for-trigger vs. triggered) so an
        agent can show progress before reading out with fcapz_capture_wait.
        """

        return session.capture_status()

    @tool(
        requires=caps.allow_capture,
        destructiveHint=True,
        idempotentHint=True,
        readOnlyHint=False,
    )
    def fcapz_disarm() -> JsonDict:
        """Soft-reset the ELA capture FSM to idle, discarding any in-flight arm.

        The clean way to stop an armed capture that is still waiting for a
        trigger. Requires capture access (disabled under --read-only).
        """

        return session.disarm()

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=False)
    def fcapz_eio_connect(
        backend: Backend = "hw_server",
        host: str | None = None,
        port: int | None = None,
        tap: str | None = None,
        chain: int | None = None,
        hardware: str | None = None,
        quartus_stp: str | None = None,
    ) -> JsonDict:
        """Connect to an Embedded I/O core.

        chain defaults by backend: 3 for hw_server/openocd, 0 for
        usb_blaster. Pass chain explicitly for non-default JTAG USER chains,
        Intel virtual JTAG instance indices, or managed core slots. Backend
        fields mirror fcapz_connect: hardware/quartus_stp for Quartus USB
        Blaster sessions.
        """

        return session.eio_connect(
            backend=backend,
            host=host,
            port=port,
            tap=tap,
            chain=chain,
            hardware=hardware,
            quartus_stp=quartus_stp,
        )

    @tool(destructiveHint=False, idempotentHint=True, readOnlyHint=False)
    def fcapz_eio_close() -> JsonDict:
        """Close the active EIO connection."""

        return session.eio_close()

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=True)
    def fcapz_eio_read() -> JsonDict:
        """Read the current EIO input vector.

        `value` is a hex string instead of a number when the vector is wider
        than 53 bits; `value_encoding` says which, and `value_hex` is always
        exact.
        """

        return session.eio_read()

    @tool(
        requires=caps.allow_eio_write,
        destructiveHint=True,
        idempotentHint=False,
        readOnlyHint=False,
    )
    def fcapz_eio_write(value: int | str) -> JsonDict:
        """Write the EIO output vector when write access is enabled.

        Pass a hex string (`"0x1122334455667788"`) for vectors wider than 53
        bits — a JSON number cannot carry them exactly.
        """

        return session.eio_write(value)

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=False)
    def fcapz_axi_connect(
        backend: Backend = "hw_server",
        host: str | None = None,
        port: int | None = None,
        tap: str | None = None,
        chain: int | None = None,
        hardware: str | None = None,
        quartus_stp: str | None = None,
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

    @tool(
        requires=caps.allow_axi_write,
        destructiveHint=True,
        idempotentHint=False,
        readOnlyHint=False,
    )
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

    @tool(
        requires=caps.allow_axi_write,
        destructiveHint=True,
        idempotentHint=False,
        readOnlyHint=False,
    )
    def fcapz_axi_write_block(
        addr: int,
        data: list[int],
        burst: bool = False,
    ) -> JsonDict:
        """Write 32-bit AXI words starting at an integer byte address.

        data is a list of integer words (at most 4096 per call — split larger
        writes into successive blocks). When burst is false, words are written
        sequentially; when true, the bridge uses its burst write path.
        """

        return session.axi_write_block(addr, data, burst=burst)

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=True)
    def fcapz_axi_dump(addr: int, count: int, burst: bool = False) -> JsonDict:
        """Read count 32-bit AXI words starting at an integer byte address.

        count is measured in 32-bit words, not bytes, and is capped at 4096 per
        call — dump larger regions in chunks at successive addresses.
        """

        return session.axi_dump(addr, count, burst=burst)

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=False)
    def fcapz_uart_connect(
        backend: Backend = "hw_server",
        host: str | None = None,
        port: int | None = None,
        tap: str | None = None,
        chain: int | None = None,
        hardware: str | None = None,
        quartus_stp: str | None = None,
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
        )

    @tool(destructiveHint=False, idempotentHint=True, readOnlyHint=False)
    def fcapz_uart_close() -> JsonDict:
        """Close the active UART bridge connection."""

        return session.uart_close()

    @tool(
        requires=caps.allow_uart_send,
        destructiveHint=True,
        idempotentHint=False,
        readOnlyHint=False,
    )
    def fcapz_uart_send(
        data_base64: str | None = None,
        text: str | None = None,
    ) -> JsonDict:
        """Send bytes over eJTAG-UART when UART send access is enabled.

        Pass data_base64 for arbitrary bytes or text for UTF-8 text.
        """

        return session.uart_send(data_base64=data_base64, text=text)

    # Not read-only: receiving consumes bytes from the UART RX FIFO.
    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=False)
    def fcapz_uart_recv(count: int, timeout: float = 1.0) -> JsonDict:
        """Receive up to count bytes from eJTAG-UART; timeout is in seconds."""

        return session.uart_recv(count, timeout)

    @tool(destructiveHint=False, idempotentHint=False, readOnlyHint=True)
    def fcapz_uart_status() -> JsonDict:
        """Return eJTAG-UART status counters and FIFO state."""

        return session.uart_status()

    @tool(destructiveHint=False, idempotentHint=True, readOnlyHint=True)
    def fcapz_status() -> SessionStatus:
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

        return session.last_capture_json_text()

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
        help=(
            "Allow fcapz_connect(program=...) to program a .bit file (any path "
            "unless --bitfile-root is set) and allow a caller-supplied "
            "quartus_stp executable path for the usb_blaster backend"
        ),
    )
    parser.add_argument(
        "--probe-root",
        type=Path,
        default=None,
        metavar="DIR",
        help=(
            "Allow capture config `probe_file` to read probe maps under this "
            "directory. Without it probe_file is rejected: it would read an "
            "arbitrary file on this machine (pass `probes` inline instead)"
        ),
    )
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="HOST",
        dest="allow_host",
        help=(
            "Permit connecting a backend to this host as well as loopback. "
            "Repeatable; without it only 127.0.0.1/localhost/::1 are allowed"
        ),
    )
    parser.add_argument(
        "--bitfile-root",
        type=Path,
        default=None,
        metavar="DIR",
        help="Only allow programming .bit files under this directory",
    )
    parser.add_argument(
        "--rpc-timeout",
        type=float,
        default=30.0,
        metavar="SEC",
        help=(
            "Watchdog window for one RPC call before attempting backend "
            "cancellation. Wait-bearing commands (capture/capture_wait/"
            "uart_recv) extend it to outlast their own timeout plus this much "
            "readback headroom"
        ),
    )
    parser.add_argument(
        "--rpc-cancel-grace",
        type=float,
        default=_RPC_CANCEL_GRACE_SEC,
        metavar="SEC",
        help="Seconds to wait for an RPC worker to unwind after backend cancellation",
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
    # `not > 0` rather than `<= 0`: NaN compares false both ways, and a NaN
    # watchdog disables the watchdog and spins a core doing it.
    if not args.rpc_timeout > 0 or not math.isfinite(args.rpc_timeout):
        parser.error("--rpc-timeout must be a finite number > 0")
    if not args.rpc_cancel_grace > 0 or not math.isfinite(args.rpc_cancel_grace):
        parser.error("--rpc-cancel-grace must be a finite number > 0")
    capabilities = McpCapabilities(
        allow_capture=not args.read_only,
        probe_root=args.probe_root,
        allowed_hosts=tuple(args.allow_host),
        allow_eio_write=bool(args.allow_eio_write),
        allow_axi_write=bool(args.allow_axi_write),
        allow_uart_send=bool(args.allow_uart_send),
        allow_program=bool(args.allow_program),
        bitfile_root=args.bitfile_root,
        rpc_timeout_sec=float(args.rpc_timeout),
        rpc_cancel_grace_sec=float(args.rpc_cancel_grace),
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
