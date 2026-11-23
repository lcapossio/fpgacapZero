# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""The broker's operations engine: whole operations per core, one at a time.

An :class:`Engine` owns the one transport of a target (cable) and runs jobs
on it:

- ``capture``: apply the full configuration, arm, wait for the trigger,
  read the capture back, publish it as the core's last snapshot.
- ``eio``: one EIO access or read-modify-write (``set_bit``).
- ``axi``: one EJTAG-AXI bridge transaction or block transfer.
- ``probe``: read an ELA's or EIO's identity and geometry.

Each core has a FIFO queue; the job at its head owns the core, so another
client's capture cannot reconfigure, re-arm or read a capture this one armed.
Jobs join their core's queue in the order :meth:`Engine.submit` took them,
whatever their threads do: a job finds its core (which may read the board)
only when every job submitted before it has joined a queue.
Cores on the same cable run interleaved: the cable is the transport's own
:meth:`~fcapz.transport.Transport.transaction_lock`, held for each register
access and released between trigger polls.  ``probe`` reads registers only
and takes no core ownership.

A job that has not reached the head of its queue by its deadline fails with
:class:`~fcapz.broker.wire.CoreBusy`.  Cancelling a job (or its client going
away) stops only that job, and the job keeps the core until its own access
has stopped; a capture cancelled while it waits for its trigger is driven
idle first.  A failure that the link itself caused marks the connection
stale (a wrong chain or a missing core is the job's own error and leaves the
connection to the others): the next job waits for the jobs still running on it to end, then
reconnects, which raises the target's image generation.  Nothing is retried
or re-armed on its own.
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
from collections import deque
from typing import Any, Callable

from ..analyzer import (
    _ADDR_STARTUP_ARM,
    _ADDR_VERSION,
    Analyzer,
    CaptureChangedError,
    CaptureConfig,
    CaptureNotReady,
    CommandPendingError,
)
from ..eio import EioController
from ..ejtagaxi import EjtagAxiController
from ..transport import ManagerResetError
from .coreref import CoreRef, TargetSpec
from .wire import CoreBusy, ImageChanged, JobCancelled, TargetMismatch

log = logging.getLogger(__name__)

_job_ids = itertools.count(1)

#: Trigger poll spacing of a capture job; the cable is free in between.
POLL_INTERVAL_S = 0.02

#: How long a job that needs a reconnect waits for the jobs still running on
#: the stale connection to end.
RECOVERY_WAIT_S = 30.0

# Failures of the operation, not of the link: the connection stays.
_LOGICAL_ERRORS = (
    CaptureNotReady,      # a TimeoutError, so an OSError: not a dead link
    JobCancelled,
    CoreBusy,
    ImageChanged,
    TargetMismatch,
    ValueError,
    KeyError,
    NotImplementedError,
    ManagerResetError,
    CaptureChangedError,
    CommandPendingError,
)
# Failures that are the link's for certain.
_LINK_ERRORS = (ConnectionError, EOFError)

EventSink = Callable[[dict[str, Any]], None]


class Job:
    """One operation submitted to an :class:`Engine`."""

    def __init__(
        self,
        kind: str,
        params: dict[str, Any],
        *,
        owner: str,
        queue_timeout: float,
        expect_gen: int | None,
        on_event: EventSink | None,
    ) -> None:
        self.id = next(_job_ids)
        self.kind = kind
        self.params = params
        self.owner = owner
        self.queue_timeout = float(queue_timeout)
        # From submit: the wait for the jobs submitted before counts too.
        self.deadline = time.monotonic() + self.queue_timeout
        self.expect_gen = expect_gen
        self.on_event = on_event
        self.state = "new"
        self.core: tuple | None = None
        self.holding = False
        self.cancel_event = threading.Event()
        self.done_event = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None

    def cancel(self) -> None:
        self.cancel_event.set()

    def wait(self, timeout: float | None = None) -> Any:
        """Block until the job ends; return its result or raise its error."""
        if not self.done_event.wait(timeout):
            raise TimeoutError(f"job {self.id} still running")
        if self.error is not None:
            raise self.error
        return self.result

    def describe(self) -> dict[str, Any]:
        return {"job": self.id, "kind": self.kind, "owner": self.owner, "state": self.state}

    def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event({"job": self.id, **event})
        except Exception:  # noqa: BLE001 - a dead client must not kill the job
            log.debug("event sink for job %s failed", self.id, exc_info=True)


TransportFactory = Callable[[TargetSpec], Any]


class Engine:
    """Runs jobs on one target's transport.  Thread-safe."""

    def __init__(
        self,
        spec: TargetSpec,
        transport_factory: TransportFactory,
        *,
        authority: str = "local",
    ) -> None:
        self.spec = spec
        self.authority = authority
        self._factory = transport_factory
        self._transport: Any = None
        self.image_gen = 0
        self._needs_open = True
        # Serializes (re)connects and controller creation.
        self._conn_lock = threading.Lock()
        # Guards everything below, and is what queued jobs wait on.
        self._cv = threading.Condition()
        self._stale = True
        self._holders = 0
        self._queues: dict[tuple, deque[Job]] = {}
        self._jobs: dict[int, Job] = {}
        self._controllers: dict[tuple, Any] = {}
        self._snapshots: dict[tuple, dict[str, Any]] = {}
        self._snapshot_seq = itertools.count(1)
        # Jobs in submit order that have not joined a core queue yet.
        self._admission: deque[Job] = deque()
        # An ELA/EIO controller that has answered on this connection: what
        # a link check reads, whatever chain the failed job named.
        self._proven: Any = None
        self._closed = False

    # ---- connection --------------------------------------------------

    def _connect_locked(self) -> None:
        """With ``_conn_lock``: reconnect if stale, once the jobs still on
        the old connection have ended."""
        with self._cv:
            if self._closed:
                raise RuntimeError("the broker is shutting down")
            if not self._stale:
                return
            deadline = time.monotonic() + RECOVERY_WAIT_S
            while self._holders:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(
                        f"{self.spec.key()} is recovering from a failed connection "
                        f"and {self._holders} job(s) are still running on it"
                    )
                self._cv.wait(min(remaining, 0.1))
            old, self._transport = self._transport, None
            self._controllers.clear()
            self._proven = None
        if old is not None:
            try:
                old.close()
            except Exception:  # noqa: BLE001 - it is being replaced
                log.debug("closing the stale transport failed", exc_info=True)
        transport = self._factory(self.spec)
        with self._cv:
            self._transport = transport
            self._needs_open = True
            self._stale = False
            self.image_gen += 1
        log.info("target %s: connection %d", self.spec.key(), self.image_gen)

    def _hold(self, job: Job) -> None:
        with self._cv:
            self._holders += 1
            job.holding = True

    def _get_controller(self, job: Job, kind: str, *, cached: bool) -> tuple[Any, tuple]:
        """The controller *job* runs on, and its core key, with the job
        counted as running on this connection.

        The first controller after a (re)connect opens the transport with its
        own ``connect()``, which selects its chain first as every backend
        needs; the rest ``attach()``.  A slot left out is resolved here, so
        the key names the core the job really reaches (an ELA binds the
        manager's first ELA slot, an EIO its first EIO slot).
        """
        p = job.params
        chain = p.get("chain")
        instance = p.get("instance")
        base_addr = int(p.get("base_addr") or 0)
        req = (kind, chain, instance, base_addr)
        with self._conn_lock:
            self._connect_locked()
            ctrl = self._controllers.get(req) if cached else None
            if ctrl is None:
                ctrl = self._new_controller(kind, chain, instance, base_addr)
                if cached:
                    self._controllers[req] = ctrl
            self._hold(job)
        return ctrl, self._core_key(kind, ctrl, base_addr)

    def _new_controller(self, kind, chain, instance, base_addr):
        t = self._transport
        if kind == "ela":
            ctrl = Analyzer(t, chain=1 if chain is None else int(chain), instance=instance)
        elif kind == "eio":
            ctrl = EioController(t, chain=chain, instance=instance, base_addr=base_addr)
        elif kind == "axi":
            ctrl = EjtagAxiController(t, chain=self._axi_chain(chain))
        else:
            raise ValueError(f"unknown core kind {kind!r}")
        try:
            if self._needs_open:
                ctrl.connect()
                self._needs_open = False
            else:
                ctrl.attach()
        except Exception as exc:
            # A wrong chain or a missing core is this job's error: only a
            # link that no longer answers takes the connection down.
            if not self._link_alive(exc, ctrl):
                with self._cv:
                    self._stale = True
            raise
        if self._proven is None and isinstance(ctrl, (Analyzer, EioController)):
            self._proven = ctrl
        return ctrl

    @staticmethod
    def _axi_chain(chain: Any) -> int:
        return 4 if chain is None else int(chain)

    @staticmethod
    def _core_key(kind: str, ctrl: Any, base_addr: int) -> tuple:
        if kind == "axi":
            return (kind, ctrl._chain, None, 0)  # noqa: SLF001 - no public accessor
        return (kind, ctrl.bscan_chain, ctrl.instance, base_addr)

    def core_ref(self, key: tuple) -> CoreRef:
        kind, chain, slot, _ = key
        return CoreRef(self.authority, self.spec.key(), kind, chain, slot, self.image_gen)

    # ---- jobs ----------------------------------------------------------

    def submit(
        self,
        kind: str,
        params: dict[str, Any],
        *,
        owner: str,
        queue_timeout: float = 30.0,
        expect_gen: int | None = None,
        on_event: EventSink | None = None,
    ) -> Job:
        """Start *kind* (``capture``, ``eio``, ``axi`` or ``probe``) in its own
        thread and return its :class:`Job`."""
        if kind not in ("capture", "eio", "axi", "probe"):
            raise ValueError(f"unknown job kind {kind!r}")
        job = Job(
            kind, params, owner=owner, queue_timeout=queue_timeout,
            expect_gen=expect_gen, on_event=on_event,
        )
        with self._cv:
            if self._closed:
                raise RuntimeError("the broker is shutting down")
            self._jobs[job.id] = job
            if kind != "probe":
                self._admission.append(job)
        threading.Thread(target=self._run, args=(job,), name=f"fcapz-job-{job.id}",
                         daemon=True).start()
        return job

    def _run(self, job: Job) -> None:
        ctrl_box: list[Any] = []
        try:
            job.result = self._execute(job, ctrl_box)
            job.state = "done"
        except BaseException as exc:  # noqa: BLE001 - delivered to the client
            job.error = exc
            job.state = "cancelled" if isinstance(exc, JobCancelled) else "failed"
            ctrl = ctrl_box[0] if ctrl_box else None
            if job.holding and not self._link_alive(exc, ctrl):
                log.warning("target %s: link failed in job %s: %s",
                            self.spec.key(), job.id, exc)
                with self._cv:
                    self._stale = True
        finally:
            with self._cv:
                self._jobs.pop(job.id, None)
                if job in self._admission:
                    self._admission.remove(job)
                if job.holding:
                    job.holding = False
                    self._holders -= 1
                self._cv.notify_all()
            job.done_event.set()
            job._emit({"event": "end", "state": job.state})

    def _link_alive(self, exc: BaseException, ctrl: Any) -> bool:
        """Whether the connection survived *exc*, raised on *ctrl*: logical
        failures leave it, link errors do not, and anything else is checked
        with a VERSION read.

        The read goes to a core that has already answered on this connection
        when there is one, not to the one the failed job named: a chain or
        virtual-JTAG instance that does not exist fails every read, on a
        cable that is fine.  Without one, *ctrl* itself is read if it is an
        ELA/EIO (an EJTAG-AXI chain has no such read)."""
        if isinstance(exc, _LOGICAL_ERRORS):
            return True
        if isinstance(exc, _LINK_ERRORS):
            return False
        ctrl = self._proven or ctrl
        if not isinstance(ctrl, (Analyzer, EioController)):
            return not isinstance(exc, OSError)
        try:
            with ctrl._selected():  # noqa: SLF001 - the controller's own scope
                base = getattr(ctrl, "_base_addr", 0)
                transport = ctrl.transport if isinstance(ctrl, Analyzer) else ctrl._t
                transport.read_reg(base | _ADDR_VERSION)
        except Exception:  # noqa: BLE001 - the link is gone
            return False
        return True

    def _check_gen(self, job: Job) -> None:
        if job.expect_gen is not None and job.expect_gen != self.image_gen:
            raise ImageChanged(
                f"{self.spec.key()} was reconnected (image generation "
                f"{job.expect_gen} -> {self.image_gen}): look the core up again"
            )

    def _execute(self, job: Job, ctrl_box: list[Any]) -> Any:
        if job.kind == "probe":
            return self._probe(job, ctrl_box)
        axi = job.kind == "axi"
        ctrl: Any = None
        self._await_admission(job)
        try:
            if axi:
                # An EJTAG-AXI attach resets and primes the bridge: only
                # under ownership of the bridge, never ahead of the queue.
                key = ("axi", self._axi_chain(job.params.get("chain")), None, 0)
            else:
                kind = "ela" if job.kind == "capture" else job.kind
                ctrl, key = self._get_controller(job, kind, cached=True)
                ctrl_box.append(ctrl)
            job.core = key
            self._enqueue(job, key)
        finally:
            self._leave_admission(job)
        try:
            self._wait_turn(job, key)
            if axi:
                ctrl, _ = self._get_controller(job, "axi", cached=False)
                ctrl_box.append(ctrl)
            return self._start_and_run(job, key, ctrl)
        finally:
            self._release(job, key)

    def _start_and_run(self, job: Job, key: tuple, ctrl: Any) -> Any:
        if job.cancel_event.is_set():
            raise JobCancelled(f"job {job.id} cancelled")
        self._check_gen(job)
        job.state = "running"
        job._emit({"event": "running", "core": self.core_ref(key).to_dict()})
        if job.kind == "capture":
            return self._capture(job, ctrl, key)
        if job.kind == "eio":
            return self._eio(job, ctrl, key)
        return self._axi(job, ctrl, key)

    def _await_admission(self, job: Job) -> None:
        """Wait until every job submitted before *job* has joined a core
        queue (or ended), so queues fill in submit order."""
        with self._cv:
            while self._admission and self._admission[0] is not job:
                if job.cancel_event.is_set():
                    raise JobCancelled(f"job {job.id} cancelled while queued")
                remaining = job.deadline - time.monotonic()
                if remaining <= 0:
                    head = self._admission[0]
                    raise CoreBusy(
                        f"{self.spec.key()} is busy: job {job.id} waited "
                        f"{job.queue_timeout:g} s behind job {head.id} "
                        f"({head.kind}, client {head.owner}), which is still "
                        "looking up its core"
                    )
                self._cv.wait(min(remaining, 0.1))

    def _leave_admission(self, job: Job) -> None:
        with self._cv:
            if job in self._admission:
                self._admission.remove(job)
            self._cv.notify_all()

    def _enqueue(self, job: Job, key: tuple) -> None:
        with self._cv:
            self._queues.setdefault(key, deque()).append(job)
            job.state = "queued"

    def _wait_turn(self, job: Job, key: tuple) -> None:
        """Wait until *job*, already in its core's queue, is at its head."""
        deadline = job.deadline
        with self._cv:
            q = self._queues[key]
            reported = None
            try:
                while q[0] is not job:
                    head = q[0]
                    if reported is not head.id:
                        reported = head.id
                        job._emit({"event": "queued", "behind": head.describe(),
                                   "position": q.index(job)})
                    if job.cancel_event.is_set():
                        raise JobCancelled(f"job {job.id} cancelled while queued")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise CoreBusy(
                            f"{self.core_ref(key)} is busy: job {job.id} waited "
                            f"{job.queue_timeout:g} s behind job {head.id} "
                            f"({head.kind}, client {head.owner})"
                        )
                    self._cv.wait(min(remaining, 0.1))
            except BaseException:
                q.remove(job)
                if not q:
                    del self._queues[key]
                self._cv.notify_all()
                raise

    def _release(self, job: Job, key: tuple) -> None:
        with self._cv:
            q = self._queues.get(key)
            if q is not None and job in q:
                q.remove(job)
                if not q:
                    del self._queues[key]
            self._cv.notify_all()

    # ---- operations ----------------------------------------------------

    def _probe(self, job: Job, ctrl_box: list[Any]) -> dict[str, Any]:
        kind = job.params.get("core", "ela")
        if kind not in ("ela", "eio"):
            raise ValueError(f"probe: core must be 'ela' or 'eio', not {kind!r}")
        # A fresh controller: a probe must not touch the state of the
        # controller a running job uses.
        ctrl, key = self._get_controller(job, kind, cached=False)
        ctrl_box.append(ctrl)
        job.core = key
        self._check_gen(job)
        if kind == "ela":
            info = ctrl.probe()
        else:
            info = {"in_w": ctrl.in_w, "out_w": ctrl.out_w, "chain": ctrl.bscan_chain,
                    "instance": ctrl.instance}
        return {"core": self.core_ref(key), "info": info}

    def _capture(self, job: Job, analyzer: Analyzer, key: tuple) -> dict[str, Any]:
        cfg: CaptureConfig = job.params["config"]
        timeout = float(job.params.get("timeout", 10.0))
        analyzer.configure(cfg)
        analyzer.arm()
        deadline = time.monotonic() + timeout
        while True:
            if job.cancel_event.is_set():
                # Idle before giving the core up, so the next owner does not
                # find this capture running.
                self._disarm(job, analyzer, cfg)
                raise JobCancelled(f"job {job.id} cancelled while waiting for the trigger")
            if analyzer.status()["done"]:
                break
            if time.monotonic() >= deadline:
                raise CaptureNotReady("capture did not complete within timeout")
            time.sleep(POLL_INTERVAL_S)
        result = analyzer.capture(timeout=max(1.0, timeout))
        out = {
            "core": self.core_ref(key),
            "result": result,
            "timestamp_w": int(getattr(analyzer, "_hw_timestamp_w", 0)),
            "capture_gen": getattr(analyzer, "_armed_gen", None),
        }
        with self._cv:
            self._snapshots[key] = {**out, "job": job.id, "owner": job.owner,
                                    "time": time.time(), "seq": next(self._snapshot_seq)}
        return out

    def _disarm(self, job: Job, analyzer: Analyzer, cfg: CaptureConfig) -> None:
        """Drive a cancelled capture's core to a verified idle.  A plain
        reset re-arms a core whose runtime STARTUP_ARM register is set, so
        that register is cleared first.  A link that fails here takes the
        connection down; a core that stays busy on a live link (a stopped
        sample clock) is logged and left to the next job to report."""
        try:
            if cfg.startup_arm:
                with analyzer._selected():  # noqa: SLF001 - the controller's own scope
                    analyzer.transport.write_reg(_ADDR_STARTUP_ARM, 0)
            analyzer.force_idle()
        except Exception as exc:  # noqa: BLE001 - the job ends as cancelled
            log.warning("job %s: could not idle the core after cancel", job.id,
                        exc_info=True)
            if not self._link_alive(exc, analyzer):
                with self._cv:
                    self._stale = True

    def _eio(self, job: Job, eio: EioController, key: tuple) -> dict[str, Any]:
        p = job.params
        op = p.get("op", "read")
        out: dict[str, Any] = {"core": self.core_ref(key)}
        if op == "probe":
            out.update(in_w=eio.in_w, out_w=eio.out_w, chain=eio.bscan_chain,
                       instance=eio.instance)
        elif op == "read":
            out["value"] = eio.read_inputs()
        elif op == "read_outputs":
            out["value"] = eio.read_outputs()
        elif op == "write":
            eio.write_outputs(int(p["value"]))
        elif op == "set_bit":
            eio.set_bit(int(p["bit"]), int(p["level"]))
        else:
            raise ValueError(f"unknown eio op {op!r}")
        return out

    def _axi(self, job: Job, axi: EjtagAxiController, key: tuple) -> dict[str, Any]:
        p = job.params
        op = p.get("op")
        addr = int(p.get("addr", 0))
        burst = bool(p.get("burst", False))
        out: dict[str, Any] = {"core": self.core_ref(key)}
        t = self._transport
        # One bridge transaction is many scans on the bridge's chain: hold
        # the cable for all of it.
        with t.transaction_lock():
            t.select_chain(axi._chain)  # noqa: SLF001 - no public accessor
            if op == "read":
                out["value"] = axi.axi_read(addr)
            elif op == "write":
                out["resp"] = axi.axi_write(addr, int(p["data"]), wstrb=int(p.get("wstrb", 0xF)))
            elif op == "dump":
                count = int(p["count"])
                out["words"] = (axi.burst_read_range(addr, count) if burst
                                else axi.read_block(addr, count))
            elif op == "write_block":
                words = [int(w) for w in p["words"]]
                if burst:
                    axi.burst_write_range(addr, words)
                else:
                    axi.write_block(addr, words)
            else:
                raise ValueError(f"unknown axi op {op!r}")
        return out

    # ---- queries and lifetime -----------------------------------------

    def last_capture(self, params: dict[str, Any]) -> dict[str, Any] | None:
        """The last capture published for the ELA *params* names, or None:
        with no ``instance``, the most recent one of any ELA on the chain.
        Its ``core`` keeps the image generation it was taken under."""
        chain = 1 if params.get("chain") is None else int(params["chain"])
        instance = params.get("instance")
        with self._cv:
            found = [
                snap for key, snap in self._snapshots.items()
                if key[0] == "ela" and key[1] == chain and (
                    instance is None or key[2] == int(instance)
                )
            ]
        return max(found, key=lambda snap: snap["seq"]) if found else None

    def cancel(self, job_id: int, owner: str | None = None) -> bool:
        with self._cv:
            job = self._jobs.get(job_id)
            if job is None or (owner is not None and job.owner != owner):
                return False
            job.cancel()
            self._cv.notify_all()
        return True

    def cancel_owner(self, owner: str) -> int:
        """Cancel every job of *owner*; return how many."""
        with self._cv:
            jobs = [j for j in self._jobs.values() if j.owner == owner]
            for j in jobs:
                j.cancel()
            self._cv.notify_all()
        return len(jobs)

    def active_jobs(self) -> int:
        with self._cv:
            return len(self._jobs)

    def status(self) -> dict[str, Any]:
        with self._cv:
            cores = []
            for key, q in self._queues.items():
                cores.append({
                    "core": self.core_ref(key).to_dict(),
                    "holder": q[0].describe() if q else None,
                    "queued": [j.describe() for j in list(q)[1:]],
                })
            return {
                "target": self.spec.key(),
                "image_gen": self.image_gen,
                "connected": self._transport is not None and not self._stale,
                "jobs": len(self._jobs),
                "cores": cores,
            }

    def close(self, timeout: float = 5.0) -> None:
        """Cancel every job, wait up to *timeout* for them, close the transport."""
        with self._cv:
            self._closed = True
            jobs = list(self._jobs.values())
            for j in jobs:
                j.cancel()
            self._cv.notify_all()
        deadline = time.monotonic() + timeout
        for j in jobs:
            j.done_event.wait(max(0.0, deadline - time.monotonic()))
        with self._conn_lock:
            with self._cv:
                t, self._transport = self._transport, None
                self._controllers.clear()
                self._stale = True
        if t is not None:
            try:
                t.close()
            except Exception:  # noqa: BLE001 - shutting down
                log.debug("closing the transport failed", exc_info=True)
