# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""The broker runtime: one headless process per user that owns the cables.

Started by the first client that needs it (see :mod:`fcapz.broker.session`)
as ``python -m fcapz.broker --dir DIR``.  One runtime per directory
wins an OS-held lock on ``runtime.lock``; a second one exits with code 3
and its starter connects to the winner.  A runtime whose starter has gone
(it holds a lock on ``starter-<id>.lock`` while it waits) before any client
said hello leaves on its own: nobody ever has to kill a runtime.

It listens on a local IPC endpoint (a named pipe on Windows, a Unix socket
elsewhere) through :mod:`multiprocessing.connection`.  Every connection must
pass the HMAC challenge with the key in ``runtime.json`` (written 0600 into
the per-user directory) before it is served; messages are JSON frames, never
pickle.  On POSIX the directory and ``runtime.json`` must belong to the user
and be writable by nobody else, or both sides refuse them.  Each target
(cable) gets one :class:`~fcapz.broker.operations.Engine`.
A client that disconnects has its jobs cancelled.  The runtime exits
``--idle-exit`` seconds (default 60) after its last client and job.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import itertools
import json
import logging
import os
import queue
import secrets
import socket
import sys
import tempfile
import threading
import time
import uuid
from multiprocessing import connection as mpc
from pathlib import Path
from typing import Any, Callable

from .._version import __version__
from . import wire
from .coreref import TargetSpec
from .operations import Engine, Job

log = logging.getLogger(__name__)

IDLE_EXIT_S = 60.0
EXIT_ALREADY_RUNNING = 3
INFO_NAME = "runtime.json"
LOCK_NAME = "runtime.lock"
LOG_NAME = "runtime.log"
SOCK_NAME = "broker.sock"
MAX_FRAME = 64 << 20
#: Longest Unix socket path used, in bytes (sun_path holds 104 on macOS).
SOCK_PATH_MAX = 100
#: How long a connection may take to authenticate and say hello.
HELLO_TIMEOUT_S = 10.0
#: How often a Unix socket's accept() returns to look at the stop flag.
ACCEPT_POLL_S = 0.2
#: How often a runtime checks that its directory still names it, and how many
#: checks in a row must fail before it leaves.
OWN_CHECK_S = 1.0
OWN_CHECK_MISSES = 3

_JOB_FIELDS = (
    "chain", "instance", "base_addr", "timeout", "action", "value", "bit", "level",
    "addr", "data", "wstrb", "count", "words", "burst", "core",
)


def default_dir() -> Path:
    """The per-user runtime directory (``FCAPZ_BROKER_DIR`` overrides it),
    as an absolute path: the runtime runs with another working directory."""
    env = os.environ.get("FCAPZ_BROKER_DIR")
    if env:
        return Path(os.path.abspath(env))
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "fcapz" / "broker"
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / "fcapz-broker"
    return Path(tempfile.gettempdir()) / f"fcapz-broker-{os.getuid()}"


def _refuse_foreign(st: os.stat_result, what: Path) -> None:
    """Raise unless *st* is this user's own (POSIX)."""
    if st.st_uid != os.getuid():
        raise wire.BrokerStartError(
            f"{what} belongs to another user (uid {st.st_uid}): refusing to use "
            "it for the fcapz broker; set FCAPZ_BROKER_DIR to a directory of your own"
        )


def _refuse_writable(st: os.stat_result, what: Path) -> None:
    if st.st_mode & 0o022:
        raise wire.BrokerStartError(
            f"{what} is writable by other users (mode {st.st_mode & 0o777:o}): "
            "refusing to use it for the fcapz broker (chmod go-w it, or set "
            "FCAPZ_BROKER_DIR to a private directory)"
        )


def _open_dir(directory: Path) -> int:
    """A descriptor of *directory* itself, never of a symbolic link's
    target: what is checked is then what is used (POSIX)."""
    try:
        return os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise wire.BrokerStartError(
            f"{directory} is not a directory (a symbolic link?): refusing to use "
            f"it for the fcapz broker ({exc})"
        ) from exc


def check_dir(directory: Path) -> None:
    """Refuse a runtime directory that is not private to this user: on
    POSIX it must be a real directory of the user's own that nobody else can
    write.  A directory that does not exist yet passes."""
    if os.name == "nt":
        return
    try:
        fd = _open_dir(directory)
    except FileNotFoundError:
        return
    try:
        st = os.fstat(fd)
    finally:
        os.close(fd)
    _refuse_foreign(st, directory)
    _refuse_writable(st, directory)


def ensure_dir(directory: Path) -> Path:
    """Create *directory* for this user only (0700 where POSIX modes apply).
    An existing one is checked before it is touched: it must be a real
    directory (not a symbolic link) of the user's own."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        fd = _open_dir(directory)
        try:
            st = os.fstat(fd)
            _refuse_foreign(st, directory)
            if st.st_mode & 0o077:
                os.fchmod(fd, 0o700)
        finally:
            os.close(fd)
    return directory


def _digest(directory: Path) -> str:
    who = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    text = f"{who}\0{os.path.normcase(str(directory.resolve()))}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _socket_path_fits(path: str) -> bool:
    # sun_path counts bytes, and a path may hold multi-byte characters.
    return len(os.fsencode(path)) <= SOCK_PATH_MAX


def endpoint(directory: Path, nonce: str) -> tuple[str, str]:
    """(family, address) of a new IPC endpoint for *directory*.

    A directory too deep for a Unix socket path gets its socket in a new
    private (0700, randomly named) directory, which the caller removes with
    the socket: under the system temporary directory, or under ``/tmp`` when
    that one is too deep as well."""
    if os.name == "nt":
        return "AF_PIPE", rf"\\.\pipe\fcapz-broker-{_digest(directory)}-{nonce}"
    path = str(directory / SOCK_NAME)
    if _socket_path_fits(path):
        return "AF_UNIX", path
    for base in (None, "/tmp"):
        private = tempfile.mkdtemp(prefix="fcapz-broker-", dir=base)
        os.chmod(private, 0o700)
        path = str(Path(private) / SOCK_NAME)
        if _socket_path_fits(path):
            return "AF_UNIX", path
        os.rmdir(private)
    raise OSError(f"no directory short enough for the broker's socket ({path})")


def read_info(directory: Path) -> dict[str, Any] | None:
    """``runtime.json`` of *directory*, or None without a readable one.

    On POSIX the file must be the user's own and writable by nobody else
    (checked on the open file): :class:`~fcapz.broker.wire.BrokerStartError`
    otherwise, since it names the endpoint and key a client then trusts."""
    path = directory / INFO_NAME
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    with os.fdopen(fd, "r", encoding="utf-8") as fh:
        if os.name != "nt":
            st = os.fstat(fd)
            _refuse_foreign(st, path)
            _refuse_writable(st, path)
        try:
            info = json.load(fh)
        except (OSError, ValueError):
            return None
    return info if isinstance(info, dict) else None


class ElectionLock:
    """An exclusive, non-blocking OS lock on a file, held until closed.

    The OS drops it when the process dies, so a crashed runtime never keeps
    the next one out.  The election's file itself is never deleted.
    """

    def __init__(self, path: Path, *, create: bool = True) -> None:
        if create:
            self._f = open(path, "a+b")  # noqa: SIM115 - held for the lifetime
        else:
            fd = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))
            self._f = os.fdopen(fd, "r+b")

    def try_acquire(self) -> bool:
        try:
            if os.name == "nt":
                import msvcrt

                self._f.seek(0)
                msvcrt.locking(self._f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def close(self) -> None:
        self._f.close()


def lock_held(directory: Path) -> bool:
    """Whether a runtime holds *directory*'s election lock: one that
    answers, one still starting, or one that is closing its cables after it
    has withdrawn ``runtime.json``."""
    return _locked(directory / LOCK_NAME)


def _locked(path: Path) -> bool:
    """Whether somebody holds the lock on *path*; False without the file,
    which is not created."""
    try:
        probe = ElectionLock(path, create=False)
    except OSError:
        return False
    try:
        return not probe.try_acquire()
    finally:
        probe.close()


def claim_path(directory: Path, spawn_id: str) -> Path:
    return directory / f"starter-{spawn_id}.lock"


class StarterClaim:
    """What a client holds from before it starts a runtime until it has
    connected to one or given up: an OS lock on ``starter-<id>.lock``.

    The runtime started with that id publishes itself only while the claim is
    held, and leaves when it is released (or its holder dies) before any
    client has said hello.  The decision is the runtime's own, taken under
    the lock it registers clients with: its starter never kills it, so a
    runtime that another client found in the meantime is never taken away,
    and neither is one that is closing its cables."""

    def __init__(self, directory: Path, spawn_id: str) -> None:
        self.path = claim_path(directory, spawn_id)
        self._lock = ElectionLock(self.path)
        if not self._lock.try_acquire():
            self._lock.close()
            raise OSError(f"{self.path} is locked by another process")

    def release(self) -> None:
        self._lock.close()
        for _ in range(25):
            try:
                self.path.unlink()
                return
            except FileNotFoundError:
                return
            except OSError:
                time.sleep(0.02)    # Windows: the runtime is looking at it


def starter_waits(directory: Path, spawn_id: str) -> bool:
    """Whether the client that started runtime *spawn_id* still holds its
    :class:`StarterClaim`."""
    return _locked(claim_path(directory, spawn_id))


class _Owned:
    """A file this runtime made, as the directory it was made in and its
    inode (POSIX).

    The directory is held open: when it is removed and made again (a
    deleted ``XDG_RUNTIME_DIR``), a path would lead to the next runtime's
    file of the same name, the descriptor never does.  A file of another
    inode under the old name is not ours either."""

    def __init__(self, path: Path, st: os.stat_result | None = None) -> None:
        self.path = Path(path)
        self.dir_fd: int | None = None
        if os.unlink in os.supports_dir_fd and os.stat in os.supports_dir_fd:
            self.dir_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        if st is None:
            st = self._stat()
        self.ident = (st.st_dev, st.st_ino)

    def _stat(self) -> os.stat_result:
        if self.dir_fd is not None:
            return os.stat(self.path.name, dir_fd=self.dir_fd, follow_symlinks=False)
        return os.lstat(self.path)

    def remove(self) -> None:
        """Unlink the file if it is still the one that was made."""
        try:
            st = self._stat()
            if (st.st_dev, st.st_ino) != self.ident:
                return
            if self.dir_fd is not None:
                os.unlink(self.path.name, dir_fd=self.dir_fd)
            else:
                os.unlink(self.path)
        except OSError:
            pass

    def remove_dir(self) -> None:
        """Remove the (private, by now empty) directory the file was in."""
        try:
            if self.dir_fd is not None:
                held, named = os.fstat(self.dir_fd), os.lstat(self.path.parent)
                if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
                    return
            os.rmdir(self.path.parent)
        except OSError:
            pass

    def close(self) -> None:
        if self.dir_fd is not None:
            os.close(self.dir_fd)
            self.dir_fd = None


class _UnixListener:
    """A listening Unix socket whose ``accept()`` returns connections as
    :mod:`multiprocessing.connection` does, and times out every
    ``ACCEPT_POLL_S``.  Unlike ``Listener`` it never unlinks its path: that
    path may by then be another runtime's (see :class:`_Owned`)."""

    def __init__(self, address: str, backlog: int) -> None:
        self._sock = socket.socket(socket.AF_UNIX)
        try:
            self._sock.bind(address)
            self._sock.listen(backlog)
            self._sock.settimeout(ACCEPT_POLL_S)
        except OSError:
            self._sock.close()
            raise

    def accept(self) -> Any:
        conn, _ = self._sock.accept()
        conn.setblocking(True)
        return mpc.Connection(conn.detach())

    def close(self) -> None:
        self._sock.close()


def default_transport_factory() -> Callable[[TargetSpec], Any]:
    """Build transports as the CLI does.  ``FCAPZ_BROKER_TRANSPORT_FACTORY``
    (``module:function``) replaces it, for tests."""
    env = os.environ.get("FCAPZ_BROKER_TRANSPORT_FACTORY")
    if env:
        module, _, func = env.partition(":")
        return getattr(importlib.import_module(module), func)

    def make(spec: TargetSpec) -> Any:
        from ..cli import _make_transport

        return _make_transport(argparse.Namespace(**spec.to_dict(), program=None))

    return make


class _Client:
    """One connection: a reader that serves requests and a writer that sends
    replies and job events, so a slow client never blocks a job."""

    def __init__(self, runtime: Runtime, conn: Any, cid: str) -> None:
        self.rt = runtime
        self.conn = conn
        self.id = cid
        self.pid: int | None = None
        self.name: str | None = None
        self.hello = False
        self._out: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._requests: dict[Any, tuple[Engine, Job]] = {}
        # A connection that never says hello would count as a client for
        # ever: it keeps the runtime from its idle exit and from a plain stop.
        self._hello_timer = threading.Timer(HELLO_TIMEOUT_S, self._expire)
        self._hello_timer.daemon = True

    def start(self) -> None:
        self._hello_timer.start()
        threading.Thread(target=self._reader, name=f"fcapz-client-{self.id}",
                         daemon=True).start()

    def _expire(self) -> None:
        if not self.hello:
            log.info("client %s did not say hello in %g s: dropped", self.id,
                     HELLO_TIMEOUT_S)
            wire.abort_connection(self.conn)

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "pid": self.pid, "name": self.name}

    def label(self) -> str:
        if not self.hello:
            return f"{self.id} (connecting)"
        return f"{self.id} pid {self.pid} {self.name or ''}".rstrip()

    def send(self, msg: dict[str, Any]) -> None:
        self._out.put(msg)

    def _writer(self) -> None:
        while True:
            msg = self._out.get()
            if msg is None:
                return
            try:
                self.conn.send_bytes(wire.encode(msg))
            except (OSError, EOFError, ValueError):
                return

    def _reader(self) -> None:
        try:
            # Authenticated here, not in accept(): a client that stalls in
            # the handshake holds up only its own thread.
            mpc.deliver_challenge(self.conn, self.rt.authkey)
            mpc.answer_challenge(self.conn, self.rt.authkey)
        except Exception:  # noqa: BLE001 - not one of ours, or gone
            log.info("client %s failed authentication", self.id)
            self._close()
            return
        threading.Thread(target=self._writer, name=f"fcapz-send-{self.id}",
                         daemon=True).start()
        try:
            while True:
                raw = self.conn.recv_bytes(MAX_FRAME)
                try:
                    msg = wire.decode(raw)
                except ValueError as exc:
                    self.send({"id": None, "ok": False, "error": wire.error_dict(exc)})
                    continue
                self._dispatch(msg)
        except (EOFError, OSError):
            pass
        finally:
            cancelled = sum(e.cancel_owner(self.id) for e in self.rt.engines())
            if cancelled:
                log.info("client %s left: cancelled %d job(s)", self.id, cancelled)
            self._out.put(None)
            self._close()

    def _close(self) -> None:
        self._hello_timer.cancel()
        try:
            self.conn.close()
        except OSError:
            pass
        self.rt.drop_client(self)

    def _reply(self, rid: Any, **payload: Any) -> None:
        self.send({"id": rid, "ok": True, **payload})

    def _dispatch(self, msg: dict[str, Any]) -> None:
        rid = msg.get("id")
        op = msg.get("op")
        try:
            if msg.get("v") != wire.PROTOCOL:
                raise wire.BrokerError(
                    f"broker protocol {msg.get('v')!r} not supported (the runtime "
                    f"speaks {wire.PROTOCOL}, fcapz {__version__})"
                )
            if op == "hello":
                self.pid = msg.get("pid")
                self.name = msg.get("name")
                self.rt.said_hello(self)
                self._hello_timer.cancel()
                self._reply(rid, **self.rt.identity())
            elif not self.hello:
                raise wire.BrokerError("send hello first")
            elif op in ("capture", "probe", "eio", "axi"):
                self._submit(rid, op, msg)
            elif op == "cancel":
                with self._lock:
                    entry = self._requests.get(msg.get("request"))
                done = bool(entry and entry[0].cancel(entry[1].id, owner=self.id))
                self._reply(rid, cancelled=done)
            elif op == "last_capture":
                eng = self.rt.find_engine(TargetSpec.from_dict(msg.get("target") or {}))
                snap = None if eng is None else eng.last_capture(msg)
                self._reply(rid, snapshot=None if snap is None else _capture_payload(snap))
            elif op == "status":
                self._reply(rid, **self.rt.status())
            elif op == "stop":
                busy = sum(e.active_jobs() for e in self.rt.engines())
                if busy and not msg.get("force"):
                    raise wire.BrokerError(
                        f"{busy} job(s) are running; stop with force to cancel them"
                    )
                # A connected client may be between two jobs (a capture's
                # probe and its capture) or about to send one, also one that
                # has not said hello yet.
                force = bool(msg.get("force"))
                others = self.rt.begin_stop(self, force)
                deadline = time.monotonic() + 0.5   # one may just be leaving
                while others and time.monotonic() < deadline:
                    time.sleep(0.02)
                    others = self.rt.begin_stop(self, force)
                if others:
                    raise wire.BrokerError(
                        f"{len(others)} other client(s) are connected "
                        f"({', '.join(others)}); stop with force to drop them"
                    )
                self._reply(rid, stopping=True)
                self.rt.stop(delay=0.2)
            else:
                raise ValueError(f"unknown broker op {op!r}")
        except Exception as exc:  # noqa: BLE001 - every error goes back
            self.send({"id": rid, "ok": False, "error": wire.error_dict(exc)})

    def _submit(self, rid: Any, op: str, msg: dict[str, Any]) -> None:
        eng = self.rt.engine_for(TargetSpec.from_dict(msg.get("target") or {}))
        params = {k: msg[k] for k in _JOB_FIELDS if k in msg}
        if "action" in params:      # the EIO/AXI operation ("op" is the request's)
            params["op"] = params.pop("action")
        if op == "capture":
            params["config"] = wire.config_from_dict(msg["config"])
        ready = threading.Event()
        box: dict[str, Job] = {}

        def on_event(ev: dict[str, Any]) -> None:
            if ev.get("event") == "end":
                ready.wait(5.0)
                self._finish(rid, box["job"])
            else:
                self.send({"id": rid, **ev})

        job = eng.submit(
            op, params, owner=self.id,
            queue_timeout=float(msg.get("queue_timeout", 30.0)),
            expect_gen=msg.get("expect_gen"),
            on_event=on_event,
        )
        box["job"] = job
        with self._lock:
            self._requests[rid] = (eng, job)
        ready.set()
        self.send({"id": rid, "event": "accepted", "job": job.id})

    def _finish(self, rid: Any, job: Job) -> None:
        with self._lock:
            self._requests.pop(rid, None)
        if job.error is not None:
            self.send({"id": rid, "ok": False, "job": job.id,
                       "error": wire.error_dict(job.error)})
            return
        try:
            payload = _capture_payload(job.result)
        except Exception as exc:  # noqa: BLE001 - reported, not lost
            self.send({"id": rid, "ok": False, "job": job.id, "error": wire.error_dict(exc)})
            return
        self.send({"id": rid, "ok": True, "job": job.id, "result": payload})


def _capture_payload(res: dict[str, Any]) -> dict[str, Any]:
    out = dict(res)
    if "core" in out and hasattr(out["core"], "to_dict"):
        out["core"] = out["core"].to_dict()
    if "result" in out:
        out["result"] = wire.result_to_dict(out["result"])
    return out


class Runtime:
    def __init__(
        self,
        directory: Path,
        *,
        idle_exit: float = IDLE_EXIT_S,
        transport_factory: Callable[[TargetSpec], Any] | None = None,
        spawn_id: str | None = None,
    ) -> None:
        self.dir = Path(directory)
        self.idle_exit = float(idle_exit)
        self.spawn_id = spawn_id
        self.runtime_id = uuid.uuid4().hex[:12]
        self.authority = f"local:{self.runtime_id}"
        self.authkey = secrets.token_bytes(32)
        self.started = time.time()
        self._factory = transport_factory or default_transport_factory()
        self._lock = threading.Lock()
        self._engines: dict[tuple, Engine] = {}
        self._clients: dict[str, _Client] = {}
        self._ids = itertools.count(1)
        self._stopping = threading.Event()
        # Set (with ``_lock``) once the runtime has decided to stop: no new
        # client is taken from then on.
        self._refusing = False
        # Set (with ``_lock``) when the engines are being closed: no engine
        # is created from then on.
        self._closing = False
        # Set (with ``_lock``) by the first client that says hello.
        self._served = False
        self.family: str | None = None
        self.address: str | None = None
        # POSIX: the socket and runtime.json, as this runtime made them.
        self._sock_file: _Owned | None = None
        self._info_file: _Owned | None = None

    # ---- registry ------------------------------------------------------

    def engines(self) -> list[Engine]:
        with self._lock:
            return list(self._engines.values())

    def find_engine(self, spec: TargetSpec) -> Engine | None:
        with self._lock:
            return self._engines.get(spec.identity())

    def engine_for(self, spec: TargetSpec) -> Engine:
        """The engine of *spec*'s cable, created on first use.

        A second client must drive the cable the same way, and a local USB
        adapter left to auto-select must not be opened beside a named one:
        it may be the same cable.
        """
        ident = spec.identity()
        with self._lock:
            if self._closing:
                # Created now, it would open a cable nobody closes.
                raise RuntimeError("the broker is shutting down")
            eng = self._engines.get(ident)
            if eng is not None:
                if eng.spec.settings() != spec.settings():
                    raise wire.TargetMismatch(
                        f"the broker already drives {spec.key()} with other "
                        f"transport settings ({eng.spec.settings()} vs "
                        f"{spec.settings()}); use the same options"
                    )
                return eng
            for other in self._engines.values():
                if other.spec.backend == spec.backend and (
                    other.spec.auto_selected() or spec.auto_selected()
                ):
                    raise wire.TargetMismatch(
                        f"{spec.key()} and {other.spec.key()} may be the same "
                        f"{spec.backend} adapter: name it with --hardware the same "
                        "way in every client"
                    )
            eng = Engine(spec, self._factory, authority=self.authority)
            self._engines[ident] = eng
            return eng

    def drop_client(self, client: _Client) -> None:
        with self._lock:
            self._clients.pop(client.id, None)

    def said_hello(self, client: _Client) -> None:
        with self._lock:
            client.hello = True
            self._served = True

    def begin_stop(self, client: _Client, force: bool) -> list[str]:
        """Commit to stopping for *client*, or return the other connections
        that stand in the way (none with *force*).

        One step under the lock the accept loop registers connections with:
        every other connection is either seen here, said hello or not, or is
        refused from now on.  None is taken and then dropped."""
        with self._lock:
            others = [c.label() for c in self._clients.values() if c is not client]
            if others and not force:
                return others
            self._refusing = True
            return []

    def close_engines(self) -> None:
        """Close every engine; none is created afterwards."""
        with self._lock:
            self._closing = True
            engines = list(self._engines.values())
        for eng in engines:
            eng.close()

    def identity(self) -> dict[str, Any]:
        return {
            "runtime_id": self.runtime_id,
            "pid": os.getpid(),
            "protocol": wire.PROTOCOL,
            "version": __version__,
            "started": self.started,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            clients = [c.describe() for c in self._clients.values()]
        return {
            **self.identity(),
            "uptime": time.time() - self.started,
            "idle_exit": self.idle_exit,
            "dir": str(self.dir),
            "clients": clients,
            "targets": [e.status() for e in self.engines()],
        }

    # ---- lifetime ------------------------------------------------------

    def stop(self, delay: float = 0.0) -> None:
        """Ask :meth:`serve` to return (after *delay*, so a reply can go out).
        New clients are refused from now on."""
        with self._lock:
            self._refusing = True

        def go() -> None:
            if delay:
                time.sleep(delay)
            self._stopping.set()
            # A pipe's accept() is woken with a bare connection, closed at
            # once.  A Unix socket's times out by itself: its path may be
            # gone, or lead to another runtime by now.
            if self.family == "AF_PIPE":
                try:
                    mpc.Client(self.address, self.family).close()
                except Exception:  # noqa: BLE001 - accept is not waiting
                    pass

        threading.Thread(target=go, daemon=True).start()

    def _starter_waits(self) -> bool:
        return self.spawn_id is None or starter_waits(self.dir, self.spawn_id)

    def _owns_directory(self) -> bool:
        """Whether ``runtime.json`` still names this runtime."""
        try:
            info = read_info(self.dir)
        except wire.BrokerError:
            return False
        return bool(info) and info.get("runtime_id") == self.runtime_id

    def _idle_watch(self) -> None:
        idle_since = time.monotonic()
        next_check = idle_since + OWN_CHECK_S
        misses = 0
        while not self._stopping.wait(0.2):
            # Started for a client that has given up, and found by no other:
            # leave.  Decided as the idle exit below is.
            if not self._served and not self._starter_waits():
                with self._lock:
                    unused = not self._clients and not self._served
                    if unused:
                        self._refusing = True
                if unused:
                    log.info("the client that started this runtime has left and "
                             "no other came: exiting")
                    self.stop()
                    return
            # A runtime whose directory was removed (a deleted
            # XDG_RUNTIME_DIR), or names another runtime, can be found by
            # no client: it leaves, busy or not, and frees its cables.
            if time.monotonic() >= next_check:
                next_check = time.monotonic() + OWN_CHECK_S
                misses = 0 if self._owns_directory() else misses + 1
                if misses >= OWN_CHECK_MISSES:
                    log.warning("%s no longer names this runtime: exiting",
                                self.dir / INFO_NAME)
                    self.stop()
                    return
            # Decided with the lock the accept loop registers clients under:
            # a client is either seen here or refused, never dropped.
            with self._lock:
                busy = bool(self._clients) or any(
                    e.active_jobs() for e in self._engines.values()
                )
                now = time.monotonic()
                if busy:
                    idle_since = now
                    continue
                if now - idle_since < self.idle_exit:
                    continue
                self._refusing = True
            log.info("idle for %.0f s: exiting", self.idle_exit)
            self.stop()
            return

    def _write_info(self) -> None:
        data = {
            **self.identity(),
            "family": self.family,
            "address": self.address,
            "authkey": self.authkey.hex(),
            # Lets the client that started this runtime tell it from another
            # starter's, whose leftover spawn it then stops.
            "spawn_id": self.spawn_id,
        }
        tmp = self.dir / f"{INFO_NAME}.{os.getpid()}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
            made = os.fstat(fd)
        for attempt in range(40):
            try:
                os.replace(tmp, self.dir / INFO_NAME)
                break
            except PermissionError:
                # Windows: a client is reading a dead runtime's file.
                if attempt == 39:
                    raise
                time.sleep(0.05)
        if os.name != "nt":
            self._info_file = _Owned(self.dir / INFO_NAME, made)

    def _remove_info(self) -> None:
        if os.name != "nt":
            if self._info_file is not None:
                self._info_file.remove()
            return
        info = read_info(self.dir)
        if info and info.get("runtime_id") == self.runtime_id:
            for _ in range(40):
                try:
                    (self.dir / INFO_NAME).unlink()
                    return
                except PermissionError:
                    time.sleep(0.05)    # Windows: a client is reading it
                except OSError:
                    return

    def serve(self) -> int:
        """Win the election, listen, serve until stopped or idle; the exit code."""
        ensure_dir(self.dir)
        election = ElectionLock(self.dir / LOCK_NAME)
        if not election.try_acquire():
            election.close()
            log.info("another runtime holds %s", self.dir / LOCK_NAME)
            return EXIT_ALREADY_RUNNING
        listener: Any = None
        try:
            if not self._starter_waits():
                log.info("the client that started this runtime has left: not needed")
                return 0
            self.family, self.address = endpoint(self.dir, secrets.token_hex(4))
            if self.family == "AF_UNIX":
                if os.path.exists(self.address):
                    os.unlink(self.address)  # a dead runtime's: we hold the lock
                listener = _UnixListener(self.address, backlog=16)
                self._sock_file = _Owned(Path(self.address))
            else:
                listener = mpc.Listener(self.address, self.family)
            self._write_info()
            log.info("runtime %s (pid %d, fcapz %s) on %s", self.runtime_id,
                     os.getpid(), __version__, self.address)
            threading.Thread(target=self._idle_watch, name="fcapz-idle", daemon=True).start()
            while not self._stopping.is_set():
                try:
                    conn = listener.accept()
                except OSError as exc:
                    if self._stopping.is_set():
                        break
                    if isinstance(exc, (TimeoutError, socket.timeout)):
                        continue
                    log.warning("accept failed", exc_info=True)
                    time.sleep(0.1)
                    continue
                if self._stopping.is_set():
                    conn.close()
                    break
                client = _Client(self, conn, f"c{next(self._ids)}")
                with self._lock:
                    refused = self._refusing
                    if not refused:
                        self._clients[client.id] = client
                if refused:
                    # Stopping: this client starts the next runtime.
                    conn.close()
                    continue
                client.start()
        finally:
            # The endpoint and runtime.json go first, so a new client learns
            # at once that this runtime is leaving; the election lock goes
            # last, when the cables are closed and the next runtime may open
            # them.  A client that comes in between waits for that (see
            # BrokerSession._start).
            self._stopping.set()
            with self._lock:
                self._refusing = True
            if listener is not None:
                try:
                    listener.close()
                except OSError:
                    pass
            # Only what is still this runtime's own is removed: after its
            # directory was removed and made again, the same names there are
            # the next runtime's.
            if self._sock_file is not None:
                self._sock_file.remove()
                if self._sock_file.path.parent != self.dir:
                    self._sock_file.remove_dir()
                self._sock_file.close()
            self._remove_info()
            if self._info_file is not None:
                self._info_file.close()
            self.close_engines()
            if self.spawn_id and not starter_waits(self.dir, self.spawn_id):
                try:    # left by a starter that died
                    claim_path(self.dir, self.spawn_id).unlink()
                except OSError:
                    pass
            election.close()
            log.info("runtime %s stopped", self.runtime_id)
        return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m fcapz.broker")
    p.add_argument("--dir", type=Path, default=None, help="runtime directory")
    p.add_argument(
        "--idle-exit", type=float,
        default=float(os.environ.get("FCAPZ_BROKER_IDLE_EXIT", IDLE_EXIT_S)),
        metavar="SEC", help="exit this long after the last client and job",
    )
    p.add_argument("--spawn-id", default=None, help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    directory = ensure_dir(Path(os.path.abspath(args.dir)) if args.dir else default_dir())
    logging.basicConfig(
        filename=str(directory / LOG_NAME),
        level=logging.INFO,
        format="%(asctime)s %(process)d %(levelname)s %(name)s: %(message)s",
    )
    try:
        return Runtime(directory, idle_exit=args.idle_exit, spawn_id=args.spawn_id).serve()
    except Exception:
        log.exception("runtime failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
