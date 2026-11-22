# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Client side of the broker: find or start the runtime, run jobs on it.

:meth:`BrokerSession.connect` reads ``runtime.json`` in the per-user runtime
directory and connects.  When no runtime answers it starts one (detached,
with this fcapz on its ``PYTHONPATH``) and waits for it.  If that runtime
cannot start, :class:`~fcapz.broker.wire.BrokerStartError` says why: there
is never a silent fallback to a direct transport.

Requests block in the caller, with a receiver thread underneath, so Ctrl+C
reaches the caller at once: the session then cancels the job in the runtime
and waits briefly for it to stop before re-raising.
"""

from __future__ import annotations

import contextlib
import itertools
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from multiprocessing import connection as mpc
from pathlib import Path
from typing import Any, Callable

from ..analyzer import Analyzer, CaptureConfig, CaptureResult
from . import wire
from .coreref import CoreRef, TargetSpec
from .runtime import EXIT_ALREADY_RUNNING, LOG_NAME, default_dir, ensure_dir, read_info

START_TIMEOUT_S = 20.0
_LOST = object()

EventSink = Callable[[dict[str, Any]], None]


class BrokerNotRunning(wire.BrokerError):
    """No runtime answers in the directory (and none was to be started)."""


@dataclass
class BrokerCapture:
    """A capture a broker job took."""

    result: CaptureResult
    core: CoreRef
    timestamp_w: int = 0
    capture_gen: int | None = None
    job: int | None = None

    def exporter(self) -> Analyzer:
        """An unconnected :class:`~fcapz.analyzer.Analyzer` to write the
        result with (``write_json`` / ``write_csv`` / ``write_vcd``)."""
        a = Analyzer(None)  # type: ignore[arg-type] - only exports
        a._hw_timestamp_w = self.timestamp_w  # noqa: SLF001
        return a


def _connect_info(directory: Path) -> tuple[Any, dict[str, Any]] | None:
    info = read_info(directory)
    if not info:
        return None
    try:
        conn = mpc.Client(
            info["address"], info["family"], authkey=bytes.fromhex(info["authkey"])
        )
    except (OSError, EOFError, KeyError, ValueError, mpc.AuthenticationError):
        return None
    return conn, info


def _log_tail(directory: Path, lines: int = 15) -> str:
    out = []
    for name in (LOG_NAME, "runtime-stderr.log"):
        try:
            text = (directory / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        tail = text.strip().splitlines()[-lines:]
        if tail:
            out.append(f"--- {name} ---\n" + "\n".join(tail))
    return "\n".join(out) or "(no runtime log)"


def spawn_runtime(directory: Path, spawn_id: str | None = None) -> subprocess.Popen:
    """Start a detached runtime for *directory*; *spawn_id* tags it in
    ``runtime.json``."""
    ensure_dir(directory)
    import fcapz

    env = dict(os.environ)
    pkg_parent = str(Path(fcapz.__file__).resolve().parent.parent)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (pkg_parent, env.get("PYTHONPATH", "")) if p
    )
    args = [sys.executable, "-m", "fcapz.broker", "--dir", str(directory)]
    if spawn_id:
        args += ["--spawn-id", spawn_id]
    stderr = open(directory / "runtime-stderr.log", "ab")  # noqa: SIM115
    kw: dict[str, Any] = dict(
        stdin=subprocess.DEVNULL, stdout=stderr, stderr=stderr,
        cwd=str(directory), env=env, close_fds=True,
    )
    try:
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                # Outlive a job object that kills its members with the shell.
                return subprocess.Popen(
                    args, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kw
                )
            except OSError:
                return subprocess.Popen(args, creationflags=flags, **kw)
        return subprocess.Popen(args, start_new_session=True, **kw)
    finally:
        stderr.close()


def _discard_spawn(proc: subprocess.Popen) -> None:
    """Stop a runtime this client started when it connected to another
    starter's.  Left alone, a spawn that reaches the election only after the
    winner has exited would win it and idle with no client."""
    if proc.poll() is not None:
        return
    with contextlib.suppress(OSError):
        proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(5.0)


class BrokerSession:
    """One connection to the runtime."""

    def __init__(self, conn: Any, info: dict[str, Any], *, name: str) -> None:
        self._conn = conn
        self.info = info
        self.name = name
        self._ids = itertools.count(1)
        self._send_lock = threading.Lock()
        self._inbox: dict[Any, queue.Queue] = {}
        self._inbox_lock = threading.Lock()
        self._lost: BaseException | None = None
        self._closed = False
        threading.Thread(target=self._read_loop, name="fcapz-broker-recv",
                         daemon=True).start()
        hello = self.request("hello", pid=os.getpid(), name=name)
        self.runtime_id: str = hello["runtime_id"]
        self.runtime_pid: int = hello["pid"]

    # ---- connecting ----------------------------------------------------

    @classmethod
    def connect(
        cls,
        directory: Path | str | None = None,
        *,
        autostart: bool = True,
        start_timeout: float = START_TIMEOUT_S,
        name: str = "fcapz",
    ) -> BrokerSession:
        d = Path(directory) if directory is not None else default_dir()
        found = _connect_info(d)
        if found is None:
            if not autostart:
                raise BrokerNotRunning(f"no fcapz broker is running in {d}")
            found = cls._start(d, start_timeout)
        conn, info = found
        return cls(conn, info, name=name)

    @staticmethod
    def _start(directory: Path, start_timeout: float) -> tuple[Any, dict[str, Any]]:
        spawn_id = secrets.token_hex(8)
        try:
            proc = spawn_runtime(directory, spawn_id)
        except OSError as exc:
            raise wire.BrokerStartError(f"could not start the fcapz broker: {exc}") from exc
        deadline = time.monotonic() + start_timeout
        while True:
            found = _connect_info(directory)
            if found is not None:
                if found[1].get("spawn_id") != spawn_id:
                    _discard_spawn(proc)
                return found
            rc = proc.poll()
            # Losing the election is fine: another starter's runtime won,
            # and it answers shortly.
            if rc is not None and rc != EXIT_ALREADY_RUNNING:
                raise wire.BrokerStartError(
                    f"the fcapz broker exited with code {rc} while starting:\n"
                    f"{_log_tail(directory)}"
                )
            if time.monotonic() >= deadline:
                raise wire.BrokerStartError(
                    f"the fcapz broker did not answer within {start_timeout:g} s "
                    f"({directory}):\n{_log_tail(directory)}"
                )
            time.sleep(0.05)

    # ---- plumbing ------------------------------------------------------

    def _read_loop(self) -> None:
        try:
            while True:
                msg = wire.decode(self._conn.recv_bytes())
                with self._inbox_lock:
                    q = self._inbox.get(msg.get("id"))
                if q is not None:
                    q.put(msg)
        except (EOFError, OSError, ValueError) as exc:
            self._lost = exc
        finally:
            with self._inbox_lock:
                for q in self._inbox.values():
                    q.put(_LOST)

    def _send(self, msg: dict[str, Any]) -> None:
        with self._send_lock:
            self._conn.send_bytes(wire.encode({"v": wire.PROTOCOL, **msg}))

    def request(
        self,
        op: str,
        /,
        *,
        on_event: EventSink | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """Send *op* and wait for its reply; events go to *on_event*."""
        if self._closed:
            raise wire.BrokerError("the broker session is closed")
        rid = next(self._ids)
        q: queue.Queue = queue.Queue()
        with self._inbox_lock:
            if self._lost is not None:
                raise self._lost_error()
            self._inbox[rid] = q
        try:
            try:
                self._send({"id": rid, "op": op, **fields})
            except (OSError, EOFError) as exc:
                raise self._lost_error() from exc
            try:
                return self._await(q, on_event)
            except KeyboardInterrupt:
                self._cancel(rid, q)
                raise
        finally:
            with self._inbox_lock:
                self._inbox.pop(rid, None)

    def _await(self, q: queue.Queue, on_event: EventSink | None) -> dict[str, Any]:
        while True:
            try:
                msg = q.get(timeout=0.2)
            except queue.Empty:
                continue
            if msg is _LOST:
                raise self._lost_error()
            if "event" in msg:
                if on_event is not None:
                    on_event(msg)
                continue
            if msg.get("ok"):
                return msg
            raise wire.error_from_dict(msg.get("error") or {})

    def _cancel(self, rid: Any, q: queue.Queue) -> None:
        """Cancel request *rid* and wait (briefly) until its job has stopped,
        so the core is free when the caller goes on."""
        try:
            self._send({"id": f"cancel-{rid}", "op": "cancel", "request": rid})
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    msg = q.get(timeout=0.2)
                except queue.Empty:
                    continue
                if msg is _LOST or "event" not in msg:
                    return
        except (OSError, EOFError):
            pass

    def _lost_error(self) -> wire.BrokerConnectionLost:
        return wire.BrokerConnectionLost(
            f"lost the fcapz broker (runtime {self.info.get('runtime_id')}, pid "
            f"{self.info.get('pid')}): any job in progress is lost, and nothing "
            "was retried or re-armed"
        )

    def close(self) -> None:
        self._closed = True
        try:
            self._conn.close()
        except OSError:
            pass

    def __enter__(self) -> BrokerSession:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ---- operations ----------------------------------------------------

    @staticmethod
    def _target(target: TargetSpec | dict[str, Any]) -> dict[str, Any]:
        return target.to_dict() if isinstance(target, TargetSpec) else dict(target)

    def probe(
        self,
        target: TargetSpec | dict[str, Any],
        *,
        core: str = "ela",
        chain: int | None = None,
        instance: int | None = None,
        base_addr: int = 0,
    ) -> dict[str, Any]:
        """Identity and geometry of a core; ``core`` holds its :class:`CoreRef`."""
        r = self.request(
            "probe", target=self._target(target), core=core, chain=chain,
            instance=instance, base_addr=base_addr,
        )["result"]
        return {**r["info"], "core": CoreRef.from_dict(r["core"])}

    def capture(
        self,
        target: TargetSpec | dict[str, Any],
        config: CaptureConfig,
        *,
        chain: int = 1,
        instance: int | None = None,
        timeout: float = 10.0,
        queue_timeout: float = 30.0,
        expect_gen: int | None = None,
        on_event: EventSink | None = None,
    ) -> BrokerCapture:
        """Configure, arm, wait and read one capture as a single job."""
        msg = self.request(
            "capture", target=self._target(target), chain=chain, instance=instance,
            config=wire.config_to_dict(config), timeout=timeout,
            queue_timeout=queue_timeout, expect_gen=expect_gen, on_event=on_event,
        )
        return _capture_from(msg["result"], msg.get("job"))

    def eio(
        self,
        target: TargetSpec | dict[str, Any],
        op: str,
        *,
        chain: int | None = None,
        instance: int | None = None,
        base_addr: int = 0,
        queue_timeout: float = 30.0,
        on_event: EventSink | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """One EIO operation: ``probe``, ``read``, ``read_outputs``,
        ``write`` (value) or ``set_bit`` (bit, level)."""
        r = self.request(
            "eio", target=self._target(target), action=op, chain=chain, instance=instance,
            base_addr=base_addr, queue_timeout=queue_timeout, on_event=on_event, **fields,
        )["result"]
        return {**r, "core": CoreRef.from_dict(r["core"])}

    def axi(
        self,
        target: TargetSpec | dict[str, Any],
        op: str,
        *,
        chain: int | None = None,
        queue_timeout: float = 30.0,
        on_event: EventSink | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """One EJTAG-AXI operation: ``read`` (addr), ``write`` (addr, data,
        wstrb), ``dump`` (addr, count, burst) or ``write_block`` (addr,
        words, burst)."""
        r = self.request(
            "axi", target=self._target(target), action=op, chain=chain,
            queue_timeout=queue_timeout, on_event=on_event, **fields,
        )["result"]
        return {**r, "core": CoreRef.from_dict(r["core"])}

    def last_capture(
        self,
        target: TargetSpec | dict[str, Any],
        *,
        chain: int = 1,
        instance: int | None = None,
    ) -> BrokerCapture | None:
        """The last capture any client took on the core, or None."""
        snap = self.request(
            "last_capture", target=self._target(target), chain=chain, instance=instance
        )["snapshot"]
        return None if snap is None else _capture_from(snap, snap.get("job"))

    def status(self) -> dict[str, Any]:
        msg = self.request("status")
        return {k: v for k, v in msg.items() if k not in ("id", "ok")}

    def stop(self, *, force: bool = False) -> None:
        self.request("stop", force=force)


def _capture_from(payload: dict[str, Any], job: int | None) -> BrokerCapture:
    return BrokerCapture(
        result=wire.result_from_dict(payload["result"]),
        core=CoreRef.from_dict(payload["core"]),
        timestamp_w=int(payload.get("timestamp_w") or 0),
        capture_gen=payload.get("capture_gen"),
        job=job,
    )
