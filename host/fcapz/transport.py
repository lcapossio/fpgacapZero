# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import glob
import logging
import os
import queue
import re
import secrets
import shutil
import socket
import sys
import time
import subprocess
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from typing import IO, Any, Callable, List, NamedTuple

# Character whitelist for the JTAG target filter (XSDB `jtag targets -set
# -filter {name =~ "..."}`).  This value is interpolated inside a
# double-quoted TCL string, so we reject every character that could end the
# string or trigger substitution: " [ ] { } $ ; \ <newline> <tab>.
_TCL_NAME_RE = re.compile(r'^[A-Za-z0-9._:/*\- ]+$')

# Character whitelist for bitfile paths (XSDB `fpga -file {...}`).  The path
# is wrapped in TCL braces which disable substitution, so the only unsafe
# characters are unbalanced braces and characters that could terminate the
# brace group.  We accept typical Windows/Unix path characters including
# backslash.  Anything outside this set is rejected outright.
_TCL_PATH_RE = re.compile(r'^[A-Za-z0-9._:/*\-\\ ]+$')
_TCL_BRACED_RE = re.compile(r"^[^{}\r\n]*$")

# Character whitelist for OpenOCD tap names. Unlike the XSDB filter/path (which
# are quoted/braced), the tap is interpolated UNQUOTED into `irscan <tap> ...`
# and `drscan <tap> ...`, which OpenOCD evaluates as TCL. A space, ';',
# newline, '$', '[', '{', etc. could split the command or inject TCL (which
# has `exec`). Restrict to the characters real tap names actually use.
_OPENOCD_TAP_RE = re.compile(r'^[A-Za-z0-9._:\-]+$')

_hw_log = logging.getLogger("fcapz.transport.hw_server")
_quartus_log = logging.getLogger("fcapz.transport.quartus_stp")
_log = logging.getLogger(__name__)
# xsdb marks the selected target with ``*``, after its number in ``jtag
# targets`` (``2* xc7a100t``) and before it in ``targets`` (``* 2  ...``).
_XSDB_TARGET_RE = re.compile(r"^\s*\*?\s*\d+\*?\s+(.+?)\s*$")
QUARTUS_AUTO_DEVICE_TAPS = frozenset(("", "auto", "xc7a100t", "xc7a100t.tap"))


def _tcl_braced(value: str) -> str:
    """Return a Tcl brace-quoted literal for simple tool-discovered names."""
    if not _TCL_BRACED_RE.match(value):
        raise ValueError(f"value contains characters unsafe for Tcl braces: {value!r}")
    return "{" + value + "}"


def connect_timing_logs_enabled() -> bool:
    """If true, log connect phase durations (hw_server + GUI worker).

    Set environment variable ``FCAPZ_LOG_CONNECT_TIMING`` to ``1``, ``true``,
    or ``yes``.
    """
    return os.environ.get("FCAPZ_LOG_CONNECT_TIMING", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def parse_xsdb_jtag_targets(output: str) -> list[str]:
    """Parse target names from XSDB ``jtag targets`` / ``targets`` output."""
    names: list[str] = []
    fpga_names: list[str] = []
    seen: set[str] = set()
    seen_fpga: set[str] = set()
    for line in output.splitlines():
        m = _XSDB_TARGET_RE.match(line)
        if not m:
            continue
        name = m.group(1).strip()
        if " (idcode " in name:
            bare = name.split(" (", 1)[0].strip()
            if " fpga)" in name and bare and bare not in seen_fpga:
                seen_fpga.add(bare)
                fpga_names.append(bare)
            name = bare
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    if fpga_names:
        return fpga_names
    return names


class _ProcessCancel:
    """Cancel handle for a helper child process: ``cancel()`` kills it."""

    def __init__(self, proc: subprocess.Popen) -> None:
        self._proc = proc

    def cancel(self) -> None:
        try:
            self._proc.kill()
        except OSError:
            pass


def list_xilinx_hw_server_targets(
    *,
    host: str = "127.0.0.1",
    port: int = 3121,
    xsdb_path: str | None = None,
    timeout_sec: float = 10.0,
    register: Callable[[Any], None] | None = None,
) -> list[str]:
    """Return JTAG target names reported by ``hw_server`` via XSDB.

    *register*, if given, receives a handle whose ``cancel()`` kills the
    XSDB child, so a caller on another thread can abort the scan.
    """
    xsdb = xsdb_path or shutil.which("xsdb") or shutil.which("xsdb.bat")
    if not xsdb:
        raise RuntimeError("xsdb not found. Add Vivado bin to PATH.")
    script = (
        f"connect -url tcp:{host}:{int(port)}\n"
        "puts [jtag targets]\n"
        "exit\n"
    )
    env = os.environ.copy()
    for key in ("TEMP", "TMP"):
        raw = env.get(key, "")
        if not raw or not os.path.isdir(raw) or not os.access(raw, os.W_OK):
            env[key] = os.getcwd()
    proc = subprocess.Popen(
        [xsdb],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    if register is not None:
        register(_ProcessCancel(proc))
    try:
        stdout, stderr = proc.communicate(script, timeout=float(timeout_sec))
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    output = f"{stdout}\n{stderr}"
    if proc.returncode != 0:
        raise RuntimeError(output.strip() or f"xsdb exited with status {proc.returncode}")
    targets = parse_xsdb_jtag_targets(output)
    if not targets and "To connect to this hw_server instance use url" in output:
        raise RuntimeError(
            "XSDB launched hw_server but did not return JTAG targets. "
            "Start hw_server first, then scan again. "
            f"Raw XSDB output:\n{output.strip()}"
        )
    return targets


def list_openocd_taps(
    *,
    host: str = "127.0.0.1",
    port: int = 6666,
    timeout_sec: float = 5.0,
    register: Callable[[Any], None] | None = None,
) -> list[str]:
    """Return JTAG tap names from a running OpenOCD instance (``jtag names``).

    Requires OpenOCD to already be listening on its TCL RPC port (default
    6666).  Used by the GUI's "Scan" button for the OpenOCD backend.
    *register*, if given, receives the transport before it connects, so a
    caller on another thread can ``cancel()`` it.
    """
    t = OpenOcdTransport(host=host, port=port, connect_timeout_sec=timeout_sec)
    if register is not None:
        register(t)
    t.connect()
    try:
        return t.list_taps()
    finally:
        t.close()


REG_ADDR_SPACE_END = 0x10000


class DataWindowError(RuntimeError):
    """A DATA / timestamp window read would leave the addressable window."""


class ManagerResetError(RuntimeError):
    """The core manager moved away from the slot an operation used.

    A reset invalidated it: the slot was reset after
    :meth:`Analyzer.configure`, so the core went back to its build defaults
    and a capture armed or read since is not the one configured (call
    ``configure()`` again), the hub was reset, which moves ``MGR_ACTIVE`` to
    slot 0, or, on a hub whose Test-Logic-Reset resets the JTAG protocol
    (``MGR_CAPS`` bit 6), the TAP passed through Test-Logic-Reset during a
    readout, which can drop a register command.  Or another controller
    selected another slot while the operation ran, so some of its accesses
    went to that slot.
    """


class BurstIntegrityError(RuntimeError):
    """A burst ran but returned the wrong number of scans or values.

    That is a defect in the readout, not a missing burst capability, so it is
    raised to the caller instead of being read again through the window.
    """


class BurstHeader(NamedTuple):
    """The header a core manager loads into the priming scan of a burst.

    Present when ``MGR_CAPS`` bit 4 is set.  The epochs are the low 16 bits of
    ``MGR_EPOCH`` and the owner slot's ``MGR_SLOT_EPOCH`` when the burst
    started.
    """

    slot: int
    start_ptr: int
    timestamp: bool
    mgr_epoch: int
    slot_epoch: int
    owner: int
    sample_w: int

    MAGIC = 0x4248  # "BH"

    @classmethod
    def parse(cls, scan: int) -> "BurstHeader | None":
        """Decode a priming scan; ``None`` when it is not a burst header."""
        if scan & 0xFFFF != cls.MAGIC or (scan >> 65) & 0x7FFF or scan >> 160:
            return None
        return cls(
            slot=(scan >> 16) & 0xFFFF,
            start_ptr=(scan >> 32) & 0xFFFF_FFFF,
            timestamp=bool((scan >> 64) & 1),
            mgr_epoch=(scan >> 80) & 0xFFFF,
            slot_epoch=(scan >> 96) & 0xFFFF,
            owner=(scan >> 112) & 0xFFFF_FFFF,
            sample_w=(scan >> 144) & 0xFFFF,
        )


class BurstExpectation(NamedTuple):
    """What the header of the next burst must say (:attr:`Transport.burst_expect`).

    ``start_ptr`` is ``SEG_START`` read just before the burst: the pointer the
    ``BURST_PTR`` write latches, so another value means the capture or the
    segment selection changed in between.  ``sample_w`` is the slot's
    ``SAMPLE_W``.  ``tlr_count`` is ``MGR_TLR_COUNT`` before the burst on a hub
    whose Test-Logic-Reset cancels bursts (``MGR_CAPS`` bit 6), else ``None``:
    a cancel after the priming scan leaves the header valid and turns the rest
    of the burst into register data, so only the count shows it.
    """

    slot: int
    start_ptr: int
    sample_w: int
    tlr_count: int | None = None


class BurstUnavailableError(RuntimeError):
    """This session cannot burst-read the request at all.

    Raised before any scan runs: the transport was built without burst
    readout (``burst=False``), or the request does not fit the burst engine
    (not the DATA base, an element wider than the burst DR).  The caller
    reads the register window instead.  A burst that runs and fails raises
    something else, and that is never read around.
    """


def _burst_element_width(sample_w: int, burst_bits: int) -> int:
    """Bits per sample in a burst scan for a core reporting *sample_w*.

    jtag_burst_read packs ``burst_bits // SAMPLE_W`` samples at a stride of
    exactly ``SAMPLE_W`` (sample 0 in the low bits), so a width that does not
    divide the scan leaves unused high bits rather than widening each sample.
    A width of 0 (no core answering) reads as 8; one wider than the scan is
    clamped to it.
    """
    sample_w = int(sample_w)
    if sample_w < 1:
        return 8
    return min(sample_w, burst_bits)


def check_data_window(addr: int, words: int, end: int = REG_ADDR_SPACE_END) -> None:
    """Refuse a register-window read of *words* 32-bit words at *addr* that
    would run past *end*.

    Register addresses are 16 bits, so a read past ``0x10000`` wraps onto the
    core's own registers; behind a core manager the window must also stop at
    the manager block (``0xF000``).  Either way the hardware returns register
    values instead of samples, with no error.
    """
    stop = addr + 4 * max(0, words)
    if stop > min(end, REG_ADDR_SPACE_END):
        raise DataWindowError(
            f"window read 0x{addr:04X}..0x{stop - 4:X} ({words} words) runs past "
            f"0x{end:X}: this capture is too large for the register window; "
            "read it with burst readout instead"
        )


#: ACTIVE writes :meth:`Transport.select_manager_instance_cached` makes before
#: it stops confirming a slot switch (see there).
MANAGER_SELECT_ATTEMPTS = 3

# VERSION[15:0] of a core manager at 0xF000 (ASCII "CM").
_CORE_MANAGER_ID = 0x434D

#: VERSION[15:0] at ``0x0000`` of the cores that speak the 49-bit register
#: protocol: an ELA (``"LA"``) or an EIO (``"IO"``).  A core manager presents
#: its active slot there.
REGISTER_PIPE_CORE_IDS = (0x4C41, 0x494F)


def register_pipe_identity(transport: "Transport", chain: int) -> int | None:
    """Return VERSION at ``0x0000`` on *chain* if an fcapz register core answers.

    Returns ``None`` when the chain answers anything else.  Only ``0x0000`` is
    read.  A read frame for an address below ``0x2000`` puts command 0 (NOP) in
    the command field of the EJTAG-AXI and EJTAG-UART bridges, so this is safe
    on a chain nobody has identified.  Higher addresses are not: a read of
    ``0xF000`` is a burst-data command on the bridge, and a write of
    ``0xF008`` is its reset.  Read anything else only after this returns a
    value.  Raises the transport's error for a chain it cannot select, such as
    a missing ``sld_virtual_jtag`` instance.
    """
    # Unselected: an inherited slot selection would put an MGR_ACTIVE write
    # ahead of the read on an atomic backend, on a chain nobody identified.
    with transport.slot_scope(None, chain=int(chain)):
        version = int(transport.read_reg(0x0000))
    return version if (version & 0xFFFF) in REGISTER_PIPE_CORE_IDS else None


# The core manager's own registers.  The manager answers these itself, for
# every active slot, so an access to them never needs a slot selected.
_MGR_BLOCK_START = 0xF000
_MGR_BLOCK_END = 0xF100


def _in_manager_block(addr: int) -> bool:
    return _MGR_BLOCK_START <= (int(addr) & 0xFFFF) < _MGR_BLOCK_END


@dataclass(frozen=True)
class SlotSelection:
    """The core-manager slot an access must reach: *slot* written to the
    ``MGR_ACTIVE`` register at *active_addr* on *chain*."""

    chain: int
    active_addr: int
    slot: int


class Transport(ABC):
    """Abstract base class for all fpgacapZero JTAG transports.

    Implementations must override the five abstract methods below.
    Two optional extension points (``select_chain`` and ``raw_dr_scan``)
    can be overridden to support multi-chain and raw DR access respectively.

    Exception contract
    ------------------
    All methods should raise:

    * ``RuntimeError``  — if called before :meth:`connect` or after
      :meth:`close`, or if the underlying transport encounters an I/O
      error (e.g. XSDB process exits, socket closed by peer).
    * ``ConnectionError`` — when the remote endpoint closes the connection
      unexpectedly mid-transaction (subclass of ``OSError``).
    * ``ValueError`` — for invalid arguments (e.g. unsupported chain index).
    * ``OSError`` / ``TimeoutError`` — for network or process-level errors
      during :meth:`connect`.
    """

    def transaction_lock(self) -> threading.RLock:
        """Return the shared host-side lock for multi-register transactions.

        Analyzer and EIO controllers can share one physical JTAG transport while
        selecting different core-manager slots.  This lock serializes those
        higher-level register sequences so one controller cannot switch
        ``MGR_ACTIVE`` between another controller's read/modify/write halves.
        """
        lock = self.__dict__.get("_fcapz_transaction_lock")
        if lock is None:
            lock = self.__dict__.setdefault("_fcapz_transaction_lock", threading.RLock())
        return lock

    #: True when the backend writes the selected slot inside the same backend
    #: operation as each access in a :meth:`slot_scope`, so no other client of
    #: the cable can move ``MGR_ACTIVE`` in between.
    atomic_slot_select: bool = False

    def _slot_local(self) -> threading.local:
        local = self.__dict__.get("_fcapz_slot_local")
        if local is None:
            local = self.__dict__.setdefault("_fcapz_slot_local", threading.local())
        return local

    def current_slot_selection(self) -> SlotSelection | None:
        """The calling thread's innermost :meth:`slot_scope` selection, or ``None``."""
        return getattr(self._slot_local(), "selection", None)

    @contextmanager
    def slot_scope(
        self, selection: SlotSelection | None, *, chain: int | None = None
    ) -> Iterator[None]:
        """Run the body's register accesses on *chain* against *selection*'s slot.

        Holds :meth:`transaction_lock` throughout.  The selection belongs to
        the calling thread and lasts only for the body.  ``None`` means the
        body carries no selection -- probes and manager-wide reads, which
        must not inherit an enclosing slot.  *chain*, if given, is selected
        for the body.

        On exit, also after an exception, a nested scope gives back the chain
        that was active when it was entered and then the enclosing slot, so a
        nested probe on another chain or slot cannot leave the enclosing
        controller's next access misrouted.  A
        top-level scope leaves its chain selected, as controllers always have.

        A backend with :attr:`atomic_slot_select` writes ``MGR_ACTIVE`` at the
        head of every backend operation in the scope that reaches a slot (an
        access to the manager's own block, ``0xF000``-``0xF0FF``, does not),
        so a second process on the same cable cannot redirect the access.  It
        does that only on a chain identified as holding a manager, which the
        first scope on each slot does with one verified select.
        Other backends select once on entry through
        :meth:`select_manager_instance_cached`, which another process can
        still undo between operations.
        """
        with self.transaction_lock():
            local = self._slot_local()
            previous = getattr(local, "selection", None)
            previous_chain = getattr(local, "chain", None)
            depth = getattr(local, "depth", 0)
            # The chain active on entry, which a nested scope gives back: read
            # from the transport, since code inside the enclosing body (a GUI
            # subsidiary chain) may have switched it without a scope.  A
            # backend that does not track it falls back to the enclosing
            # scope's record.
            entry_chain = self._current_chain()
            if entry_chain is None:
                entry_chain = previous_chain
            if chain is not None:
                self._scope_select_chain(chain)
            local.selection = selection
            local.chain = chain if chain is not None else entry_chain
            local.depth = depth + 1
            failed = False
            try:
                if selection is not None:
                    if self.atomic_slot_select:
                        local.selection = self._checked_atomic_selection(selection)
                    else:
                        self.select_manager_instance_cached(
                            selection.chain, selection.active_addr, selection.slot
                        )
                yield
            except BaseException:
                failed = True
                raise
            finally:
                local.selection = previous
                local.chain = previous_chain
                local.depth = depth
                try:
                    # Compare with the chain now, not this scope's own: the
                    # body may have switched chains without a scope.  An
                    # untracked backend only knows what this scope selected.
                    exit_chain = self._current_chain()
                    if exit_chain is None:
                        exit_chain = chain
                    if (
                        depth > 0
                        and entry_chain is not None
                        and exit_chain is not None
                        and exit_chain != entry_chain
                    ):
                        self._scope_select_chain(entry_chain)
                    if (
                        previous is not None
                        and previous != selection
                        and not self.atomic_slot_select
                    ):
                        self.select_manager_instance_cached(
                            previous.chain, previous.active_addr, previous.slot
                        )
                except BaseException as exc:
                    # The hardware slot is unknown now: make the next scope
                    # select for real.  The body's own error wins over a
                    # failed restore, but not over an interrupt.
                    self.invalidate_manager_instance_cache()
                    if not failed or not isinstance(exc, Exception):
                        raise

    def _current_chain(self) -> int | None:
        """The chain register accesses go to now, or ``None`` if untracked."""
        return getattr(self, "_active_chain", None)

    def _checked_atomic_selection(
        self, selection: SlotSelection
    ) -> SlotSelection | None:
        """The selection an :attr:`atomic_slot_select` scope publishes for
        its accesses to carry.

        The first scope on a slot selects it once through
        :meth:`select_manager_instance_cached`: that identifies the chain
        (nothing writes ``MGR_ACTIVE`` on a chain before it is known to hold a
        manager), and fails loudly for a slot the manager does not take.  On a
        chain without an identified manager the scope carries no selection,
        as for a standalone core."""
        key = (int(selection.chain), int(selection.slot))
        checked = self.__dict__.setdefault("_fcapz_checked_slots", set())
        if key not in checked:
            self.select_manager_instance_cached(
                selection.chain, selection.active_addr, selection.slot
            )
        if selection.chain not in self.__dict__.get("_fcapz_manager_chains", ()):
            return None
        checked.add(key)
        return selection

    def _scope_select_chain(self, chain: int) -> None:
        try:
            self.select_chain(chain)
        except NotImplementedError:
            # A single-chain transport: chain 1 is the only one there is.
            if chain != 1:
                raise

    def read_regs_after_write(
        self, write_addr: int, value: int, addrs: List[int]
    ) -> List[int]:
        """Write *value* to *write_addr*, then read each of *addrs*.

        For a selector register and the registers it selects, such as
        ``MGR_DESC_INDEX`` and the slot descriptor.  A backend with
        :attr:`atomic_slot_select` does it all in one backend operation, so
        no other client can move the selector in between; this default is
        separate accesses.
        """
        with self.transaction_lock():
            self.write_reg(write_addr, value)
            return [int(self.read_reg(addr)) for addr in addrs]

    def select_manager_instance_cached(
        self,
        chain: int,
        active_addr: int,
        instance: int,
    ) -> None:
        """Make *instance* the core manager's active slot on *chain*.

        The active slot is a sticky hardware register that something else can
        move: a hub reset (power-up, ``MGR_CTRL`` bit 0, or any ELA sample
        reset on bitstreams before per-slot resets) returns it to slot 0, and
        another host session can select its own slot.  So the slot is always
        read back before it is trusted, and written only when it differs.  On
        a backend without :attr:`atomic_slot_select`, :meth:`slot_scope`
        selects through here on entry; an atomic backend comes here once per
        slot, to identify the manager and check the slot, and then selects
        inside every access.  Call under :meth:`transaction_lock`.

        Raises ``ValueError`` for a negative slot and ``RuntimeError`` when a
        core manager answers on *chain* but does not take the slot (out of
        range, or still refusing after :data:`MANAGER_SELECT_ATTEMPTS`
        writes).  The first time it meets a chain it reads ``0x0000`` and then
        the manager VERSION, and writes nothing unless both answer: an
        ``MGR_ACTIVE`` write is the reset command of an EJTAG-AXI bridge (see
        :func:`register_pipe_identity`).  A chain with an fcapz core but no
        manager is remembered as standalone and not written; a chain with
        neither is left alone and checked again next time.  The write and its
        readback are one backend operation (:meth:`read_regs_after_write`),
        and *chain* is selected for them and the chain active before restored.
        """
        chain = int(chain)
        instance = int(instance)
        if instance < 0:
            raise ValueError(f"core-manager slot must be >= 0, got {instance}")
        standalone = self.__dict__.setdefault("_fcapz_manager_standalone_chains", set())
        if chain in standalone:
            return
        current = self._current_chain()
        switch = current is not None and current != chain
        if switch:
            # The manager lives on *chain*; another chain's 0xF008 is some
            # other core's register.
            self._scope_select_chain(chain)
        try:
            with self._no_slot_selection():
                self._select_manager_slot(chain, active_addr, instance)
        finally:
            if switch:
                self._scope_select_chain(current)

    def _select_manager_slot(self, chain: int, active_addr: int, instance: int) -> None:
        """:meth:`select_manager_instance_cached` with *chain* selected and no
        slot selection in force, so no access here carries a prefix."""
        standalone = self.__dict__.setdefault("_fcapz_manager_standalone_chains", set())
        if chain in standalone:
            return
        managers = self.__dict__.setdefault("_fcapz_manager_chains", set())
        base = active_addr & 0xFF00
        if chain not in managers:
            if (int(self.read_reg(0x0000)) & 0xFFFF) not in REGISTER_PIPE_CORE_IDS:
                return
            if (int(self.read_reg(base)) & 0xFFFF) != _CORE_MANAGER_ID:
                standalone.add(chain)
                return
            managers.add(chain)
            self.manager_chain_caps(chain)
            self._claim_manager(chain, base)
        cached = self.__dict__.get("_fcapz_manager_active_cache")
        if cached == (chain, instance) and int(self.read_reg(active_addr)) == instance:
            return
        # A write that fails may still have reached the hardware: until one
        # is confirmed the slot is unknown, not the previously cached one.
        self.__dict__.pop("_fcapz_manager_active_cache", None)
        # The manager ignores an ACTIVE write while its burst engine loads.
        # After a burst the pipe preloads once more, at the next scan's
        # capture, for ~256 / SAMPLE_W TCKs, so on bitstreams built before
        # the burst owner was made stable a switch straight after a narrow
        # (SAMPLE_W <= 5) burst can be dropped.  Write again: two rounds
        # outlast the longest preload.
        for _ in range(MANAGER_SELECT_ATTEMPTS):
            self._count_manager_select(chain)
            (got,) = self.read_regs_after_write(active_addr, instance, [active_addr])
            if int(got) == instance:
                self.__dict__["_fcapz_manager_active_cache"] = (chain, instance)
                return
        count = int(self.read_reg(base + 0x4))
        detail = (
            f"it has {count} slot(s)"
            if instance >= count
            else f"ACTIVE still reads {int(self.read_reg(active_addr))}"
        )
        raise RuntimeError(
            f"core manager on chain {chain} did not select slot {instance}: {detail}"
        )

    @contextmanager
    def _no_slot_selection(self) -> Iterator[None]:
        """Run the block with no slot selection in force on this thread, and
        no hardware action on the way in or out (unlike ``slot_scope(None)``,
        which restores the enclosing slot on a fallback backend)."""
        local = self._slot_local()
        previous = getattr(local, "selection", None)
        local.selection = None
        try:
            yield
        finally:
            local.selection = previous

    def _count_manager_select(self, chain: int) -> None:
        """Count one ``MGR_ACTIVE`` write of this transport on *chain*; see
        :meth:`manager_select_writes`."""
        writes = self.__dict__.setdefault("_fcapz_manager_select_writes", {})
        writes[int(chain)] = (writes.get(int(chain), 0) + 1) & 0xFFFF

    def manager_chain_caps(self, chain: int) -> int | None:
        """``MGR_CAPS`` of the identified core manager on *chain*, read once
        per identification; ``None`` when *chain* holds no identified manager.
        Call with *chain* selected and no slot selection in force."""
        chain = int(chain)
        if chain not in self.__dict__.get("_fcapz_manager_chains", ()):
            return None
        caps = self.__dict__.setdefault("_fcapz_manager_caps", {})
        if chain not in caps:
            caps[chain] = int(self.read_reg(_MGR_BLOCK_START + 0x10))
        return caps[chain]

    def slot_routing_isolated(self, chain: int, slot: int) -> bool:
        """Whether every access in the calling thread's scope reaches *slot*
        on *chain* whatever other controllers select.

        True only on an :attr:`atomic_slot_select` backend whose scope carries
        that slot of an identified manager: each access then writes the slot
        in its own uninterrupted sequence, and the manager takes the write
        (one with epochs, ``MGR_CAPS`` bit 3, takes it even mid-preload; an
        older one gets a burst drain ahead of it).  Another controller's
        select can then not redirect an access, so a moved ``MGR_ACTIVE`` or
        ``MGR_SELECT_COUNT`` is not evidence that one was.  It is no
        protection against another controller writing this same slot."""
        if not self.atomic_slot_select:
            return False
        sel = self.current_slot_selection()
        return (
            sel is not None
            and sel.chain == int(chain)
            and sel.slot == int(slot)
            and sel.chain in self.__dict__.get("_fcapz_manager_chains", ())
        )

    @contextmanager
    def held_manager_instance(
        self,
        chain: int,
        active_addr: int,
        instance: int,
    ) -> Iterator[None]:
        """Select *instance* as :meth:`select_manager_instance_cached` does,
        then check, after the block, that every access in it reached that
        slot.  Call under :meth:`transaction_lock`, and access only that slot
        in the block.

        Another controller can select another slot at any time, and select
        this one back before the block ends: ``MGR_ACTIVE`` reads the same,
        but the accesses in between went elsewhere.  ``MGR_SELECT_COUNT``
        (``MGR_CAPS`` bit 7) counts every ``MGR_ACTIVE`` write, so a count
        that moved by more than this transport's own writes says one
        happened.  ``MGR_ACTIVE`` is read after the block too, for a hub
        reset (it moves the active slot to 0 without a select) and for hubs
        without the count.  Raises :class:`ManagerResetError` in either
        case; the block is not checked when it raises.  Nothing is checked on
        a chain without a core manager.

        The order makes the count cover the block: count, then ``MGR_ACTIVE``
        (this slot, so no select since the count took it away), the block,
        ``MGR_ACTIVE`` (a hub reset in the block shows, or a select back
        after it moved the count), then the count.
        """
        chain = int(chain)
        instance = int(instance)
        if self.slot_routing_isolated(chain, instance):
            # Every access in the block selects the slot itself.
            yield
            return
        self.select_manager_instance_cached(chain, active_addr, instance)
        if chain not in self.__dict__.get("_fcapz_manager_chains", ()):
            yield
            return
        base = active_addr & 0xFF00
        caps = self.__dict__.setdefault("_fcapz_manager_caps", {})
        if chain not in caps:
            caps[chain] = int(self.read_reg(base + 0x10))
        count_addr = base + 0x34 if caps[chain] & 0x80 else None

        def foreign_selects() -> int:
            own = self.manager_select_writes(chain)
            return (int(self.read_reg(count_addr)) - own) & 0xFFFF

        before = None if count_addr is None else foreign_selects()

        def check_active(when: str) -> None:
            active = int(self.read_reg(active_addr))
            if active != instance:
                raise ManagerResetError(
                    f"the core manager's active slot on chain {chain} is "
                    f"{active}, not {instance}, {when} an access to slot "
                    f"{instance}: another controller selected it, or the hub "
                    "was reset, and some of the access went there"
                )

        if before is not None:
            check_active("at the start of")
        yield
        check_active("after")
        if before is not None:
            moved = (foreign_selects() - before) & 0xFFFF
            if moved:
                raise ManagerResetError(
                    f"another controller wrote the core manager's active slot "
                    f"on chain {chain} {moved} time(s) during an access to slot "
                    f"{instance}: some of the access may have reached another slot"
                )

    def _claim_manager(self, chain: int, base: int) -> None:
        """Write this session's owner token to the manager at *base* on *chain*.

        Only managers with ``MGR_OWNER`` (``MGR_CAPS`` bit 3).  The token is
        advisory: a token of another session is reported, not obeyed, since
        a session that exited without closing leaves its token behind too.
        Call with *chain* selected.
        """
        if not int(self.read_reg(base + 0x10)) & 0x08:
            return
        token = self.__dict__.setdefault("_fcapz_owner_token", secrets.randbits(31) | 1)
        owner = int(self.read_reg(base + 0x24))
        if owner not in (0, token):
            _log.warning(
                "core manager on chain %d carries owner token 0x%08X: another "
                "host session may be using it, or one exited without closing",
                chain,
                owner,
            )
        self.write_reg(base + 0x24, token)
        self.__dict__.setdefault("_fcapz_owned_managers", set()).add((chain, base))

    def release_manager_ownership(self) -> None:
        """Clear this session's owner token from the managers it claimed.

        A manager whose ``MGR_OWNER`` holds another value (another session
        took it, or the hub was reset) is left alone.
        """
        token = self.__dict__.get("_fcapz_owner_token")
        owned = self.__dict__.pop("_fcapz_owned_managers", set())
        if token is None or not owned:
            return
        with self.transaction_lock():
            for chain, base in sorted(owned):
                try:
                    self.select_chain(chain)
                except NotImplementedError:
                    if chain != 1:
                        continue
                if int(self.read_reg(base + 0x24)) == token:
                    self.write_reg(base + 0x24, 0)

    def _release_ownership_on_close(self) -> None:
        """:meth:`release_manager_ownership` for ``close()``, best effort.

        Skipped while another thread holds the transaction lock: a close must
        not wait on a scan in flight.  A failure is logged, and the close goes
        on.
        """
        if not self.__dict__.get("_fcapz_owned_managers"):
            return
        lock = self.transaction_lock()
        if not lock.acquire(blocking=False):
            return
        try:
            self.release_manager_ownership()
        except Exception as exc:  # noqa: BLE001 - closing anyway
            _log.warning("could not clear MGR_OWNER: %s", exc)
        finally:
            lock.release()

    def manager_select_writes(self, chain: int) -> int:
        """``MGR_ACTIVE`` writes this transport made to the core manager on
        *chain*, modulo 2**16.  The manager counts every one, from every
        controller, in ``MGR_SELECT_COUNT`` (``MGR_CAPS`` bit 7): the
        difference is the other controllers' selects.  Every select of this
        host goes through :meth:`select_manager_instance_cached`, which
        counts them; the count survives
        :meth:`invalidate_manager_instance_cache`."""
        return self.__dict__.get("_fcapz_manager_select_writes", {}).get(int(chain), 0)

    def invalidate_manager_instance_cache(self) -> None:
        """Forget the cached core-manager active slot selection, so the next
        cached select writes and confirms it.  Which chains hold a manager is
        kept; see :meth:`forget_manager_chains`."""
        self.__dict__.pop("_fcapz_manager_active_cache", None)

    def forget_manager_chains(self) -> None:
        """Forget everything learned about the core managers: the cached
        active slot, which chains hold a manager or a standalone core, their
        ``MGR_CAPS`` and the slots already checked.  For a new session or a
        new bitstream."""
        self.invalidate_manager_instance_cache()
        self.__dict__.pop("_fcapz_manager_standalone_chains", None)
        self.__dict__.pop("_fcapz_manager_chains", None)
        self.__dict__.pop("_fcapz_manager_caps", None)
        self.__dict__.pop("_fcapz_checked_slots", None)

    def _forget_hub_state(self) -> None:
        """:meth:`forget_manager_chains`, and the managers this session
        claimed, unreleased: a new connection or a new bitstream may put
        anything on those chains, and an ``MGR_OWNER`` read or write there
        would be a command to whatever core is there now."""
        self.forget_manager_chains()
        self.__dict__.pop("_fcapz_owned_managers", None)

    @abstractmethod
    def connect(self) -> None:
        """Open the transport connection.

        Raises ``RuntimeError`` if the backend cannot be reached (e.g. xsdb
        not on PATH, OpenOCD port not listening).  Raises ``OSError`` or
        ``TimeoutError`` for socket-level failures.
        """
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Close the transport.  Must be idempotent — safe to call multiple times."""
        raise NotImplementedError

    def cancel(self) -> None:
        """Best-effort abort for an in-flight backend operation."""
        self.close()

    @abstractmethod
    def read_reg(self, addr: int) -> int:
        """Read a 32-bit register at *addr*.

        Raises ``RuntimeError`` if not connected or if the underlying I/O
        fails.  Returns the raw 32-bit value (unsigned).
        """
        raise NotImplementedError

    def read_reg_stable(self, addr: int) -> int:
        """Read a register, applying any transport-specific stale-read workaround.

        The base implementation is a single ``read_reg`` call.  Transports
        with a known JTAG pipeline hazard may override this to discard a
        warmup read before returning data.  This is not data-integrity
        verification: it does not compare reads or detect corruption.
        """
        return self.read_reg(addr)

    @abstractmethod
    def write_reg(self, addr: int, value: int) -> None:
        """Write *value* (32-bit) to the register at *addr*.

        Raises ``RuntimeError`` if not connected or if the underlying I/O
        fails.
        """
        raise NotImplementedError

    @abstractmethod
    def read_block(self, addr: int, words: int) -> List[int]:
        """Read *words* consecutive 32-bit registers starting at *addr*.

        Returns a list of *words* unsigned 32-bit integers.  Raises
        ``RuntimeError`` if not connected or on I/O failure.
        """
        raise NotImplementedError

    def read_window_block(self, addr: int, words: int) -> List[int]:
        """Like :meth:`read_block`, but always through the register window,
        never a burst.  For a core-manager slot with no burst wiring, whose
        burst reads return zeros.  Transports whose ``read_block`` never
        bursts need not override it."""
        return self.read_block(addr, words)

    def bursts_data_window(self, *, timestamp: bool = False) -> bool:
        """Whether ``read_block(0x0100, ...)`` (with *timestamp*,
        ``read_timestamp_block``) runs a burst rather than reading the
        register window.  A burst is not limited by
        :attr:`data_window_end`; a window read is, so the analyzer pages it
        (``DATA_OFFSET``) when it would pass the end.  Transports that burst
        override this, and decide their ``read_block`` with it."""
        return False

    #: One past the last address a DATA / timestamp window read may touch.
    #: :class:`~fcapz.analyzer.Analyzer` lowers it to the manager block
    #: (``0xF000``) for a core behind a core manager.
    data_window_end: int = REG_ADDR_SPACE_END

    #: Set by :class:`~fcapz.analyzer.Analyzer` before a burst when the core
    #: sits behind a core manager with two or more slots that predates
    #: ``MGR_CAPS`` bit 2.  That manager passes on the owner slot's own burst
    #: start toggle, and after a slot switch the toggle can equal the copy the
    #: burst engine last saw, so the engine misses the start and reads the new
    #: slot from the previous burst's pointer.  A bursting transport then
    #: writes ``BURST_PTR``, runs one burst scan (its capture makes the
    #: engine's copy match the new owner's toggle), and writes ``BURST_PTR``
    #: again: that second toggle the engine cannot miss.
    burst_start_sync: bool = False

    #: Set by :class:`~fcapz.analyzer.Analyzer` before a burst through a core
    #: manager that loads a burst header into the priming scan (``MGR_CAPS``
    #: bit 4): what that header must say.  A bursting transport then checks
    #: the priming scan (:meth:`_check_burst_header`) and keeps the header in
    #: :attr:`last_burst_header`.  ``None``: no header expected.
    burst_expect: BurstExpectation | None = None

    #: The header of the last checked burst, for the epoch check after it.
    last_burst_header: BurstHeader | None = None

    def _check_burst_header(self, prime_scan: int, *, timestamp: bool) -> None:
        """Check a burst's priming scan against :attr:`burst_expect`.

        Raises :class:`BurstIntegrityError` when the scan is not the header of
        the expected burst: the data that follow would belong to another
        burst, another slot or segment, a slot held in reset, or no burst at
        all.  ``MGR_OWNER`` is advisory: another session's token is reported.
        """
        expect = self.burst_expect
        if expect is None:
            return
        header = BurstHeader.parse(prime_scan)
        if header is None:
            raise BurstIntegrityError(
                f"burst priming scan is not a burst header ({prime_scan:#x}): "
                "the hub did not start this burst"
            )
        if header.slot != expect.slot or header.timestamp != timestamp:
            raise BurstIntegrityError(
                f"burst header is for slot {header.slot} "
                f"({'timestamps' if header.timestamp else 'samples'}), expected "
                f"slot {expect.slot} ({'timestamps' if timestamp else 'samples'})"
            )
        if header.start_ptr != expect.start_ptr:
            raise BurstIntegrityError(
                f"burst header starts at sample {header.start_ptr}, expected "
                f"{expect.start_ptr}: the capture or its segment selection "
                "changed before the burst started"
            )
        if header.sample_w != expect.sample_w:
            raise BurstIntegrityError(
                f"burst header is for {header.sample_w}-bit samples, slot "
                f"{expect.slot} reports SAMPLE_W={expect.sample_w}"
            )
        if header.slot_epoch & 1:
            raise BurstIntegrityError(
                f"slot {expect.slot} is held in reset (MGR_SLOT_EPOCH "
                f"{header.slot_epoch} is odd): its capture is not readable"
            )
        token = self.__dict__.get("_fcapz_owner_token")
        if token is not None and header.owner not in (0, token):
            _log.warning(
                "burst from slot %d started while MGR_OWNER holds 0x%08X, not "
                "this session's token: another host session may be using the hub",
                expect.slot,
                header.owner,
            )
        self.last_burst_header = header

    #: True when :meth:`read_block` and ``read_timestamp_block`` burst on a
    #: separate data chain (the unmanaged two-chain ELA's DATA_CHAIN).  A core
    #: manager answers bursts only on its own chain, so
    #: :class:`~fcapz.analyzer.Analyzer` then reads a managed slot through the
    #: single-chain ``read_sample_block`` / ``read_timestamp_block_single_chain``,
    #: passing ``on_control_chain=True`` so they burst on the active chain.
    burst_on_data_chain: bool = False

    #: Idle TCKs after the command scan that ends a burst on a control chain:
    #: one full staging fill (256 / lane-width words, 256 for a 1-bit lane)
    #: plus margin.  A core manager without epochs (``MGR_CAPS`` bit 3)
    #: ignores an ``MGR_ACTIVE`` write while a fill runs.
    BURST_DRAIN_IDLE_CYCLES = 258

    def select_chain(self, chain: int) -> None:
        """Select the transport-defined JTAG user chain for later accesses.

        For Xilinx/OpenOCD transports this is the BSCANE2 USER chain number
        mapped through the backend's IR table.  For virtual-JTAG transports it
        may be the vendor instance identifier, such as Intel's
        ``sld_virtual_jtag`` ``instance_index``.

        Subclasses that support multi-chain access must override this, and
        keep the selected chain in ``_active_chain`` (or override
        ``_current_chain``): :meth:`slot_scope` reads it to give an enclosing
        scope back its chain and to write a slot select on the manager's own
        chain.
        Raises ``ValueError`` if *chain* is invalid for that transport.
        Raises ``NotImplementedError`` on transports that only support a
        single fixed chain.
        """
        raise NotImplementedError

    def discovery_chains(self) -> tuple[int, ...]:
        """Chains :func:`~fcapz.discovery.discover_cores` looks at by default.

        USER1-4 here; transports narrow it to the chains they can select.
        """
        return (1, 2, 3, 4)

    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        """Perform a raw DR scan of *width* bits, shifting in *bits*.

        Returns the captured TDO value as an unsigned integer.  If *chain*
        is given it overrides the active chain for this scan only.  The chain
        value is transport-specific: Xilinx/OpenOCD transports use the
        user-chain number that maps through their IR table, while Intel
        Quartus/USB-Blaster uses the ``sld_virtual_jtag`` ``instance_index``
        configured by the Intel RTL wrapper's ``CHAIN`` parameter.

        Subclasses that expose raw JTAG DR access must override this.
        Raises ``NotImplementedError`` on transports that do not support it.
        Raises ``RuntimeError`` if not connected or on I/O failure.
        """
        raise NotImplementedError

    def raw_dr_scan_batch(
        self, scans: list[tuple[int, int]], *, chain: int | None = None
    ) -> list[int]:
        """Perform multiple raw DR scans and return all captured TDO values.

        *scans* is a list of ``(bits, width)`` tuples.  Returns a list of
        captured values in the same order.

        Default implementation calls :meth:`raw_dr_scan` in a loop.
        Override for transports that support batched transfers (e.g. a
        single ``jtag sequence`` round-trip in XSDB).
        """
        return [self.raw_dr_scan(bits, width, chain=chain) for bits, width in scans]


#: One step of a raw scan batch (see :meth:`_ScanBurstMixin._run_scans`):
#: ``("ir", chain)`` loads the IR of a USER chain, ``("dr", value, width,
#: capture)`` runs one DR scan and returns its TDO bits when *capture* is
#: true, ``("idle", n)`` clocks *n* TCKs in Run-Test/Idle.  Every scan starts
#: and ends in Run-Test/Idle.
ScanOp = tuple


class _ScanBurstMixin:
    """fcapz burst readout over raw JTAG scans.

    For transports that can run an ordered batch of IR / DR / idle steps as
    one atomic unit (:meth:`_run_scans`).  Provides the burst methods
    :class:`~fcapz.analyzer.Analyzer` looks up by name, with the same
    contract as :class:`XilinxHwServerTransport`: a ``BURST_PTR`` write
    (bit 31 selects timestamps), ``BURST_PREFILL_IDLE_CYCLES`` idle TCKs, one
    discarded priming scan, then one 256-bit scan per packed group of samples.

    The whole burst is one batch.  On a single-chain build any 49-bit scan
    between the ``BURST_PTR`` write and the last burst scan is decoded as a
    register command and ends burst mode, so nothing else may reach the chain
    in between; ``_run_scans`` must hold the transport's I/O lock for the
    whole batch.  A transport that writes the slot selection inside each
    access (:attr:`Transport.atomic_slot_select`) puts it at the head of the
    batch, before ``BURST_PTR`` (:meth:`_slot_select_ops`).  A burst on the
    control chain is checked against its header and ends with a command scan
    and a drain, as on ``hw_server``.

    The host class provides ``burst``, ``single_chain_burst``,
    ``burst_data_chain``, ``_active_chain`` and :meth:`read_reg_stable`.
    """

    DR_BITS = 49
    BURST_DR_BITS = 256
    ADDR_BURST_PTR = 0x002C
    BURST_PREFILL_IDLE_CYCLES = 160
    #: Idle TCKs between burst scans.  The staging register refills while the
    #: previous scan shifts; these give it margin for one-bit samples, which
    #: pack 256 per scan.
    BURST_SCAN_IDLE_CYCLES = 4
    _ADDR_DATA_BASE = 0x0100
    _ADDR_SAMPLE_W = 0x000C

    burst: bool
    single_chain_burst: bool
    burst_data_chain: int
    burst_start_sync: bool

    def _run_scans(self, ops: list[ScanOp]) -> list[int]:
        """Run *ops* atomically; return the captured DR values in order."""
        raise NotImplementedError

    def _slot_select_ops(self, addr: int) -> list[ScanOp]:
        """Ops that write the calling thread's slot selection at the head of a
        batch reaching *addr*; none for a transport that selects on entering
        :meth:`Transport.slot_scope`."""
        return []

    @property
    def burst_on_data_chain(self) -> bool:
        """A two-chain session (``single_chain_burst=False``) bursts on its
        data chain, which a core manager never answers."""
        return not self.single_chain_burst

    # -- Analyzer-facing burst methods --------------------------------------

    def _burst_block_or_none(self, addr: int, words: int) -> List[int] | None:
        """Burst-read a narrow core's DATA window, or ``None`` when the
        request belongs to the register window (not the DATA base, burst off,
        or ``SAMPLE_W > 32``, which :meth:`read_sample_block` serves)."""
        if words <= 0 or addr != self._ADDR_DATA_BASE or not self.burst:
            return None
        sample_w = int(self.read_reg_stable(self._ADDR_SAMPLE_W))
        if sample_w > 32:
            return None
        return self._burst_with_hint(words, element_width=max(1, sample_w))

    def read_sample_block(
        self, base_addr: int, n_samples: int, sample_width: int,
        *, on_control_chain: bool = False,
    ) -> List[int]:
        """Read *n_samples* whole samples via the burst DR.

        With *on_control_chain* the scans stay on the control chain even on a
        two-chain session: a core manager answers bursts only there.

        Returns ``ceil(sample_width / 32)`` little-endian 32-bit words per
        sample.  Raises :class:`BurstUnavailableError`, before any scan, when
        this transport cannot burst the request; :class:`BurstIntegrityError`
        when a burst ran but returned the wrong number of samples.
        """
        if n_samples <= 0:
            return []
        if base_addr != self._ADDR_DATA_BASE:
            raise BurstUnavailableError(
                f"sample burst needs the DATA base, got 0x{base_addr:04X}"
            )
        if not 1 <= sample_width <= self.BURST_DR_BITS:
            raise BurstUnavailableError(
                f"sample width {sample_width} does not fit the "
                f"{self.BURST_DR_BITS}-bit burst DR"
            )
        if not self.burst:
            raise BurstUnavailableError("burst readout is off for this transport")
        samples = self._burst_with_hint(
            n_samples, element_width=sample_width, on_control_chain=on_control_chain
        )
        words_per_sample = (sample_width + 31) // 32
        words: List[int] = []
        for sample in samples:
            for w in range(words_per_sample):
                words.append((sample >> (w * 32)) & 0xFFFFFFFF)
        return words

    def read_timestamp_block_single_chain(
        self, base_addr: int, n_timestamps: int, timestamp_width: int,
        *, on_control_chain: bool = False,
    ) -> List[int]:
        """Read one timestamp per captured sample via the burst DR, on the
        control chain with *on_control_chain* (a core manager's slot)."""
        if n_timestamps <= 0:
            return []
        if not self.burst:
            raise BurstUnavailableError("burst readout is off for this transport")
        return self._burst_with_hint(
            n_timestamps, timestamp=True, element_width=timestamp_width,
            on_control_chain=on_control_chain,
        )

    def read_run_length_block(
        self, n_entries: int, lane_width: int, *, on_control_chain: bool = False
    ) -> List[int]:
        """Read one run count per captured entry via the burst DR: the
        timestamp lane with ``BURST_PTR[30]`` set, ``lane_width`` bits per
        element.  Raises :class:`BurstUnavailableError`, before any scan,
        when burst readout is off."""
        if n_entries <= 0:
            return []
        if not self.burst:
            raise BurstUnavailableError("burst readout is off for this transport")
        return self._burst_with_hint(
            n_entries, timestamp=True, element_width=lane_width,
            run_lengths=True, on_control_chain=on_control_chain,
        )

    def read_timestamp_block(
        self, addr: int, words: int, timestamp_width: int
    ) -> List[int]:
        """Read timestamp words by burst when available, else the window."""
        if words <= 0:
            return []
        if self.burst and timestamp_width > 0:
            return self._burst_with_hint(
                words, timestamp=True, element_width=timestamp_width
            )
        return self.read_window_block(addr, words)

    # -- burst engine --------------------------------------------------------

    def _burst_ops(
        self, n_scans: int, *, timestamp: bool, run_lengths: bool = False,
        on_control_chain: bool = False,
    ) -> tuple[list[ScanOp], int, bool]:
        """Return the op batch for a burst of *n_scans* data scans, the
        number of leading captures (priming scans) to discard, and whether
        the burst runs on the control chain."""
        ctrl = self._active_chain
        on_ctrl = self.single_chain_burst or on_control_chain
        burst_chain = ctrl if on_ctrl else self.burst_data_chain
        frame = (
            (1 << 48)
            | (self.ADDR_BURST_PTR << 32)
            | (0x80000000 if timestamp else 0)
            | (0x40000000 if timestamp and run_lengths else 0)
        )
        write_ptr: list[ScanOp] = [
            ("ir", ctrl),
            ("dr", frame, self.DR_BITS, False),
            ("idle", self.BURST_PREFILL_IDLE_CYCLES),
        ]
        # Select the slot before BURST_PTR, which makes it the burst owner;
        # never between burst scans, where any command scan ends burst mode.
        ops = [*self._slot_select_ops(self.ADDR_BURST_PTR), *write_ptr]
        if self.burst_start_sync:
            # See Transport.burst_start_sync: one burst scan whose capture
            # matches the engine's copy to the new owner's start toggle, then
            # a second BURST_PTR write the engine cannot miss.
            ops += [("ir", burst_chain), ("dr", 0, self.BURST_DR_BITS, False)]
            ops += write_ptr
        ops.append(("ir", burst_chain))
        prime = 1
        for _ in range(n_scans + prime):
            ops.append(("dr", 0, self.BURST_DR_BITS, True))
            ops.append(("idle", self.BURST_SCAN_IDLE_CYCLES))
        if on_ctrl:
            # Leave the pipe idle: until a command scan ends burst mode every
            # capture starts another staging fill, and a core manager ignores
            # an MGR_ACTIVE write while one runs (see BURST_DRAIN_IDLE_CYCLES).
            # The VERSION read is not captured.
            ops += [
                ("ir", ctrl),
                ("dr", 0, self.DR_BITS, False),
                ("idle", self.BURST_DRAIN_IDLE_CYCLES),
            ]
        return ops, prime, on_ctrl

    def _read_block_burst(
        self, count: int, *, timestamp: bool = False, element_width: int = 8,
        run_lengths: bool = False, on_control_chain: bool = False,
    ) -> List[int]:
        """Read *count* elements of *element_width* bits via the burst DR."""
        per_scan = max(1, self.BURST_DR_BITS // element_width)
        n_scans = (count + per_scan - 1) // per_scan
        ops, prime, on_ctrl = self._burst_ops(
            n_scans, timestamp=timestamp, run_lengths=run_lengths,
            on_control_chain=on_control_chain,
        )
        scans = self._run_scans(ops)
        if len(scans) != n_scans + prime:
            raise BurstIntegrityError(
                f"burst returned {len(scans)} scans, expected {n_scans + prime}"
            )
        if on_ctrl:
            # A core manager loads the burst header into the priming scan.
            self._check_burst_header(scans[0], timestamp=timestamp)
        mask = (1 << element_width) - 1
        values: List[int] = []
        for scan in scans[prime:]:
            for s in range(per_scan):
                if len(values) >= count:
                    break
                values.append((scan >> (s * element_width)) & mask)
        if len(values) != count:
            raise BurstIntegrityError(
                f"burst returned {len(values)} values, expected {count}"
            )
        return values

    def _burst_with_hint(self, count: int, **kwargs) -> List[int]:
        """Run :meth:`_read_block_burst`; a burst that fails is raised with
        the build options that would explain it, never read around."""
        try:
            return self._read_block_burst(count, **kwargs)
        except RuntimeError as exc:
            if type(exc) is not RuntimeError:
                raise  # BurstIntegrityError and other typed errors, unchanged
            if self.single_chain_burst:
                hint = (
                    "If this bitstream was built with SINGLE_CHAIN_BURST=0, pass "
                    "--two-chain-burst (single_chain_burst=False)"
                )
            else:
                hint = (
                    "If this bitstream was built with BURST_EN=0, it has no USER2 "
                    "burst path"
                )
            raise RuntimeError(
                f"burst readback failed: {exc}. {hint}; if it has no burst path at "
                "all, pass --no-burst (burst=False)."
            ) from exc


class OpenOcdTransport(_ScanBurstMixin, Transport):
    """
    Drives the fpgacapZero BSCANE2 USER register interface via the OpenOCD
    TCL socket (default port 6666).

    Socket reads and writes are serialized with a lock so concurrent use
    (e.g. multiple GUI workers) cannot corrupt the byte stream.

    Protocol recap (49-bit DR, LSB-first):
        bits[31:0]  = wdata / rdata
        bits[47:32] = addr[15:0]
        bits[48]    = rnw (1=write, 0=read)

    A read requires two DR scans: one to issue the read command and one (after
    idle TCK cycles for CDC) to clock out the returned data.
    """

    # Default BSCANE2 IR codes for Xilinx 7-series.
    # USER1 (0x02) and USER2 (0x03) are verified.
    # Verified on xc7a100t (Arty A7): USER1=0x02, USER2=0x03, USER3=0x22, USER4=0x23.
    DEFAULT_IR_TABLE: dict[int, int] = {1: 0x02, 2: 0x03, 3: 0x22, 4: 0x23}

    # Named IR-table presets for the Xilinx families this transport
    # supports out of the box.  Pass via the ``ir_table`` constructor
    # argument or assign one of these to ``ir_table`` after construction.
    # The 7-series preset is the default and matches DEFAULT_IR_TABLE
    # above; the UltraScale preset is documented in UG570 / UG574 and
    # used by the rtl/jtag_tap_xilinxus.v wrapper instantiations.
    IR_TABLE_XILINX7: dict[int, int] = {1: 0x02, 2: 0x03, 3: 0x22, 4: 0x23}
    IR_TABLE_XILINX_ULTRASCALE: dict[int, int] = {
        1: 0x24, 2: 0x25, 3: 0x26, 4: 0x27,
    }
    # Gowin GW_JTAG exposes ER1/ER2 IR opcodes.  Current RTL wrappers still
    # instantiate one GW_JTAG primitive each, so combining cores should use the
    # wrapper's address-muxed EIO_EN path unless the design shares the primitive.
    IR_TABLE_GOWIN: dict[int, int] = {1: 0x42, 2: 0x43}
    # Microchip PolarFire / PolarFire SoC UJTAG: user IRs are 0x10..0x7F
    # (8-bit IR).  The fcapz wrappers default to 0x20/0x21 because the
    # PolarFire SoC MSS debug module owns 0x10/0x11.
    IR_TABLE_POLARFIRE: dict[int, int] = {1: 0x20, 2: 0x21}
    # Zynq UltraScale+ MPSoC PL TAP opcodes.  OpenOCD's TCL listener
    # delegates chain walking (IR padding for the ARM DAP + DR BYPASS
    # bits) to the openocd config file rather than to host code, so this
    # preset is only useful when your openocd.cfg already declares the
    # xck26 / xczu* chain correctly.  Values parallel
    # ``XilinxHwServerTransport.IR_TABLE_XILINX_ZYNQUS`` for symmetry.
    # **Not yet hardware-validated via OpenOCD** — ship with caution.
    IR_TABLE_XILINX_ZYNQUS: dict[int, int] = {
        1: 0x024, 2: 0x025, 3: 0x026, 4: 0x027,
    }
    # Alias so callers can write IR_TABLE_US for brevity.
    IR_TABLE_US = IR_TABLE_XILINX_ULTRASCALE

    USER1_IR = 0x02
    READ_IDLE_CYCLES = 20

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 6666,
        tap: str = "xc7a100t.tap",
        ir_table: dict[int, int] | None = None,
        *,
        connect_timeout_sec: float = 5.0,
        burst: bool = False,
        single_chain_burst: bool = True,
        burst_data_chain: int = 2,
    ):
        """``burst=True`` reads captures through the ELA's 256-bit burst DR:
        on the control chain by default (``SINGLE_CHAIN_BURST=1`` builds), or
        on *burst_data_chain* with ``single_chain_burst=False``.  It is off by
        default because not every wrapper has a burst path (Gowin has none);
        the CLI and RPC turn it on for the PolarFire preset."""
        self.host = host
        self.port = port
        # 'auto'/'' are resolved later from OpenOCD's own `jtag names`; any other
        # value is user-supplied and is interpolated into OpenOCD TCL, so reject
        # anything outside the safe tap-name set to prevent TCL injection.
        if tap.strip().lower() not in ("", "auto") and not _OPENOCD_TAP_RE.match(tap):
            raise ValueError(
                f"unsafe OpenOCD tap name {tap!r}: only letters, digits, and "
                "'. _ : -' are allowed (it is interpolated into OpenOCD TCL)."
            )
        self.tap = tap
        self.ir_table = dict(ir_table) if ir_table else dict(self.DEFAULT_IR_TABLE)
        self._connect_timeout_sec = float(connect_timeout_sec)
        self._active_chain: int = 1
        self._sock: socket.socket | None = None
        # Re-entrant: a burst holds it across all of its Tcl scripts.
        self._sock_lock = threading.RLock()
        self.burst = bool(burst)
        self.single_chain_burst = bool(single_chain_burst)
        self.burst_data_chain = int(burst_data_chain)

    def connect(self) -> None:
        self._forget_hub_state()
        self._sock = socket.create_connection(
            (self.host, self.port),
            timeout=self._connect_timeout_sec,
        )
        self._sock.settimeout(0.2)
        try:
            self._sock.recv(4096)
        except OSError:
            pass
        self._sock.settimeout(5)
        if self.tap.strip().lower() in ("", "auto"):
            self.tap = self._resolve_auto_tap()

    def list_taps(self) -> list[str]:
        """Return the JTAG tap names OpenOCD has configured (``jtag names``)."""
        return self._cmd("jtag names").split()

    def _resolve_auto_tap(self) -> str:
        """Resolve ``tap='auto'`` to a concrete name via OpenOCD ``jtag names``.

        Picks the first tap OpenOCD reports — single-FPGA chains have exactly
        one.  Raises ``RuntimeError`` if OpenOCD has no taps configured.
        """
        taps = self.list_taps()
        if not taps:
            raise RuntimeError(
                "tap='auto' but OpenOCD reports no JTAG taps. "
                "Check your openocd.cfg ('jtag newtap ...')."
            )
        return taps[0]

    def close(self) -> None:
        if self._sock:
            self._release_ownership_on_close()
        self._close_socket()

    def _close_socket(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def cancel(self) -> None:
        # No MGR_OWNER release: that is scans from the cancelling thread,
        # racing the operation being aborted.  The owner's close() does it.
        self._close_socket()

    def _cmd(self, tcl: str) -> str:
        if not self._sock:
            raise RuntimeError("not connected — call connect() first")
        with self._sock_lock:
            self._sock.sendall((tcl + "\x1a").encode())
            buf = b""
            while not buf.endswith(b"\x1a"):
                chunk = self._sock.recv(4096)
                if not chunk:
                    raise ConnectionError("OpenOCD closed the connection")
                buf += chunk
            return buf[:-1].decode().strip()

    def select_chain(self, chain: int) -> None:
        """Select BSCANE2 USER chain for subsequent register accesses."""
        if chain not in self.ir_table:
            raise ValueError(f"chain {chain} not in ir_table {self.ir_table}")
        self._active_chain = chain

    def discovery_chains(self) -> tuple[int, ...]:
        return tuple(sorted(self.ir_table))

    def _select_ir(self, chain: int | None = None) -> None:
        ir = self.ir_table[chain if chain is not None else self._active_chain]
        self._cmd(f"irscan {self.tap} {ir}")

    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        """Perform a raw DR scan via irscan + drscan on the OpenOCD socket."""
        self._select_ir(chain)
        hex_width = (width + 3) // 4
        hex_in = f"0x{bits:0{hex_width}x}"
        result = self._cmd(f"drscan {self.tap} {width} {hex_in}")
        return self._parse_drscan_result(result, command="drscan", width=width)

    def _parse_drscan_result(self, result: str, *, command: str, width: int) -> int:
        token = result.split()[0] if result.split() else ""
        try:
            return int(token, 16)
        except ValueError as exc:
            raise RuntimeError(
                f"OpenOCD {command} failed or returned non-hex data "
                f"for tap {self.tap!r}, width {width}: {result!r}"
            ) from exc

    # Each access is one Tcl command line, the slot selection at its head:
    # OpenOCD's Tcl server runs a whole line before it serves another client.
    atomic_slot_select = True

    def _scan_tcl(self, frame: int) -> str:
        """IR scan of the active chain's opcode, then one 49-bit DR scan."""
        ir = self.ir_table[self._active_chain]
        return f"irscan {self.tap} {ir}; drscan {self.tap} 49 0x{frame:013x}"

    def _run_line(self, cmds: list[str]) -> str:
        return self._cmd("; ".join(cmds))

    def _slot_select_cmds(self, addrs: List[int]) -> list[str]:
        """Commands that write the calling thread's slot selection (see
        :meth:`Transport.slot_scope`), for the head of a command line whose
        accesses reach *addrs* on the active chain.

        Nothing when no slot is selected, when the access is on another
        chain, or when every address is in the manager's own block: the
        manager answers those for any slot, and a select ahead of a read of
        ``MGR_ACTIVE`` would overwrite what the read is after.
        """
        sel = self.current_slot_selection()
        if sel is None or sel.chain != self._active_chain:
            return []
        if sel.chain not in self.__dict__.get("_fcapz_manager_chains", ()):
            # Not (or no longer) known to hold a manager: on any other core
            # 0xF008 is some other register, an EJTAG-AXI bridge's reset.
            return []
        if addrs and all(_in_manager_block(a) for a in addrs):
            return []
        # This line moves MGR_ACTIVE behind the cache, and may fail after
        # doing so: a later cached select must write for real.
        self.invalidate_manager_instance_cache()
        self._count_manager_select(sel.chain)
        cmds: list[str] = []
        caps = self.__dict__.get("_fcapz_manager_caps", {}).get(sel.chain, 0)
        if not caps & 0x08:
            # A manager without epochs (MGR_CAPS bit 3) ignores an ACTIVE
            # write while its burst engine loads, which another client's burst
            # can leave it doing: a VERSION read ends burst mode first, and the
            # idle outlasts the last fill.
            cmds += [self._scan_tcl(0), f"runtest {self.BURST_DRAIN_IDLE_CYCLES}"]
        frame = (
            (1 << 48) | ((sel.active_addr & 0xFFFF) << 32) | (sel.slot & 0xFFFFFFFF)
        )
        return cmds + [self._scan_tcl(frame), f"runtest {self.READ_IDLE_CYCLES}"]

    def write_reg(self, addr: int, value: int) -> None:
        frame = (1 << 48) | ((addr & 0xFFFF) << 32) | (value & 0xFFFFFFFF)
        result = self._run_line([*self._slot_select_cmds([addr]), self._scan_tcl(frame)])
        self._parse_drscan_result(result, command="drscan", width=49)

    def read_reg(self, addr: int) -> int:
        read_frame = ((addr & 0xFFFF) << 32)
        result = self._run_line([
            *self._slot_select_cmds([addr]),
            self._scan_tcl(read_frame),
            f"runtest {self.READ_IDLE_CYCLES}",
            self._scan_tcl(read_frame),
        ])
        return self._parse_drscan_result(result, command="drscan", width=49) & 0xFFFFFFFF

    def read_regs_after_write(
        self, write_addr: int, value: int, addrs: List[int]
    ) -> List[int]:
        """The write and the reads run as one command line."""
        # One unit with the chain and slot read once: hold off any other
        # thread's scope, as the base implementation does.
        with self.transaction_lock():
            if not addrs:
                self.write_reg(write_addr, value)
                return []
            frame = (1 << 48) | ((write_addr & 0xFFFF) << 32) | (value & 0xFFFFFFFF)
            cmds = [
                *self._slot_select_cmds([write_addr, *addrs]),
                self._scan_tcl(frame),
                f"runtest {self.READ_IDLE_CYCLES}",
            ]
            for i, addr in enumerate(addrs):
                read_frame = (addr & 0xFFFF) << 32
                cmds += [
                    self._scan_tcl(read_frame),
                    f"runtest {self.READ_IDLE_CYCLES}",
                    f"set __fcapz_read_{i} [{self._scan_tcl(read_frame)}]",
                ]
            cmds.append("list " + " ".join(f"$__fcapz_read_{i}" for i in range(len(addrs))))
            tokens = self._run_line(cmds).split()
            if len(tokens) != len(addrs):
                raise RuntimeError(
                    f"OpenOCD returned {len(tokens)} values for {len(addrs)} reads: "
                    f"{' '.join(tokens)!r}"
                )
            return [
                self._parse_drscan_result(token, command="drscan", width=49) & 0xFFFFFFFF
                for token in tokens
            ]

    def read_block(self, addr: int, words: int) -> List[int]:
        """Read *words* registers; the DATA window of a narrow core goes
        through the burst DR when ``burst`` is on."""
        burst = self._burst_block_or_none(addr, words)
        if burst is not None:
            return burst
        return self.read_window_block(addr, words)

    def read_window_block(self, addr: int, words: int) -> List[int]:
        check_data_window(addr, words, self.data_window_end)
        return [self.read_reg(addr + i * 4) for i in range(words)]

    #: Read timeout for a scan batch: OpenOCD answers only once the whole
    #: line has run, so a deep burst gets a base plus a margin per scan.
    _BATCH_TIMEOUT_SEC = 5.0
    _BATCH_TIMEOUT_PER_SCAN_SEC = 0.05

    def _slot_select_ops(self, addr: int) -> list[ScanOp]:
        return [("tcl", cmd) for cmd in self._slot_select_cmds([addr])]

    def _run_scans(self, ops: list[ScanOp]) -> list[int]:
        """Run *ops* as ONE Tcl command line, which OpenOCD's Tcl server runs
        before it serves another client: no other client's scan can end
        burst mode, or move the slot, between two scans of a batch.  A run of
        identical captured scans becomes a ``for`` loop, so the line stays
        short at any depth (OpenOCD drops a line over 4 MiB).
        """
        cmds = ["set __fcapz_r {}"]
        expected = 0
        i = 0
        while i < len(ops):
            op = ops[i]
            kind = op[0]
            if kind == "ir":
                cmds.append(f"irscan {self.tap} {self.ir_table[op[1]]}")
            elif kind == "idle":
                cmds.append(f"runtest {int(op[1])}")
            elif kind == "tcl":
                cmds.append(op[1])
            elif kind == "dr":
                _, value, width, capture = op
                scan = f"drscan {self.tap} {width} 0x{value:0{(width + 3) // 4}x}"
                if not capture:
                    cmds.append(scan)
                else:
                    pair = ops[i:i + 2]
                    idle = pair[1] if len(pair) == 2 and pair[1][0] == "idle" else None
                    unit = pair if idle is not None else [op]
                    repeats = 1
                    while ops[i + repeats * len(unit):i + (repeats + 1) * len(unit)] == unit:
                        repeats += 1
                    body = f"lappend __fcapz_r [{scan}]"
                    if idle is not None:
                        body += f"; runtest {int(idle[1])}"
                    if repeats == 1:
                        cmds.append(body)
                    else:
                        cmds.append(
                            "for {set __fcapz_i 0} "
                            f"{{$__fcapz_i < {repeats}}} {{incr __fcapz_i}} {{{body}}}"
                        )
                    expected += repeats
                    i += repeats * len(unit)
                    continue
            else:
                raise ValueError(f"unknown scan op {op!r}")
            i += 1
        cmds.append("set __fcapz_r")
        with self._sock_lock:
            sock = self._sock
            if sock is not None:
                sock.settimeout(
                    self._BATCH_TIMEOUT_SEC + self._BATCH_TIMEOUT_PER_SCAN_SEC * expected
                )
            try:
                result = self._run_line(cmds)
            finally:
                if sock is not None:
                    sock.settimeout(self._BATCH_TIMEOUT_SEC)
        try:
            values = [int(t, 16) for t in result.split()]
        except ValueError as exc:
            raise RuntimeError(
                f"OpenOCD scan batch failed for tap {self.tap!r}: {result!r}"
            ) from exc
        if len(values) != expected:
            raise BurstIntegrityError(
                f"OpenOCD scan batch returned {len(values)} values, expected {expected}"
            )
        return values

def openocd_burst_default(ir_table: dict[int, int] | None) -> bool:
    """Whether an OpenOCD session with *ir_table* reads captures by burst
    unless told otherwise.

    True only for the PolarFire preset: its wrapper builds single-chain burst
    by default and the path is hardware-validated over OpenOCD.  Gowin
    wrappers have no burst path, and the other presets stay on the register
    window until validated; ``OpenOcdTransport(burst=True)`` (CLI ``--burst``)
    opts in.
    """
    return dict(ir_table or {}) == OpenOcdTransport.IR_TABLE_POLARFIRE


def find_quartus_stp(explicit: str | None = None) -> str | None:
    """Locate the ``quartus_stp`` executable for the USB-Blaster transport.

    Resolution order, first hit wins:

    1. ``explicit`` (an operator-supplied path — returned as-is),
    2. the ``PATH``,
    3. ``$QUARTUS_ROOTDIR`` (Quartus sets this in its shells),
    4. common Intel/Altera install roots, newest version first.

    Returns ``None`` when nothing is found, so callers can raise a message
    that fits their context.  Kept OS-agnostic: Windows drives + Program
    Files, POSIX ``/opt`` / ``/tools`` / ``$HOME`` are all globbed.
    """
    if explicit:
        return explicit
    for name in ("quartus_stp", "quartus_stp.exe"):
        found = shutil.which(name)
        if found:
            return found

    roots: list[str] = []
    rootdir = os.environ.get("QUARTUS_ROOTDIR")
    if rootdir:
        roots.append(rootdir)
    base_names = (
        "altera_pro",
        "intelFPGA_pro",
        "intelFPGA",
        "altera_lite",
        "altera",
        "quartus",
    )
    if os.name == "nt":
        prefixes = [f"{d}:\\" for d in "CDE"]
        for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            if os.environ.get(env):
                prefixes.append(os.environ[env])
    else:
        prefixes = ["/opt", "/tools", os.path.expanduser("~"), "/usr/local"]
    for prefix in prefixes:
        for base in base_names:
            roots.append(os.path.join(prefix, base))

    # Exact executable name only — a "quartus_stp*" glob would also match
    # quartus_stpw (the windowed SignalTap GUI), which is not the Tcl shell.
    # ".exe" first on Windows so the shell wins over any extensionless sibling.
    exe_names = ("quartus_stp.exe", "quartus_stp") if os.name == "nt" else ("quartus_stp",)
    # A root may already be a Quartus rootdir (has bin/) or a parent holding
    # one or more version dirs; try all three shapes.
    for root in roots:
        for exe in exe_names:
            for pat in (
                os.path.join(root, "bin*", exe),
                os.path.join(root, "quartus", "bin*", exe),
                os.path.join(root, "*", "quartus", "bin*", exe),
            ):
                for match in sorted(glob.glob(pat), reverse=True):  # newest first
                    if os.path.isfile(match):
                        return match
    return None


class _StpSession:
    """One ``quartus_stp`` process and everything bound to it.

    Built completely, drain threads included, before it is published on the
    transport with a single assignment, so a reader can never pair one
    session's process with another session's output queue.
    """

    __slots__ = ("proc", "out", "err", "threads", "dead")

    def __init__(self, proc: subprocess.Popen) -> None:
        self.proc = proc
        self.out: queue.Queue[str | None] = queue.Queue()
        self.err: list[str] = []
        self.threads: tuple[threading.Thread, ...] = ()
        # Set -- under the transport's I/O lock where a request is involved --
        # once this session must take no further requests.  It lives on the
        # session, not the transport: a transport-wide flag would race
        # connect() installing the next session.
        self.dead = False


class QuartusStpTransport(Transport):
    """
    Intel/Altera USB-Blaster transport through Quartus ``quartus_stp``.

    The Intel RTL wrappers use ``sld_virtual_jtag`` instances rather than
    plain device-level USER opcodes.  Quartus exposes those instances through
    the ``device_virtual_ir_shift`` and ``device_virtual_dr_shift`` Tcl
    commands.  This transport keeps a persistent ``quartus_stp`` Tcl process,
    opens the selected USB-Blaster/device pair, and performs fcapz 49-bit
    register scans through a selected virtual JTAG instance.
    """

    DR_BITS = 49
    BURST_DR_BITS = 256
    ADDR_BURST_PTR = 0x002C
    # Same idle gap used by the other transports for rtl/jtag_reg_iface.v's
    # CDC pipeline between the request scan and the response-capture scan.
    READ_IDLE_CYCLES = 20
    # fcapz Intel wrappers set sld_ir_width=1 and drive ir_out=0, so the
    # virtual IR value is currently fixed at zero.
    VIRTUAL_IR_VALUE = 0
    # read_block / read_timestamp_block burst on burst_data_chain.
    burst_on_data_chain = True
    _SENTINEL = "<<FCAPZ_QUARTUS_STP_DONE>>"
    # close() teardown budget.  The healthy path costs none of it -
    # quartus_stp exits promptly on stdin EOF - and only a wedged process
    # pays, in this order: wait, terminate, kill.
    CLOSE_GRACE_SEC = 5.0
    CLOSE_TERM_SEC = 2.0
    CLOSE_KILL_SEC = 2.0
    CLOSE_JOIN_SEC = 1.0
    # How long close() queues behind another lifecycle transition -- a
    # connect() in its open handshake, say -- before killing the published
    # session so that transition unwinds.
    CLOSE_CONTEND_SEC = 0.5

    def __init__(
        self,
        *,
        hardware_name: str | None = None,
        device_name: str | None = None,
        quartus_stp_path: str | None = None,
        quartus_stp_argv: list[str] | None = None,
        lock_timeout_ms: int = 10_000,
        read_timeout_sec: float | None = None,
        read_idle_cycles: int = READ_IDLE_CYCLES,
        burst_data_chain: int = 2,
        burst_prefill_idle_cycles: int = 160,
        burst: bool = True,
    ):
        """``burst=False`` declares a build with no burst path: every capture
        is then read through the register window.  With ``burst=True`` a
        burst that fails is raised, never read around."""
        self.hardware_name = hardware_name
        self.device_name = device_name
        self._quartus_stp_path = quartus_stp_path
        self._quartus_stp_argv = list(quartus_stp_argv) if quartus_stp_argv else None
        self.lock_timeout_ms = int(lock_timeout_ms)
        self.read_idle_cycles = int(read_idle_cycles)
        self.burst_data_chain = int(burst_data_chain)
        self.burst_prefill_idle_cycles = int(burst_prefill_idle_cycles)
        if read_timeout_sec is None:
            read_timeout_sec = float(os.environ.get("FCAPZ_QUARTUS_TIMEOUT", "60"))
        self.read_timeout_sec = float(read_timeout_sec)
        self._active_chain: int = 1
        # The only mutable reference to session state; see _StpSession.
        self._session: _StpSession | None = None
        self._stp_io_lock = threading.Lock()
        # Serialises session transitions (connect, close, retiring a session
        # whose request timed out).  Lock order is always _life_lock, then
        # _stp_io_lock; nothing takes them the other way round.
        self._life_lock = threading.RLock()
        # Set by cancel(), cleared when a session is torn down.  A cancel that
        # lands before connect() has published its session has no process to
        # kill; connect() checks this right after publishing.
        self._cancel_requested = False
        self.burst = bool(burst)
        # The actual device quartus_stp opened (family/part + IDCODE), filled in
        # by connect(). None until connected. Surfaced so the UI can name the
        # FPGA it attached to, not just the vendor.
        self.opened_device: str | None = None

    @property
    def _proc(self) -> subprocess.Popen | None:
        """The current session's process, or None when not connected."""
        session = self._session
        return None if session is None else session.proc

    def connect(self) -> None:
        self._forget_hub_state()
        argv = self._quartus_stp_argv
        if argv is None:
            quartus_stp = find_quartus_stp(self._quartus_stp_path)
            if not quartus_stp:
                raise RuntimeError(
                    "quartus_stp not found. Add the Quartus bin dir to PATH, set "
                    "$QUARTUS_ROOTDIR, or pass quartus_stp_path=."
                )
            argv = [quartus_stp, "-s"]

        with self._life_lock:
            if self._session is not None:
                # Replacing a live session would leave its process running,
                # still holding the cable, with nothing left to close it.
                # A cancel already aimed at this connect must survive that.
                pending = self._cancel_requested
                self._close_locked()
                self._cancel_requested = pending
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            session = _StpSession(proc)
            try:
                session.threads = (
                    threading.Thread(
                        target=self._drain_stdout, args=(proc.stdout, session.out), daemon=True
                    ),
                    threading.Thread(
                        target=self._drain_stderr, args=(proc.stderr, session.err), daemon=True
                    ),
                )
                for thread in session.threads:
                    thread.start()
            except BaseException:
                # Not published yet, so no close() could ever find it.
                self._reap_killed(session)
                raise
            # Published before the open handshake, so a close() from another
            # thread (a GUI cancel) has a process to kill while it runs.
            self._session = session
            try:
                if self._cancel_requested:
                    raise RuntimeError("quartus_stp connect was cancelled")
                if proc.poll() is not None:
                    self._raise_process_exited(session)
                opened_device = self._send(
                    self._open_device_script(), timeout=self.read_timeout_sec
                )
            except BaseException:
                # A failure here (cable busy, no such device) would otherwise
                # leave quartus_stp running and still holding the USB-Blaster,
                # so the next attempt fails for a reason that has nothing to do
                # with the original one.
                self._close_locked()
                raise
        self.opened_device = self._prettify_device_name(opened_device)
        _quartus_log.info("Opened Quartus JTAG device %s", opened_device)

    def close(self) -> None:
        if self._session is not None:
            self._release_ownership_on_close()
        self._acquire_life_lock_killing()
        try:
            self._close_locked()
        finally:
            self._life_lock.release()

    def cancel(self) -> None:
        """Abort an in-flight request or connect from another thread.

        Kills ``quartus_stp`` without taking any lock: a connect() holds
        ``_life_lock`` through its open handshake, and a cancel must never
        wait on a lock the call it aborts holds.  The owner reconciles with
        :meth:`close`.
        """
        self._cancel_requested = True
        session = self._session
        if session is not None:
            session.dead = True
            self._kill_quietly(session.proc)

    def close_fast(self) -> None:
        """Kill ``quartus_stp`` without the graceful teardown, for Ctrl+C.

        Skips Quartus' own ``close_device``, so the cable is released by
        process exit alone; :meth:`close` is the orderly path.  Still waits up
        to ``CLOSE_KILL_SEC`` for the process to die and joins its threads.
        """
        session = self._session
        if session is not None:
            # First, without any lock: a close() or a stalled request in
            # progress then unblocks at once.
            session.dead = True
            self._kill_quietly(session.proc)
        self._acquire_life_lock_killing()
        try:
            self._cancel_requested = False
            session = self._session
            if session is None:
                return
            self._session = None
            session.dead = True
            self._reap_killed(session)
        finally:
            self._life_lock.release()

    def _acquire_life_lock_killing(self) -> None:
        """Take ``_life_lock`` without queueing behind a long transition.

        A connect() holds the lock through its open handshake, which can take
        up to ``read_timeout_sec``.  Rather than wait that out, kill whatever
        session is published, which makes the holder unwind promptly, and try
        again.  Each round is ``CLOSE_CONTEND_SEC``.
        """
        while not self._life_lock.acquire(timeout=self.CLOSE_CONTEND_SEC):
            session = self._session
            if session is not None:
                session.dead = True
                self._kill_quietly(session.proc)

    def _close_locked(self) -> None:
        """Tear down the current session.  The caller holds ``_life_lock``.

        Bounded.  The graceful phase -- Quartus' own ``close_device``, then
        ``exit`` and stdin EOF -- shares one ``CLOSE_GRACE_SEC`` deadline that
        also covers waiting for the I/O lock; the rest of it goes to waiting
        for the process to exit.  Terminate and kill follow and need no lock,
        so a stalled request elsewhere cannot keep this from returning.

        Also clears a pending cancel: the session it was aimed at is gone.
        """
        self._cancel_requested = False
        session = self._session
        if session is None:
            return
        proc = session.proc
        deadline = time.monotonic() + self.CLOSE_GRACE_SEC
        graceful = not session.dead
        if graceful:
            try:
                self._send(
                    "catch {close_device}",
                    timeout=min(self._remaining(deadline), self.read_timeout_sec),
                    session=session,
                )
            except Exception:
                _quartus_log.debug("quartus_stp close_device failed", exc_info=True)
            if self._session is not session:
                return  # it timed out, and _send already retired it
        # Re-read: a request on another thread may have timed out meanwhile,
        # and then there is no point asking the process to exit politely.
        graceful = not session.dead
        self._session = None
        # Any request still queued for this session must now refuse it.
        session.dead = True
        if graceful and proc.stdin is not None:
            # Only with the I/O lock: another thread may be mid-write, and
            # interleaving "exit" into its script would corrupt both.
            if self._stp_io_lock.acquire(timeout=self._remaining(deadline)):
                try:
                    self._write_exit(proc)
                finally:
                    self._stp_io_lock.release()
        self._wait_for_exit(proc, self._remaining(deadline))
        self._join_threads(session.threads)
        self._close_pipes(session)

    def _retire_session(self, session: _StpSession) -> None:
        """Kill and reap *session*, whose request timed out.

        The caller has already marked it dead under the I/O lock.  Only that
        session is detached: one connect() installed meanwhile stays open.
        Callers must not hold ``_stp_io_lock`` (lock order).
        """
        with self._life_lock:
            if self._session is session:
                self._session = None
            self._reap_killed(session)

    @staticmethod
    def _remaining(deadline: float) -> float:
        return max(0.0, deadline - time.monotonic())

    @staticmethod
    def _kill_quietly(proc: subprocess.Popen) -> None:
        try:
            proc.kill()
        except Exception:
            _quartus_log.debug("quartus_stp kill failed", exc_info=True)

    @staticmethod
    def _write_exit(proc: subprocess.Popen) -> None:
        try:
            proc.stdin.write("exit\n")
            proc.stdin.flush()
        except Exception:
            _quartus_log.debug("quartus_stp exit write failed", exc_info=True)
        try:
            # EOF makes quartus_stp -s exit even if the "exit" line was never
            # parsed.
            proc.stdin.close()
        except Exception:
            _quartus_log.debug("quartus_stp stdin close failed", exc_info=True)

    def _wait_for_exit(self, proc: subprocess.Popen, grace_sec: float) -> None:
        """Block until *proc* is really gone, escalating if it will not go.

        Returning while quartus_stp is still alive leaves the USB-Blaster
        claimed, so a script that closes one connection and opens another
        races its own previous process for the cable.
        """
        for timeout, signal in (
            (grace_sec, None),
            (self.CLOSE_TERM_SEC, proc.terminate),
            (self.CLOSE_KILL_SEC, proc.kill),
        ):
            if signal is not None:
                try:
                    signal()
                except Exception:
                    _quartus_log.debug("quartus_stp signal failed", exc_info=True)
            try:
                proc.wait(timeout=timeout)
                return
            except subprocess.TimeoutExpired:
                continue
        _quartus_log.warning(
            "quartus_stp (pid %s) would not exit; the USB-Blaster may stay "
            "claimed until it does",
            proc.pid,
        )

    def _reap_killed(self, session: _StpSession) -> None:
        proc = session.proc
        self._kill_quietly(proc)
        try:
            proc.wait(timeout=self.CLOSE_KILL_SEC)
        except subprocess.TimeoutExpired:
            _quartus_log.warning(
                "quartus_stp (pid %s) survived kill; the USB-Blaster may stay "
                "claimed until it exits",
                proc.pid,
            )
        self._join_threads(session.threads)
        self._close_pipes(session)

    def _join_threads(self, threads: tuple[threading.Thread, ...]) -> None:
        for thread in threads:
            if thread is not threading.current_thread() and thread.is_alive():
                thread.join(timeout=self.CLOSE_JOIN_SEC)

    def _close_pipes(self, session: _StpSession) -> None:
        """Close *session*'s pipes, skipping any that could block.

        Closing a pipe waits for whichever thread is using it.  A drain thread
        can still be reading after quartus_stp exits if a process it started
        inherited the write end, and this runs under ``_life_lock``, so an
        output pipe is closed only once its drain thread has finished, and
        stdin only if no request holds the I/O lock.  A skipped pipe is left
        to garbage collection.
        """
        proc = session.proc
        readers = dict(zip((id(proc.stdout), id(proc.stderr)), session.threads))
        for pipe in (proc.stdout, proc.stderr):
            if pipe is None:
                continue
            reader = readers.get(id(pipe))
            if reader is not None and reader.is_alive():
                _quartus_log.debug(
                    "quartus_stp output pipe still being read; left open (pid %s)", proc.pid
                )
                continue
            self._close_quietly(pipe)
        if proc.stdin is not None:
            if self._stp_io_lock.acquire(blocking=False):
                try:
                    self._close_quietly(proc.stdin)
                finally:
                    self._stp_io_lock.release()

    @staticmethod
    def _close_quietly(pipe: IO[str]) -> None:
        try:
            pipe.close()
        except Exception:
            _quartus_log.debug("quartus_stp pipe close failed", exc_info=True)

    def select_chain(self, chain: int) -> None:
        if chain < 1:
            raise ValueError(f"virtual JTAG instance index must be >= 1, got {chain}")
        self._active_chain = chain

    #: ``sld_virtual_jtag`` instance indices discovery tries.  A missing
    #: instance fails its first scan without shifting anything.
    DISCOVERY_INSTANCES = tuple(range(1, 9))

    def discovery_chains(self) -> tuple[int, ...]:
        return self.DISCOVERY_INSTANCES

    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        if width < 1:
            raise ValueError(f"DR scan width must be positive, got {width}")
        instance = self._active_chain if chain is None else chain
        self._validate_instance(instance)
        captured = self._send(
            self._locked_script(
                body=[
                    self._virtual_ir_tcl(instance),
                    self._dr_shift_tcl(instance, bits, width, "__fcapz_capture"),
                ],
                result="__fcapz_capture",
                status="__fcapz_scan_status",
                error="__fcapz_scan_error",
            )
        )
        return self._shift_string_to_int(captured.strip(), width)

    def raw_dr_scan_batch(
        self, scans: list[tuple[int, int]], *, chain: int | None = None
    ) -> list[int]:
        if not scans:
            return []
        instance = self._active_chain if chain is None else chain
        self._validate_instance(instance)
        body = ["set __fcapz_captures {}"]
        body.append(self._virtual_ir_tcl(instance))
        for idx, (bits, width) in enumerate(scans):
            if width < 1:
                raise ValueError(f"DR scan width must be positive, got {width}")
            var = f"__fcapz_capture_{idx}"
            body.append(self._dr_shift_tcl(instance, bits, width, var))
            body.append(f"lappend __fcapz_captures ${var}")
        captured = self._send(
            self._locked_script(
                body=body,
                result="__fcapz_captures",
                status="__fcapz_batch_status",
                error="__fcapz_batch_error",
            )
        )
        tokens = captured.split()
        if len(tokens) != len(scans):
            raise RuntimeError(
                f"Quartus batch DR scan returned {len(tokens)} values, "
                f"expected {len(scans)}: {captured!r}"
            )
        return [
            self._shift_string_to_int(token, width)
            for token, (_bits, width) in zip(tokens, scans)
        ]

    def write_reg(self, addr: int, value: int) -> None:
        frame = (1 << 48) | ((addr & 0xFFFF) << 32) | (value & 0xFFFFFFFF)
        instance = self._active_chain
        self._validate_instance(instance)
        self._send(
            self._locked_script(
                body=[
                    *self._slot_select_body(instance, [addr]),
                    self._virtual_ir_tcl(instance),
                    self._dr_shift_tcl(instance, frame, self.DR_BITS, "__fcapz_capture"),
                ],
                result="__fcapz_capture",
                status="__fcapz_scan_status",
                error="__fcapz_scan_error",
            )
        )

    def read_reg(self, addr: int) -> int:
        read_frame = (addr & 0xFFFF) << 32
        instance = self._active_chain
        shifted_out = self._send(
            self._locked_script(
                body=[
                    *self._slot_select_body(instance, [addr]),
                    self._virtual_ir_tcl(instance),
                    self._dr_shift_tcl(
                        instance, read_frame, self.DR_BITS, "__fcapz_discard"
                    ),
                    f"device_run_test_idle -num_clocks {self.read_idle_cycles}",
                    self._dr_shift_tcl(
                        instance, read_frame, self.DR_BITS, "__fcapz_capture"
                    ),
                ],
                result="__fcapz_capture",
                status="__fcapz_read_status",
                error="__fcapz_read_error",
            )
        )
        return self._shift_string_to_int(shifted_out, self.DR_BITS) & 0xFFFFFFFF

    def bursts_data_window(self, *, timestamp: bool = False) -> bool:
        return self._burst_available

    def read_block(self, addr: int, words: int) -> List[int]:
        if words <= 0:
            return []
        if addr == 0x0100 and self.bursts_data_window():
            return self._read_block_burst(words)
        return self.read_window_block(addr, words)

    def read_window_block(self, addr: int, words: int) -> List[int]:
        if words <= 0:
            return []
        check_data_window(addr, words, self.data_window_end)
        return self._locked_reads([addr + i * 4 for i in range(words)], head=[])

    def read_regs_after_write(
        self, write_addr: int, value: int, addrs: List[int]
    ) -> List[int]:
        """The write and the reads run in one locked script."""
        # One unit with the chain and slot read once: hold off any other
        # thread's scope, as the base implementation does.
        with self.transaction_lock():
            if not addrs:
                self.write_reg(write_addr, value)
                return []
            instance = self._active_chain
            frame = (1 << 48) | ((write_addr & 0xFFFF) << 32) | (value & 0xFFFFFFFF)
            head = [
                self._virtual_ir_tcl(instance),
                self._dr_shift_tcl(instance, frame, self.DR_BITS, "__fcapz_write_discard"),
                f"device_run_test_idle -num_clocks {self.read_idle_cycles}",
            ]
            return self._locked_reads(addrs, head=head, select_addrs=[write_addr])

    def _locked_reads(
        self, addrs: List[int], *, head: list[str], select_addrs: List[int] = ()
    ) -> List[int]:
        """Read each of *addrs* on the active instance in one locked script,
        after the slot selection for all of them and the commands in *head*."""
        instance = self._active_chain
        body = [
            "set __fcapz_reads {}",
            *self._slot_select_body(instance, [*select_addrs, *addrs]),
            *head,
            self._virtual_ir_tcl(instance),
        ]
        for i, addr in enumerate(addrs):
            read_frame = (addr & 0xFFFF) << 32
            body.append(
                self._dr_shift_tcl(
                    instance, read_frame, self.DR_BITS, f"__fcapz_discard_{i}"
                )
            )
            body.append(f"device_run_test_idle -num_clocks {self.read_idle_cycles}")
            body.append(
                self._dr_shift_tcl(
                    instance, read_frame, self.DR_BITS, f"__fcapz_capture_{i}"
                )
            )
            body.append(f"lappend __fcapz_reads $__fcapz_capture_{i}")
        captured = self._send(
            self._locked_script(
                body=body,
                result="__fcapz_reads",
                status="__fcapz_read_block_status",
                error="__fcapz_read_block_error",
            )
        )
        tokens = captured.split()
        if len(tokens) != len(addrs):
            raise RuntimeError(
                f"Quartus read_block returned {len(tokens)} values, expected "
                f"{len(addrs)}: {captured!r}"
            )
        return [
            self._shift_string_to_int(token, self.DR_BITS) & 0xFFFFFFFF
            for token in tokens
        ]

    def read_timestamp_block(
        self, addr: int, words: int, timestamp_width: int
    ) -> List[int]:
        """Read timestamp words through the Intel/Altera DATA_CHAIN burst path."""
        if words <= 0:
            return []
        if timestamp_width > 0 and self.bursts_data_window(timestamp=True):
            return self._read_block_burst(
                words,
                timestamp=True,
                element_width=timestamp_width,
            )
        return self.read_block(addr, words)

    def read_run_length_block(
        self, n_entries: int, lane_width: int, *, on_control_chain: bool = False
    ) -> List[int]:
        """Read one run count per captured entry through the DATA_CHAIN burst,
        or with *on_control_chain* (a core manager's slot) through the
        single-chain burst on the active instance.

        Counts travel on the timestamp lane, ``lane_width`` bits per element
        (the core's timestamp width, or its RLE_W without timestamps).  Raises
        :class:`BurstUnavailableError`, before any scan, when burst readout is
        off, so the caller can read the window instead.
        """
        if n_entries <= 0:
            return []
        if not self._burst_available:
            raise BurstUnavailableError("burst readout is off for this transport")
        if on_control_chain:
            return self._single_chain_burst(
                n_entries, lane_width, timestamp=True, run_lengths=True
            )
        return self._read_block_burst(
            n_entries,
            timestamp=True,
            element_width=lane_width,
            run_lengths=True,
        )

    @property
    def _burst_available(self) -> bool:
        """Declared by the ``burst`` constructor argument, never probed."""
        return self.burst

    def _burst_sample_width(self) -> int:
        """Bits per sample in a burst scan: the selected core's SAMPLE_W, read
        for every burst so a slot switch cannot leave a stale width."""
        return _burst_element_width(self.read_reg(0x000C), self.BURST_DR_BITS)

    def _read_block_burst(
        self,
        words: int,
        *,
        timestamp: bool = False,
        element_width: int | None = None,
        run_lengths: bool = False,
    ) -> List[int]:
        if timestamp:
            if element_width is None:
                element_width = 32
            per_scan = max(1, self.BURST_DR_BITS // element_width)
        else:
            element_width = self._burst_sample_width()
            per_scan = max(1, self.BURST_DR_BITS // element_width)
        n_scans = (words + per_scan - 1) // per_scan
        prime_scans = 1
        ctrl_chain = self._active_chain
        burst_frame = (
            (1 << 48)
            | (self.ADDR_BURST_PTR << 32)
            | (0x80000000 if timestamp else 0)
            | (0x40000000 if timestamp and run_lengths else 0)  # run counts
        )

        def write_ptr() -> list[str]:
            return [
                self._virtual_ir_tcl(ctrl_chain),
                self._dr_shift_tcl(
                    ctrl_chain, burst_frame, self.DR_BITS, "__fcapz_burst_ptr_discard"
                ),
                f"device_run_test_idle -num_clocks {self.burst_prefill_idle_cycles}",
            ]

        # Select the slot before BURST_PTR, which makes it the burst owner;
        # never between burst scans, where any command scan ends burst mode.
        body = [
            "set __fcapz_burst {}",
            *self._slot_select_body(ctrl_chain, [self.ADDR_BURST_PTR]),
            *write_ptr(),
        ]
        if self.burst_start_sync:
            # See Transport.burst_start_sync.
            body += [
                self._virtual_ir_tcl(self.burst_data_chain),
                self._dr_shift_tcl(
                    self.burst_data_chain, 0, self.BURST_DR_BITS, "__fcapz_burst_sync"
                ),
                *write_ptr(),
            ]
        body.append(self._virtual_ir_tcl(self.burst_data_chain))
        for idx in range(n_scans + prime_scans):
            var = f"__fcapz_burst_{idx}"
            body.append(
                self._dr_shift_tcl(
                    self.burst_data_chain, 0, self.BURST_DR_BITS, var
                )
            )
            body.append(f"lappend __fcapz_burst ${var}")
        if self.burst_data_chain == ctrl_chain:
            body += self._burst_drain_body(ctrl_chain)
        captured = self._send(
            self._locked_script(
                body=body,
                result="__fcapz_burst",
                status="__fcapz_burst_status",
                error="__fcapz_burst_error",
            )
        )
        tokens = captured.split()
        if tokens and self.burst_data_chain == ctrl_chain:
            self._check_burst_header(
                self._shift_string_to_int(tokens[0], self.BURST_DR_BITS),
                timestamp=timestamp,
            )
        return self._parse_burst_tokens(
            tokens,
            words,
            skip_scans=prime_scans,
            element_width=element_width,
        )

    def _parse_burst_tokens(
        self,
        tokens: list[str],
        total_words: int,
        *,
        skip_scans: int,
        element_width: int,
    ) -> List[int]:
        values: list[int] = []
        mask = (1 << element_width) - 1
        per_scan = max(1, self.BURST_DR_BITS // element_width)
        for scan_idx, token in enumerate(tokens):
            if scan_idx < skip_scans:
                continue
            scan_value = self._shift_string_to_int(token, self.BURST_DR_BITS)
            for sample_idx in range(per_scan):
                if len(values) >= total_words:
                    break
                values.append((scan_value >> (sample_idx * element_width)) & mask)
        if len(values) != total_words:
            raise RuntimeError(
                f"Quartus DATA_CHAIN burst returned {len(values)} values, "
                f"expected {total_words}: {tokens!r}"
            )
        return values

    def read_sample_block(
        self, base_addr: int, n_samples: int, sample_width: int,
        *, on_control_chain: bool = True,
    ) -> List[int]:
        """Read *n_samples* whole samples via single-chain burst on the active chain.

        *on_control_chain* is accepted for the shared signature; this reader
        always bursts on the active chain.

        Returns ``ceil(sample_width / 32)`` little-endian 32-bit words per
        sample — the exact flat layout ``Analyzer.capture()`` reassembles.

        This is the fast path for a wide, single-chain core such as the 160-bit
        AXI monitor, whose burst DR shares one BSCAN instance with its control
        frames (``jtag_pipe_iface``).  One 256-bit scan carries
        ``256 // sample_width`` samples (one, for the 160-bit monitor), so the
        whole buffer streams in ~``n_samples`` DR scans instead of
        ``n_samples * ceil(width/32)`` per-word register reads — ~15x fewer
        quartus_stp commands, which is where the readback time actually goes.

        The two-chain :meth:`_read_block_burst` shifts on ``burst_data_chain``
        (the ELA's legacy DATA_CHAIN); a single-chain core has no such chain, so
        the burst scans go on the control chain itself.  Raises
        :class:`BurstUnavailableError`, before any scan, when burst readout is
        off, and :class:`BurstIntegrityError` when a burst ran but returned the
        wrong number of samples; that is never read around.
        """
        if not self._burst_available:
            raise BurstUnavailableError("burst readout is off for this transport")
        elements = self._single_chain_burst(
            n_samples, sample_width, timestamp=False
        )
        # Split each whole sample into little-endian 32-bit words -- the flat
        # layout Analyzer.capture() reassembles.
        words_per_sample = (sample_width + 31) // 32
        words: List[int] = []
        for sample in elements:
            for w in range(words_per_sample):
                words.append((sample >> (w * 32)) & 0xFFFFFFFF)
        return words

    def read_timestamp_block_single_chain(
        self, base_addr: int, n_timestamps: int, timestamp_width: int,
        *, on_control_chain: bool = True,
    ) -> List[int]:
        """Read per-sample timestamps via single-chain burst on the active chain.

        The wide, single-chain cores handled by :meth:`read_sample_block` keep
        their timestamp window behind the *same* BSCAN instance, so the
        two-chain :meth:`read_timestamp_block` (which shifts on the ELA's
        separate ``burst_data_chain``) can never reach them.  This mirrors the
        sample burst but asserts the timestamp-select bit in the burst pointer,
        returning one value per captured sample.  Raises
        :class:`BurstUnavailableError`, before any scan, when burst readout is
        off, and :class:`BurstIntegrityError` when a burst ran but returned the
        wrong number of timestamps.
        """
        if not self._burst_available:
            raise BurstUnavailableError("burst readout is off for this transport")
        return self._single_chain_burst(
            n_timestamps, timestamp_width, timestamp=True
        )

    def _single_chain_burst(
        self,
        n_elements: int,
        element_width: int,
        *,
        timestamp: bool,
        run_lengths: bool = False,
    ) -> List[int]:
        """Stream ``n_elements`` of ``element_width`` bits, all on the active
        (control) chain -- one 256-bit DR carries ``256 // element_width``
        elements.  ``timestamp`` selects the burst engine's timestamp window
        instead of the sample window; with ``run_lengths`` too it carries the
        run counts of a run-length capture.  Returns masked element values."""
        if n_elements <= 0:
            return []
        if element_width < 1:
            raise ValueError(f"element_width must be >= 1, got {element_width}")
        per_scan = max(1, self.BURST_DR_BITS // element_width)
        n_scans = (n_elements + per_scan - 1) // per_scan
        prime_scans = 1
        chain = self._active_chain
        # write bit | BURST_PTR addr | data: bit31 selects the timestamp window,
        # bit30 with it the run counts, else 0 to start at sample 0.
        burst_frame = (
            (1 << 48)
            | (self.ADDR_BURST_PTR << 32)
            | (0x80000000 if timestamp else 0)
            | (0x40000000 if timestamp and run_lengths else 0)
        )

        write_ptr = [
            self._dr_shift_tcl(chain, burst_frame, self.DR_BITS, "__fcapz_scb_ptr"),
            f"device_run_test_idle -num_clocks {self.burst_prefill_idle_cycles}",
        ]
        body = [
            "set __fcapz_scb {}",
            *self._slot_select_body(chain, [self.ADDR_BURST_PTR]),
            self._virtual_ir_tcl(chain),
            *write_ptr,
        ]
        if self.burst_start_sync:
            # See Transport.burst_start_sync.
            body += [
                self._dr_shift_tcl(chain, 0, self.BURST_DR_BITS, "__fcapz_scb_sync"),
                *write_ptr,
            ]
        # First scan primes/flushes the 256-bit staging register; discarded.
        for idx in range(n_scans + prime_scans):
            var = f"__fcapz_scb_{idx}"
            body.append(
                self._dr_shift_tcl(chain, 0, self.BURST_DR_BITS, var)
            )
            body.append(f"lappend __fcapz_scb ${var}")
        body += self._burst_drain_body(chain)
        captured = self._send(
            self._locked_script(
                body=body,
                result="__fcapz_scb",
                status="__fcapz_scb_status",
                error="__fcapz_scb_error",
            )
        )
        tokens = captured.split()
        if tokens:
            self._check_burst_header(
                self._shift_string_to_int(tokens[0], self.BURST_DR_BITS),
                timestamp=timestamp,
            )
        return self._parse_single_chain_burst(
            tokens,
            n_elements,
            element_width,
            skip_scans=prime_scans,
        )

    def _parse_single_chain_burst(
        self,
        tokens: list[str],
        n_elements: int,
        element_width: int,
        *,
        skip_scans: int,
    ) -> List[int]:
        per_scan = max(1, self.BURST_DR_BITS // element_width)
        mask = (1 << element_width) - 1
        values: list[int] = []
        for scan_idx, token in enumerate(tokens):
            if scan_idx < skip_scans:
                continue
            scan_value = self._shift_string_to_int(token, self.BURST_DR_BITS)
            for s in range(per_scan):
                if len(values) >= n_elements:
                    break
                values.append((scan_value >> (s * element_width)) & mask)
        if len(values) != n_elements:
            raise BurstIntegrityError(
                f"Quartus single-chain burst returned {len(values)} values, "
                f"expected {n_elements}: {tokens!r}"
            )
        return values

    def _validate_instance(self, instance: int) -> None:
        if instance < 1:
            raise ValueError(
                f"virtual JTAG instance index must be >= 1, got {instance}"
            )

    # The selection is shifted inside the access's own device_lock, and the
    # JTAG server runs no other client's scans on the device while it is held.
    atomic_slot_select = True

    def _slot_select_body(self, instance: int, addrs: List[int]) -> list[str]:
        """Commands that write the calling thread's slot selection (see
        :meth:`Transport.slot_scope`), for the head of a locked script whose
        accesses reach *addrs* on *instance*.

        Nothing when no slot is selected, when the access is on another
        instance, or when every address is in the manager's own block: the
        manager answers those for any slot, and a select ahead of a read of
        ``MGR_ACTIVE`` would overwrite what the read is after.
        """
        sel = self.current_slot_selection()
        if sel is None or sel.chain != instance:
            return []
        if sel.chain not in self.__dict__.get("_fcapz_manager_chains", ()):
            # Not (or no longer) known to hold a manager: on any other core
            # 0xF008 is some other register, an EJTAG-AXI bridge's reset.
            return []
        if addrs and all(_in_manager_block(a) for a in addrs):
            return []
        # This script moves MGR_ACTIVE behind the cache, and may fail after
        # doing so: a later cached select must write for real.
        self.invalidate_manager_instance_cache()
        self._count_manager_select(sel.chain)
        body = [self._virtual_ir_tcl(sel.chain)]
        caps = self.__dict__.get("_fcapz_manager_caps", {}).get(sel.chain, 0)
        if not caps & 0x08:
            # A manager without epochs (MGR_CAPS bit 3) ignores an ACTIVE
            # write while its burst engine loads, which another client's burst
            # can leave it doing: a VERSION read ends burst mode first, and the
            # idle outlasts the last fill.
            body += [
                self._dr_shift_tcl(sel.chain, 0, self.DR_BITS, "__fcapz_select_drain"),
                f"device_run_test_idle -num_clocks {self.BURST_DRAIN_IDLE_CYCLES}",
            ]
        frame = (
            (1 << 48) | ((sel.active_addr & 0xFFFF) << 32) | (sel.slot & 0xFFFFFFFF)
        )
        return body + [
            self._dr_shift_tcl(sel.chain, frame, self.DR_BITS, "__fcapz_select_discard"),
            f"device_run_test_idle -num_clocks {self.read_idle_cycles}",
        ]

    def _burst_drain_body(self, instance: int) -> list[str]:
        """Commands that leave *instance*'s pipe idle after a burst on it.

        Until a command scan ends burst mode, every capture on the chain
        starts another staging fill, and a core manager without epochs
        ignores an ``MGR_ACTIVE`` write while one runs.  A VERSION read ends
        it, and the idle outlasts the fill."""
        return [
            self._virtual_ir_tcl(instance),
            self._dr_shift_tcl(instance, 0, self.DR_BITS, "__fcapz_drain_discard"),
            f"device_run_test_idle -num_clocks {self.BURST_DRAIN_IDLE_CYCLES}",
        ]

    def _virtual_ir_tcl(self, instance: int) -> str:
        return (
            "set __fcapz_ir_discard [device_virtual_ir_shift "
            f"-instance_index {instance} "
            f"-ir_value {self.VIRTUAL_IR_VALUE} "
            "-no_captured_ir_value]"
        )

    def _dr_shift_tcl(self, instance: int, bits: int, width: int, result_var: str) -> str:
        bit_string = self._int_to_shift_string(bits, width)
        return (
            f"set {result_var} [device_virtual_dr_shift "
            f"-instance_index {instance} "
            f"-length {width} "
            f"-dr_value {bit_string}]"
        )

    def _locked_script(
        self,
        *,
        body: list[str],
        result: str | None = None,
        status: str,
        error: str,
    ) -> str:
        if not body:
            raise ValueError("locked Quartus Tcl script body must not be empty")
        lines = [
            f"device_lock -timeout {self.lock_timeout_ms}",
            f"set {status} [catch {{",
            *body,
            f"}} {error}]",
            "device_unlock",
            f"if {{${status}}} {{",
            f"    error ${error}",
            "}",
        ]
        if result is not None:
            lines.append(f"set {result}")
        return "\n".join(lines)

    def _open_device_script(self) -> str:
        lines = [
            "package require ::quartus::jtag",
        ]
        if self.hardware_name:
            lines.append(f"set __fcapz_hardware {_tcl_braced(self.hardware_name)}")
        else:
            lines.extend(
                [
                    "set __fcapz_hardware_matches [get_hardware_names]",
                    "if {[llength $__fcapz_hardware_matches] == 0} {",
                    '    error "no Quartus JTAG hardware found"',
                    "}",
                    "if {[llength $__fcapz_hardware_matches] > 1} {",
                    '    error "multiple Quartus JTAG cables found; pass --hardware"',
                    "}",
                    "set __fcapz_hardware [lindex $__fcapz_hardware_matches 0]",
                ]
            )
        if self.device_name:
            lines.append(f"set __fcapz_device {_tcl_braced(self.device_name)}")
        else:
            lines.extend(
                [
                    "set __fcapz_device {}",
                    "foreach __name [get_device_names -hardware_name $__fcapz_hardware] {",
                    '    if {[string match "@1*" $__name]} {',
                    "        set __fcapz_device $__name",
                    "        break",
                    "    }",
                    "}",
                    'if {$__fcapz_device eq ""} {',
                    '    error "no @1 device found on selected USB-Blaster chain"',
                    "}",
                ]
            )
        lines.append(
            "open_device -hardware_name $__fcapz_hardware -device_name $__fcapz_device"
        )
        lines.append("set __fcapz_device")
        return "\n".join(lines)

    def _send(
        self,
        script: str,
        *,
        timeout: float | None = None,
        session: _StpSession | None = None,
    ) -> str:
        """Run *script* in quartus_stp and return its last output line.

        With *timeout* None this is a normal request: it waits for the I/O
        lock and allows ``read_timeout_sec`` between output lines.  With a
        number it is an overall deadline for the whole request, lock wait
        included, that output arriving without the sentinel cannot extend.

        *session* defaults to the current one, read once: connect() may
        publish a new session while this request is in flight, and the request
        keeps talking to the one it started on.
        """
        session = self._session if session is None else session
        if session is None:
            raise RuntimeError("not connected - call connect() first")
        if session.dead:
            raise RuntimeError("quartus_stp transport is closed or timed out; reconnect")
        proc = session.proc
        if not proc.stdin or not proc.stdout:
            raise RuntimeError("not connected - call connect() first")
        if self._SENTINEL in script:
            raise ValueError("quartus_stp Tcl script contains the response sentinel")
        wrapped = "\n".join(
            [
                "set __fcapz_status [catch {",
                script,
                "} __fcapz_result]",
                "if {$__fcapz_status} {",
                '    puts "ERROR: $__fcapz_result"',
                "} else {",
                "    puts $__fcapz_result",
                "}",
                f"puts {self._SENTINEL}",
                "flush stdout",
            ]
        )
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        if deadline is None:
            self._stp_io_lock.acquire()
        elif not self._stp_io_lock.acquire(timeout=self._remaining(deadline)):
            raise TimeoutError(
                f"quartus_stp is busy with another request; not sent within {timeout:.1f}s"
            )
        waited: float | None = None
        answered = False
        try:
            # Checked again under the lock: a request that timed out on this
            # session marks it dead before releasing the lock, and its late
            # response must not be read as this request's.
            if session.dead:
                raise RuntimeError("quartus_stp transport is closed or timed out; reconnect")
            if proc.poll() is not None:
                self._raise_process_exited(session)
            proc.stdin.write(wrapped + "\n")
            proc.stdin.flush()
            lines: list[str] = []
            while True:
                if deadline is None:
                    wait_sec = self.read_timeout_sec
                else:
                    # Explicitly: Queue.get(timeout=0) still returns an item
                    # when one is queued, so steady output would otherwise
                    # keep the request alive past its deadline.
                    wait_sec = self._remaining(deadline)
                    if wait_sec <= 0.0:
                        waited = float(timeout)
                        break
                try:
                    raw = session.out.get(timeout=wait_sec)
                except queue.Empty:
                    waited = self.read_timeout_sec if deadline is None else float(timeout)
                    break
                if raw is None:
                    stderr = "\n".join(session.err[-20:])
                    raise ConnectionError(
                        f"quartus_stp process exited unexpectedly. stderr:\n{stderr}"
                    )
                line = self._strip_quartus_prompt(raw.rstrip("\n\r"))
                if line.strip() == self._SENTINEL:
                    answered = True
                    break
                if line:
                    lines.append(line)
        finally:
            if not answered:
                # Timed out, interrupted (Ctrl+C) or failed after the script
                # may have been sent: its answer can still arrive, and the
                # next request would read it as its own.  Marked before the
                # lock is released, so that request cannot get in first.
                session.dead = True
            self._stp_io_lock.release()
        if waited is not None:
            # Outside the I/O lock: retiring takes _life_lock, and connect()
            # and close() take that one first.
            self._retire_session(session)
            raise TimeoutError(
                "timed out waiting for quartus_stp response sentinel "
                f"after {waited:.1f}s; reconnect required"
            )
        first_error = next(
            (idx for idx, line in enumerate(lines) if line.startswith("ERROR: ")),
            None,
        )
        if first_error is not None:
            detail = "\n".join(lines[first_error:])
            if "virtual JTAG instance cannot be found" in detail:
                # quartus_stp emits this only when the requested sld_virtual_jtag
                # node is absent from the bitstream -- i.e. the FPGA carries no
                # fpgacapZero cores. The connection itself is fine, so say that
                # plainly instead of the raw JTAG-instance wording, which reads
                # like a cable/chain fault.
                raise RuntimeError(
                    "No fpgacapZero-compatible cores found on the device. The "
                    "FPGA is reachable but presents no fpgacapZero cores -- "
                    "check that it is configured with an fpgacapZero build."
                )
            raise RuntimeError(detail)
        return lines[-1].strip() if lines else ""

    @staticmethod
    def _prettify_device_name(opened: str) -> str | None:
        """Tidy quartus_stp's opened-device string for display.

        ``open_device`` echoes names like ``@1: A5EB013BB23BCS(...)  (0x4362C0DD)``
        -- the leading ``@N:`` is the chain position, not part of the device.
        Strip it and collapse whitespace; return None for an empty result so the
        UI simply omits the device rather than showing a blank.
        """
        name = " ".join((opened or "").split())
        name = re.sub(r"^@\d+:\s*", "", name)
        return name or None

    @staticmethod
    def _strip_quartus_prompt(line: str) -> str:
        stripped = line.strip()
        while True:
            if stripped.startswith("tcl>"):
                stripped = stripped[4:].lstrip()
                continue
            if stripped.startswith(">"):
                stripped = stripped[1:].lstrip()
                continue
            return stripped

    def _raise_process_exited(self, session: _StpSession | None = None) -> None:
        session = self._session if session is None else session
        if session is None:
            raise RuntimeError("not connected - call connect() first")
        code = session.proc.poll()
        if code is None:
            return
        stderr = "\n".join(session.err[-20:])
        raise ConnectionError(
            f"quartus_stp exited with status {code}. stderr:\n{stderr}"
        )

    def _drain_stderr(self, stderr: IO[str], sink: list[str]) -> None:
        # Bound at thread creation, for the reason given on _drain_stdout.
        for raw in stderr:
            sink.append(raw.rstrip("\n\r"))

    def _drain_stdout(self, stdout: IO[str], sink: "queue.Queue[str | None]") -> None:
        # The stream and the sink are arguments, never read off self.
        # connect() installs a fresh queue, so a drain thread still
        # finishing with the previous process would otherwise deliver its
        # EOF marker into the new connection's queue, and the first scan
        # after a reconnect would fail with 'process exited unexpectedly'.
        for raw in stdout:
            sink.put(raw)
        sink.put(None)

    @staticmethod
    def _int_to_shift_string(value: int, width: int) -> str:
        # Quartus' binary DR operand is a normal fixed-width numeric string.
        # Its documented example maps "010001" to hex 0x11 and shifts the
        # rightmost/least-significant bit first.
        mask = (1 << width) - 1
        return f"{value & mask:0{width}b}"

    @staticmethod
    def _shift_string_to_int(value: str, width: int) -> int:
        bits = re.sub(r"\s+", "", value)
        if not re.fullmatch(r"[01]+", bits):
            raise RuntimeError(f"Quartus virtual DR scan returned non-binary data: {value!r}")
        if len(bits) != width:
            raise RuntimeError(
                f"Quartus virtual DR scan returned {len(bits)} bits, expected {width}: "
                f"{value!r}"
            )
        return int(bits, 2)


class XilinxHwServerTransport(Transport):
    """
    Xilinx hw_server transport using a persistent XSDB session.

    Keeps an ``xsdb`` process alive and sends TCL commands over stdin.
    This avoids the overhead of spawning a new process per register access
    and enables efficient batched ``read_block`` operations.
    A mutex serializes :meth:`_send` so concurrent threads (e.g. GUI EIO
    polling and ELA capture) cannot interleave on the single process.

    Uses the ``-bits`` format for ``drshift`` which provides standard JTAG
    bit ordering (``-hex`` has a non-standard byte/nibble mapping in XSDB).

    49-bit DR frame (bit string, position k = sr[k]):
        bits[31:0]  = wdata / rdata
        bits[47:32] = addr[15:0]
        bits[48]    = rnw  (1 = write, 0 = read)
    """

    # Default BSCANE2 IR codes for Xilinx 7-series.
    # USER1 (0x02) and USER2 (0x03) are verified.
    # Verified on xc7a100t (Arty A7): USER1=0x02, USER2=0x03, USER3=0x22, USER4=0x23.
    DEFAULT_IR_TABLE: dict[int, int] = {1: 0x02, 2: 0x03, 3: 0x22, 4: 0x23}

    # Named IR-table presets for the Xilinx families this transport
    # supports out of the box.  Pass via the ``ir_table`` constructor
    # argument or assign one of these to ``ir_table`` after construction.
    # The 7-series preset is the default and matches DEFAULT_IR_TABLE
    # above; the UltraScale preset is documented in UG570 / UG574 and
    # used by the rtl/jtag_tap_xilinxus.v wrapper instantiations.
    IR_TABLE_XILINX7: dict[int, int] = {1: 0x02, 2: 0x03, 3: 0x22, 4: 0x23}
    IR_TABLE_XILINX_ULTRASCALE: dict[int, int] = {
        1: 0x24, 2: 0x25, 3: 0x26, 4: 0x27,
    }
    # Zynq UltraScale+ MPSoC PL TAP (xck26 / xczu*), raw-opcode mode.
    # The supported MPSoC path is ``use_register_ir=True`` (the CLI picks
    # it), where xsdb routes the IR and pads the DR itself; this table is
    # kept for raw-mode experiments.  In raw mode xsdb at the PL-TAP
    # target level pads the ARM DAP's **IR** but not its **DR**: the
    # DAP's 1-bit BYPASS register is still in series with the PL's DR, so
    # pair this table with ``ir_length=12`` and ``dr_extra_bits=1``.
    # ``dr_extra_position="tdi"`` matched a KV260 TDO trace, which assumed
    # ``TDI → ARM DAP → PL TAP → TDO``; OpenOCD's xilinx_zynqmp.cfg implies
    # the DAP is nearest TDO instead, so treat the position as unverified.
    # The PL BSCANE2 USER1..USER4 instructions share the 7-series opcode
    # pattern but in the 12-bit IR land at 0x024, 0x025, 0x026, 0x027.
    IR_TABLE_XILINX_ZYNQUS: dict[int, int] = {
        1: 0x024, 2: 0x025, 3: 0x026, 4: 0x027,
    }
    # Alias so callers can write IR_TABLE_US for brevity.
    IR_TABLE_US = IR_TABLE_XILINX_ULTRASCALE

    USER1_IR = 0x02
    USER2_IR = 0x03
    DR_BITS = 49
    BURST_DR_BITS = 256
    ADDR_BURST_PTR = 0x002C
    READ_IDLE_CYCLES = 20
    # `fpga -file` on a large device is minutes, not seconds.
    PROGRAM_TIMEOUT_SEC = 600.0
    RAW_DR_IDLE_CYCLES = 8
    USER1_PIPE_PRIME_READS = 3
    _SENTINEL = "<<XSDB_DONE>>"
    # Prefix that ``_send(check=True)`` prints when the command raised in Tcl.
    _ERR_MARKER = "<<XSDB_ERR>>"

    # Default chain shape: single-device 6-bit IR (Xilinx 7-series, standalone
    # UltraScale / UltraScale+).  Override per-instance for chains with extra
    # TAPs in series — e.g. Zynq UltraScale+ MPSoC, where the PL TAP shares
    # the boundary scan chain with the ARM DAP and every IR/DR scan must
    # account for the DAP's IR length and BYPASS bit.  The values stored
    # in ``ir_table`` are shifted **as-is** for ``ir_length`` bits, so the
    # caller is responsible for OR-ing in any other-TAP BYPASS opcodes
    # (typically all-ones in the appropriate bit positions).
    DEFAULT_IR_LENGTH = 6
    DEFAULT_DR_EXTRA_BITS = 0
    DEFAULT_DR_EXTRA_POSITION = "tdo"

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 3121,
        fpga_name: str = "xc7a100t",
        xsdb_path: str | None = None,
        bitfile: str | None = None,
        ir_table: dict[int, int] | None = None,
        ready_probe_addr: int | None = 0x0000,
        ready_probe_timeout: float = 2.0,
        read_timeout_sec: float | None = None,
        *,
        post_program_delay_ms: int = 200,
        ready_poll_interval_sec: float = 0.02,
        target_wait_timeout: float = 10.0,
        ir_length: int = DEFAULT_IR_LENGTH,
        dr_extra_bits: int = DEFAULT_DR_EXTRA_BITS,
        dr_extra_position: str = DEFAULT_DR_EXTRA_POSITION,
        use_register_ir: bool = False,
        single_chain_burst: bool = True,
        burst: bool = True,
    ):
        """``burst=False`` declares a bitstream with no burst path at all
        (``SINGLE_CHAIN_BURST=0`` and ``BURST_EN=0``): every capture is then
        read through the register window.  With ``burst=True`` a burst that
        fails is raised, never read around, so a build without the burst
        path the transport expects must be declared here."""
        if not _TCL_NAME_RE.match(fpga_name):
            raise ValueError(
                f"fpga_name contains unsafe characters for TCL: {fpga_name!r}"
            )
        if bitfile and not _TCL_PATH_RE.match(bitfile):
            raise ValueError(
                f"bitfile path contains unsafe characters for TCL: {bitfile!r}"
            )
        self.host = host
        self.port = port
        self.fpga_name = fpga_name
        self.bitfile = bitfile
        self._xsdb_path = xsdb_path
        self.ir_table = dict(ir_table) if ir_table else dict(self.DEFAULT_IR_TABLE)
        self.ready_probe_addr = ready_probe_addr
        self.ready_probe_timeout = ready_probe_timeout
        self.post_program_delay_ms = int(max(0, min(30_000, post_program_delay_ms)))
        self.ready_poll_interval_sec = float(
            max(0.005, min(0.5, ready_poll_interval_sec))
        )
        # How long connect() waits for hw_server to finish releasing its
        # cables and for a JTAG target matching ``fpga_name`` to appear before
        # giving up.  It must outlast a full release and rescan: when the
        # previous xsdb client exits, hw_server releases every cable and the
        # next client makes it reopen and rescan them all, which took up to
        # 6.2 s on a host with three boards.  It is a deadline, not a delay: a
        # live target is selected in milliseconds.
        self.target_wait_timeout = float(max(0.0, min(30.0, target_wait_timeout)))
        self._active_chain: int = 1
        self._proc: subprocess.Popen | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_lines: list[str] = []
        self._xsdb_io_lock = threading.Lock()
        # Every response is read from this queue, filled by a reader thread,
        # never straight from the pipe. A blocking readline() on a live
        # process that has stopped answering returns *never*, which wedges
        # whatever thread is driving the transport -- for the MCP server that
        # is the single hardware owner, and losing it kills the session for
        # the life of the process. A queue read has a deadline.
        self._stdout_lines: queue.Queue[str | None] = queue.Queue()
        self._stdout_thread: threading.Thread | None = None
        self._poisoned = False
        if read_timeout_sec is None:
            read_timeout_sec = float(os.environ.get("FCAPZ_XSDB_TIMEOUT", "60"))
        self.read_timeout_sec = float(read_timeout_sec)
        # Chain-shape parameters.  All TCL emission and bit-string parsing
        # use these — never the literal 6 / 49 / 256 — so a Zynq US+ MPSoC
        # session (ir_length=16, dr_extra_bits=1) and a 7-series session
        # (ir_length=6, dr_extra_bits=0) share one code path.
        if ir_length < 1 or ir_length > 64:
            raise ValueError(f"ir_length must be 1..64, got {ir_length}")
        if dr_extra_bits < 0 or dr_extra_bits > 32:
            raise ValueError(f"dr_extra_bits must be 0..32, got {dr_extra_bits}")
        if dr_extra_position not in ("tdo", "tdi"):
            raise ValueError(
                f"dr_extra_position must be 'tdo' or 'tdi', got {dr_extra_position!r}"
            )
        self.use_register_ir = bool(use_register_ir)
        self.single_chain_burst = bool(single_chain_burst)
        self.burst = bool(burst)
        if self.use_register_ir:
            # In -register mode xsdb handles both IR routing and DR BYPASS
            # padding for multi-TAP chains (e.g. Zynq US+ MPSoC ARM DAP).
            # Override chain-shape params to avoid double-padding.
            ir_length = 6
            dr_extra_bits = 0
        self.ir_length = int(ir_length)
        self.dr_extra_bits = int(dr_extra_bits)
        self.dr_extra_position = dr_extra_position
        self._ir_hex_digits = (self.ir_length + 3) // 4

    # -- lifecycle -----------------------------------------------------------

    def connect(self) -> None:
        self._forget_hub_state()
        timing = connect_timing_logs_enabled()
        marks: list[tuple[str, float]] = [("start", time.monotonic())]

        def mark(label: str) -> None:
            marks.append((label, time.monotonic()))

        xsdb = self._xsdb_path or shutil.which("xsdb") or shutil.which("xsdb.bat")
        if not xsdb:
            raise RuntimeError(
                "xsdb not found. Add Vivado bin to PATH or pass xsdb_path=."
            )

        self._proc = subprocess.Popen(
            [xsdb],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._poisoned = False
        self._stdout_lines = queue.Queue()
        self._stderr_lines = []
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True
        )
        self._stderr_thread.start()
        self._stdout_thread = threading.Thread(
            target=self._drain_stdout, daemon=True
        )
        self._stdout_thread.start()
        mark("xsdb_spawned")

        self._send(f"connect -url tcp:{self.host}:{self.port}")
        # Widen hw_server's BSCAN switch mask so USER2-USER4 irshifts
        # reach the right BSCANE2 instead of collapsing onto USER1.
        # Defaults to 0x1 (USER1 only) on Zynq US+ MPSoC.
        self._send("configparams bscan-switch-user-mask 0xF")
        self._send("configparams xsdb-user-bscan 1,2,3,4")
        mark("hw_server_tcp")

        if self.bitfile:
            # Programming over a cable hw_server is still reopening fails the
            # same way a scan does, so wait for a live target first.
            self._select_fpga_target()
            _hw_log.info(
                "Programming FPGA from bitfile (fpga -file): %s",
                self.bitfile,
            )
            self.program(self.bitfile)
            mark("fpga_file_done")
        else:
            _hw_log.info(
                "Skipping fpga -file — using the configuration already in the FPGA. "
                "Uncheck 'Program on connect' or clear the bitfile path in Connection "
                "when you do not want to reprogram.",
            )
            mark("fpga_skipped")

        self._select_fpga_target()
        mark("jtag_target_set")

        # Wait for the JTAG chain to respond with valid (non-zero) data on
        # the configured probe register.  After fpga -file the bitstream is
        # uploaded but the FPGA's startup sequence (DONE assertion, BSCAN
        # bring-up, internal config logic settling) can run a few hundred
        # ms longer.  Reading too early returns all-zero scans.  Polling
        # here pushes the entire "is the chain alive yet?" concern into the
        # transport, so callers can rely on connect() returning a working
        # session.  Pass ready_probe_addr=None to skip (e.g. when the
        # bitstream cannot guarantee a non-zero response at any address).
        if self.ready_probe_addr is not None and self.bitfile:
            _hw_log.info(
                "Waiting for FPGA ready (probe register 0x%04X, timeout %.1fs)",
                self.ready_probe_addr,
                self.ready_probe_timeout,
            )
            attempts = self._wait_until_ready()
            mark("fpga_ready")
            _hw_log.info("FPGA ready probe succeeded.")
            if timing:
                _hw_log.info(
                    "hw_server connect: ready_poll attempts=%d (see fpga_ready delta)",
                    attempts,
                )
        else:
            mark("ready_skipped")

        mark("connect_done")
        if timing and len(marks) >= 2:
            parts = []
            for i in range(1, len(marks)):
                label, t = marks[i]
                dt = t - marks[i - 1][1]
                parts.append(f"{label}={dt:.3f}s")
            total = marks[-1][1] - marks[0][1]
            _hw_log.info(
                "hw_server connect timing (FCAPZ_LOG_CONNECT_TIMING): %s | total=%.3fs",
                " ".join(parts),
                total,
            )

    def _wait_until_ready(self) -> int:
        """Poll the configured probe register until it returns non-zero.

        Raises ConnectionError if the deadline elapses.  Uses the chain
        currently active (default chain 1 / USER1).

        Returns:
            Number of probe read attempts (including the successful one).
        """
        deadline = time.monotonic() + self.ready_probe_timeout
        attempts = 0
        last_value = 0
        while time.monotonic() < deadline:
            try:
                last_value = self.read_reg(self.ready_probe_addr)
            except Exception:
                last_value = 0
            attempts += 1
            if last_value != 0:
                return attempts
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(self.ready_poll_interval_sec, remaining))
        raise ConnectionError(
            f"FPGA did not become ready within {self.ready_probe_timeout}s "
            f"after program() (probe addr=0x{self.ready_probe_addr:04X}, "
            f"last_value=0x{last_value:08X}, attempts={attempts}). "
            "Either the bitstream failed to load, the wrong fpga_name was "
            "selected, or the probe register address is wrong for this design."
        )

    # One IDCODE scan: harmless on any device (it never selects a USER chain)
    # and named by register so xsdb picks each device's own IR code.
    _NODE_CHECK_TCL = (
        "set _nc [jtag sequence]; "
        "$_nc irshift -state IRUPDATE -register idcode; "
        "$_nc drshift -state DRUPDATE -capture -tdi 0 32; "
        "$_nc run; $_nc delete"
    )

    # Prints the name of every cable hw_server reports as closed or still
    # initializing, one per line.  A cable in an error state is left out:
    # that lasts, and is not part of a release.
    _CLOSED_CABLES_TCL = (
        "foreach _t [jtag targets -target-properties] { "
        "set _s [dict get $_t state]; "
        "if {[dict get $_t level] == 0 && ![string match error* $_s] && "
        "(![dict get $_t is_open] || [string match initializing* $_s])} "
        "{ puts [dict get $_t name] } }"
    )

    def _select_fpga_target(self) -> None:
        """Select the JTAG target matching ``fpga_name`` once it answers a scan.

        When the last xsdb client exits, hw_server releases its cables
        ``jtag-poll-close-delay`` (1 s) later, closing them one after another;
        with a client connected again it reopens and rescans them all.  A
        client that arrives once the release has begun does not stop it: it
        sees some cables closed and the rest still open, and the open ones
        close a moment later.  A target on a still-open cable answers a scan
        and then drops out for the whole reopen (about 3 s).

        So first wait for any release to finish: while a client is connected,
        hw_server never starts one, so a cable it reports closed means a
        release is under way, and every cable open and initialized means it
        is over.  A cable reporting an error (a board powered off, say) is
        not part of a release and is not waited for.  Then poll ``jtag
        targets`` until a matching device appears (a board still powering
        up, say), select it, and confirm it with an IDCODE scan.  Both waits
        are polled until ``target_wait_timeout``; a select or scan that
        fails is raised at once.

        One window is left, and only hw_server could close it.  For about
        0.2 s after it decides to close a cable, hw_server still reports
        that cable open, and it has no closing state to wait on.  A connect
        that lands right at a release's start can pass the cable wait and
        select, then see the target drop out for about 1 s: the IDCODE scan
        here fails, or this returns and the reads just after it fail.
        Either way the error is raised; no wrong data is returned.

        The deadline bounds this polling, not a single xsdb command: like
        every command on this transport, one that never answers is waited
        for.
        """
        deadline = time.monotonic() + self.target_wait_timeout
        self._wait_for_cable_release(deadline)
        while True:
            # ``puts`` forces the list onto stdout — the bare command doesn't
            # echo its result through a piped (non-interactive) xsdb session.
            names = parse_xsdb_jtag_targets(self._send("puts [jtag targets]"))
            if any(self.fpga_name in name for name in names):
                # ``-timeout 0``: with ``-filter`` xsdb otherwise polls up to
                # 3 s for a match, which would wait out a target that just
                # left the list instead of failing.
                self._send(
                    "jtag targets -set -timeout 0 "
                    f'-filter {{name =~ "{self.fpga_name}"}}',
                    check=True,
                )
                self._send(self._NODE_CHECK_TCL, check=True)
                return
            if time.monotonic() >= deadline:
                visible = ", ".join(names) if names else "(none)"
                raise ConnectionError(
                    f"no JTAG target matching {self.fpga_name!r} appeared within "
                    f"{self.target_wait_timeout:.1f}s (visible: {visible}). The "
                    "board may be unplugged or powered off."
                )
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    def _wait_for_cable_release(self, deadline: float) -> None:
        """Wait until hw_server reports every cable open and initialized.

        A cable reporting an error is left out: that state lasts, and the
        target wait that follows names a board that is missing.

        While a client is connected hw_server reopens a closed cable within a
        few seconds, so a release ends well inside ``target_wait_timeout``.
        A cable still closed at the deadline means the release has not
        ended, and selecting a target then could hand back one that is about
        to drop out, so it is an error.
        """
        while True:
            closed = [
                line.strip()
                for line in self._send(self._CLOSED_CABLES_TCL, check=True).splitlines()
                if line.strip()
            ]
            if not closed:
                return
            if time.monotonic() >= deadline:
                raise ConnectionError(
                    f"hw_server still reports JTAG cable(s) closed or initializing "
                    f"after {self.target_wait_timeout:.1f}s: {', '.join(closed)}. "
                    "It reopens its cables within a few seconds while a client "
                    "is connected; check that no other program holds the cable "
                    "and that hw_server's auto-open-ports is on."
                )
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    def _select_config_target(self) -> None:
        """Select the debug target that ``fpga -file`` configures.

        This is a *different* namespace from ``_select_fpga_target``.  That one
        picks a device in the JTAG scan chain (``jtag targets``), where the
        part name is the node name.  ``fpga`` works on the debug-target tree
        (``targets``), and the two only coincide on standalone FPGAs:

          * 7-series / UltraScale(+): ``targets`` has one node per device,
            named for the part (``xc7a100t``) — the part name works.
          * Zynq UltraScale+ MPSoC (Kria xck24/xck26, ZCU+ xczu*): ``targets``
            has no node named for the part at all.  The tree is
            ``PS TAP`` -> ``PMU``/``PL``, plus ``PSU`` -> ``RPU``/``APU``, and
            configuration is done from ``PS TAP``.  Filtering on the part name
            selects **nothing**, and ``fpga -file`` then programs nothing.
            (``PL`` is not it either: xsdb answers "Multiple FPGA devices
            found, please use targets command to select one of ..." — verified
            on xck26 / KV260 with xsdb 2025.2.)

        Both filters are scoped by ``jtag_device_name`` so the right board is
        picked when several are attached — two MPSoC boards both contribute a
        node named ``PS TAP``, and the part name is the only thing that tells
        them apart.
        """
        attempts = (
            # MPSoC/Versal: configuration hangs off the PS TAP node.
            f'{{jtag_device_name =~ "{self.fpga_name}" && name =~ "PS TAP"}}',
            # Standalone FPGA: the device node is named for the part.
            f'{{jtag_device_name =~ "{self.fpga_name}" && name =~ "{self.fpga_name}"}}',
        )
        errors: list[str] = []
        for flt in attempts:
            try:
                self._send(f"targets -set -filter {flt}", check=True)
                return
            except RuntimeError as exc:
                errors.append(str(exc))
        detail = " | ".join(errors)
        raise ConnectionError(
            f"no configuration target for {self.fpga_name!r} -- nothing "
            f"would be programmed. Tried {attempts[0]} then {attempts[1]}. "
            f"xsdb said: {detail}"
        )

    def program(self, bitfile: str) -> None:
        """Program the FPGA with *bitfile* using the current XSDB session."""
        if not _TCL_PATH_RE.match(bitfile):
            raise ValueError(
                f"bitfile path contains unsafe characters for TCL: {bitfile!r}"
            )
        self._select_config_target()
        # check=True: a failed load prints a message and returns normally, so
        # without it a bad/incompatible bitstream looks like a success and the
        # session runs on against the old configuration.
        # A large bitstream takes far longer than a register read, so this
        # one call gets its own budget rather than forcing the interactive
        # default up for everything.
        self._send(
            f"fpga -file {{{bitfile}}}",
            check=True,
            timeout_sec=max(self.read_timeout_sec, self.PROGRAM_TIMEOUT_SEC),
        )
        self._send(f"after {int(self.post_program_delay_ms)}")
        # A new bitstream: which chains hold a manager, and what this
        # session claimed, are no longer known.
        self._forget_hub_state()

    def close(self) -> None:
        if self._proc and self._proc.stdin:
            self._release_ownership_on_close()
            try:
                self._proc.stdin.write("exit\n")
                self._proc.stdin.flush()
            except OSError:
                pass
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        # Release anyone waiting on a response the dead process will never
        # send. Without this a concurrent _send sits out its whole budget
        # before noticing, which is the delay cancelling was meant to avoid.
        self._stdout_lines.put(None)

    def close_fast(self) -> None:
        """Kill ``xsdb`` quickly for console interrupt; normal :meth:`close` may wait 5s."""
        proc = self._proc
        if proc is None:
            self._stdout_lines.put(None)
            return
        try:
            if proc.stdin is not None:
                try:
                    proc.stdin.write("exit\n")
                    proc.stdin.flush()
                except OSError:
                    pass
        except (OSError, ValueError):
            pass
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            pass
        self._proc = None
        self._stdout_lines.put(None)

    def cancel(self) -> None:
        # Called from another thread while a _send may be waiting. Killing
        # the process is what makes that wait end early; the sentinel below
        # is what makes it end immediately.  Never touches stdin: a _send
        # blocked writing a large command to an xsdb that stopped reading
        # holds the pipe's buffer lock, and an "exit" write would wait on it.
        # Leaves _proc for the owner: its _send fails on the dead pipe and
        # its close() reaps the process.
        self._poisoned = True
        proc = self._proc
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass
        self._stdout_lines.put(None)

    # -- chain selection -----------------------------------------------------

    def select_chain(self, chain: int) -> None:
        """Select BSCANE2 USER chain for subsequent register accesses."""
        if self.use_register_ir:
            if not (1 <= chain <= 4):
                raise ValueError(f"chain must be 1..4, got {chain}")
        elif chain not in self.ir_table:
            raise ValueError(f"chain {chain} not in ir_table {self.ir_table}")
        self._active_chain = chain

    def discovery_chains(self) -> tuple[int, ...]:
        if self.use_register_ir:
            return (1, 2, 3, 4)
        return tuple(sorted(self.ir_table))

    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        """Perform a raw DR scan via XSDB jtag sequence (irscan + drscan)."""
        ch = chain if chain is not None else self._active_chain
        bit_str = "".join("1" if (bits >> i) & 1 else "0" for i in range(width))
        padded = self._pad_dr(bit_str)
        total = self._user_dr_bits(width)
        tcl = (
            f"set _rd [jtag sequence]; "
            f"{self._irshift_tcl('_rd', ch)}; "
            f"$_rd drshift -state DRUPDATE -capture -bits {total} {padded}; "
            f"$_rd state IDLE {self.RAW_DR_IDLE_CYCLES}; "
            f"puts [$_rd run -bits]; $_rd delete"
        )
        out = self._send(tcl)
        return self._parse_scan_bits(out, width, total)

    def raw_dr_scan_batch(
        self, scans: list[tuple[int, int]], *, chain: int | None = None
    ) -> list[int]:
        """Perform multiple raw DR scans in one XSDB jtag sequence."""
        if not scans:
            return []
        ch = chain if chain is not None else self._active_chain
        parts = ["set _rdb [jtag sequence]"]
        totals: list[int] = []
        widths: list[int] = []
        for bits, width in scans:
            bit_str = "".join("1" if (bits >> i) & 1 else "0" for i in range(width))
            padded = self._pad_dr(bit_str)
            total = self._user_dr_bits(width)
            parts.append(
                f"{self._irshift_tcl('_rdb', ch)}; "
                f"$_rdb drshift -state DRUPDATE -capture -bits {total} {padded}; "
                f"$_rdb state IDLE {self.RAW_DR_IDLE_CYCLES}"
            )
            totals.append(total)
            widths.append(width)
        parts.append("puts [$_rdb run -bits]; $_rdb delete")
        out = self._send("; ".join(parts))
        return self._parse_scan_bits_list(out, widths, totals)

    # -- register access -----------------------------------------------------

    def read_reg(self, addr: int) -> int:
        frame = self._frame_bits(addr=addr, data=0, write=False)
        tcl = self._read_reg_tcl(frame, addr=addr)
        raw = self._send(tcl)
        return self._parse_bits_u32(raw)

    def write_reg(self, addr: int, value: int) -> None:
        frame = self._frame_bits(addr=addr, data=value, write=True)
        tcl = self._write_reg_tcl(frame, addr=addr)
        self._send(tcl)

    _BLOCK_CHUNK = 512  # max reads per single jtag sequence

    def read_block(self, addr: int, words: int) -> List[int]:
        """Read *words* consecutive 32-bit registers starting at *addr*.

        If *addr* is the DATA window base (0x0100) and burst mode is
        available, uses the wide burst DR for ~10x faster throughput.
        Otherwise falls back to single-sequence pipelined reads on the
        active ELA control chain.

        The burst DR packs whole ``SAMPLE_W``-bit samples per 256-bit scan, but
        *words* counts 32-bit words, so this burst is only used when a sample
        fits one word (``SAMPLE_W <= 32``); a wider core here takes the 32-bit
        word path.  ``Analyzer.capture()`` reads a wide core with
        :meth:`read_sample_block`, which bursts whole samples, and comes here
        only when that raises :class:`BurstUnavailableError`.
        """
        if words <= 0:
            return []
        if addr == 0x0100 and self.bursts_data_window():
            return self._burst_with_hint(words)
        # Non-burst path needs flush to reset the 49-bit register pipeline.
        return self._read_block_user1(addr, words)

    def read_window_block(self, addr: int, words: int) -> List[int]:
        if words <= 0:
            return []
        return self._read_block_user1(addr, words)

    def bursts_data_window(self, *, timestamp: bool = False) -> bool:
        if timestamp:
            return self._burst_available
        return self._burst_available and self._burst_sample_ok()

    @property
    def _burst_available(self) -> bool:
        """True if the bitstream has a fast burst interface.

        Declared by the ``burst`` constructor argument, never probed: a
        BURST_PTR write is a side-effecting start toggle for the burst
        engine, and a failed burst is a defect to raise, not a sign that
        the build has none.
        """
        return self.burst

    def _burst_sample_ok(self) -> bool:
        """True when the selected core's ``SAMPLE_W`` fits the burst DR model.

        The burst engine returns whole samples; ``capture()`` only treats them
        as such for ``SAMPLE_W <= 32`` (one 32-bit word per sample). Read fresh
        (not cached) so a session that hops between an 8-bit ELA and a 160-bit
        AXI monitor always gates on the *currently selected* core.
        """
        sw = int(self.read_reg_stable(0x000C))  # ADDR_SAMPLE_W
        return sw < 1 or sw <= 32

    @property
    def burst_on_data_chain(self) -> bool:  # type: ignore[override]
        """A two-chain session (``single_chain_burst=False``) bursts on USER2,
        which a core manager never answers."""
        return not self.single_chain_burst

    def _burst_sample_width(self) -> int:
        """Bits per sample in a burst scan: the selected core's SAMPLE_W, read
        for every burst so a slot switch cannot leave a stale width."""
        return _burst_element_width(self.read_reg_stable(0x000C), self.BURST_DR_BITS)

    def _read_block_burst(
        self,
        words: int,
        *,
        timestamp: bool = False,
        element_width: int | None = None,
        on_control_chain: bool = False,
        run_lengths: bool = False,
    ) -> List[int]:
        """Read *words* samples via the 256-bit burst DR.

        The scans go on the control chain on a single-chain session or with
        *on_control_chain* (a core manager), otherwise on USER2.
        ``timestamp`` reads the timestamp lane instead; with ``run_lengths``
        too it carries the run counts of a run-length capture.

        The BURST_PTR write, the staging-fill idle and every 256-bit DR scan
        are ONE ``jtag sequence``, run once.  Nothing else can reach the chain
        from the write to the last scan: between two runs hw_server can put
        a scan of its own through the PL with the USER chain still selected,
        and on a single-chain build jtag_pipe_iface decodes its last 49 bits
        as a register command, which ends burst mode.  Seen on Zynq US+ MPSoC
        (``-register`` mode): the scan after the gap returns the register
        read data instead of samples.  A deep burst is too long for one TCL
        line, so the sequence object is built over several xsdb sends and only
        the last one runs it.
        """
        if timestamp and element_width is None:
            element_width = 32
        if element_width is None:
            element_width = self._burst_sample_width()
        sps = max(1, self.BURST_DR_BITS // element_width)
        n_scans = (words + sps - 1) // sps
        prime_scans = 1

        dr_bits = self.BURST_DR_BITS
        burst_total = self._user_dr_bits(dr_bits)
        burst_zeros = self._pad_dr("0" * dr_bits)

        burst_frame = self._pad_dr(
            self._frame_bits(
                addr=self.ADDR_BURST_PTR,
                data=(0x80000000 if timestamp else 0)
                | (0x40000000 if timestamp and run_lengths else 0),
                write=True,
            )
        )
        user_total = self._user_dr_bits(self.DR_BITS)
        ctrl_chain = self._active_chain
        ir1_cmd = self._irshift_tcl("_bq", chain=ctrl_chain)
        burst_chain = (
            ctrl_chain if (self.single_chain_burst or on_control_chain) else 2
        )
        ir_burst_cmd = self._irshift_tcl("_bq", chain=burst_chain)

        # The BURST_PTR write ends in an explicit UPDATE-DR, like every
        # command scan, then idle TCKs so the update crosses into the burst
        # reader (TCK-clocked) and the first 256-bit staging word fills before
        # the first burst CAPTURE samples it.  Register mode also needs the
        # longer register-write settle.
        write_idle = self.BURST_PREFILL_IDLE_CYCLES
        if self.use_register_ir:
            write_idle = max(self.WRITE_IDLE_CYCLES_REGISTER, write_idle)
        write_ptr = [
            f"{ir1_cmd}; "
            f"$_bq drshift -state DRUPDATE -bits {user_total} {burst_frame}",
            f"$_bq state IDLE {write_idle}",
        ]
        # Select the slot before BURST_PTR, which makes it the burst owner;
        # never between burst scans, where any command scan ends burst mode.
        head = [
            "set _bq [jtag sequence]",
            *self._slot_select_tcl("_bq", [self.ADDR_BURST_PTR]),
            *write_ptr,
        ]
        if self.burst_start_sync:
            # See Transport.burst_start_sync: one burst scan whose capture
            # matches the engine's copy to the new owner's start toggle, then
            # a second BURST_PTR write the engine cannot miss.  The TAP
            # passes Capture-DR either way; without ``-capture`` xsdb just
            # does not print the scan, so the burst output is unchanged.
            head += [
                f"{ir_burst_cmd}; $_bq drshift -state DRUPDATE "
                f"-bits {burst_total} {burst_zeros}",
                *write_ptr,
            ]
        tail: list[str] = []
        if burst_chain == ctrl_chain:
            # Leave the pipe idle.  Until a command scan ends burst mode, every
            # capture on the chain starts another staging fill, and the core
            # manager ignores an MGR_ACTIVE write while one runs.  On a narrow
            # lane (1-4 bits) a fill outlasts the next 49-bit select scan, so
            # without this a slot switch right after the burst was dropped and
            # the next access reached the previous slot.  The VERSION read is
            # not captured, so the output is unchanged.
            neutral = self._pad_dr(self._frame_bits(addr=0x0000, data=0, write=False))
            tail = [
                f"{ir1_cmd}; $_bq drshift -state DRUPDATE -bits {user_total} {neutral}",
                f"$_bq state IDLE {self.BURST_DRAIN_IDLE_CYCLES}",
            ]
        # The first wide scan primes/fills staging and is discarded.
        tcls = self._burst_sequence_sends(
            head, ir_burst_cmd, burst_total, burst_zeros, n_scans + prime_scans, tail
        )

        # Every send is checked: a failure while the sequence is being built
        # prints only into that send's output, and the last send would then
        # run a partial sequence whose scans parse as a short burst.
        out = ""
        for tcl in tcls:
            out = self._send(tcl, check=True)  # only the last send prints the scans
        return self._parse_burst_bits(
            out,
            words,
            skip_scans=prime_scans,
            element_width=element_width,
            expected_scans=n_scans + prime_scans,
            header_timestamp=timestamp if burst_chain == ctrl_chain else None,
        )

    # Wide scans per xsdb send.  A deep wide-sample burst is thousands of
    # 256-bit scans; as one TCL line that hung xsdb, so the scans are added to
    # the sequence object over several sends.  They still run as one sequence.
    _BURST_SCANS_PER_SEQUENCE = 256

    def _burst_sequence_sends(
        self,
        head: list[str],
        ir_cmd: str,
        total_bits: int,
        zeros: str,
        n_scans: int,
        tail: list[str] | None = None,
    ) -> list[str]:
        """TCL sends that build ONE ``_bq`` sequence -- *head*, *n_scans*
        burst DR scans (at most ``_BURST_SCANS_PER_SEQUENCE`` per send), then
        *tail* -- and run it in the last send, printing every captured scan."""
        scan = f"{ir_cmd}; $_bq drshift -state DRUPDATE -capture -bits {total_bits} {zeros}"
        sends: list[list[str]] = []
        for start in range(0, n_scans, self._BURST_SCANS_PER_SEQUENCE):
            count = min(self._BURST_SCANS_PER_SEQUENCE, n_scans - start)
            sends.append([scan] * count)
        sends[0] = head + sends[0]
        sends[-1] = sends[-1] + list(tail or ()) + ["puts [$_bq run -bits]; $_bq delete"]
        return ["; ".join(s) for s in sends]

    def read_sample_block(
        self, base_addr: int, n_samples: int, sample_width: int,
        *, on_control_chain: bool = False,
    ) -> List[int]:
        """Read *n_samples* whole samples via the burst DR.

        With *on_control_chain* the scans stay on the control chain even on a
        two-chain session: a core manager answers bursts only there.

        Returns ``ceil(sample_width / 32)`` little-endian 32-bit words per
        sample, the flat layout ``Analyzer.capture()`` reassembles.  This is the
        readout for wide cores (``SAMPLE_W > 32``): the burst engine addresses
        the capture RAM by sample, so unlike the 16-bit register window it has
        no size limit, and one 256-bit scan replaces ``ceil(width / 32)``
        register reads.  Raises :class:`BurstUnavailableError`, before any
        scan, when this transport cannot burst the request, so the caller can
        read the window instead.  A burst that runs and fails raises anything
        else -- :class:`BurstIntegrityError` for the wrong number of samples --
        and must not be read around.
        """
        if n_samples <= 0:
            return []
        if base_addr != 0x0100:
            raise BurstUnavailableError(
                f"sample burst needs the DATA base, got 0x{base_addr:04X}"
            )
        if not 1 <= sample_width <= self.BURST_DR_BITS:
            raise BurstUnavailableError(
                f"sample width {sample_width} does not fit the "
                f"{self.BURST_DR_BITS}-bit burst DR"
            )
        if not self._burst_available:
            raise BurstUnavailableError("burst readout is off for this transport")
        samples = self._burst_with_hint(
            n_samples, element_width=sample_width, on_control_chain=on_control_chain
        )
        if len(samples) != n_samples:
            raise BurstIntegrityError(
                f"sample burst returned {len(samples)} samples, expected {n_samples}"
            )
        words_per_sample = (sample_width + 31) // 32
        words: List[int] = []
        for sample in samples:
            for w in range(words_per_sample):
                words.append((sample >> (w * 32)) & 0xFFFFFFFF)
        return words

    def read_timestamp_block_single_chain(
        self, base_addr: int, n_timestamps: int, timestamp_width: int,
        *, on_control_chain: bool = False,
    ) -> List[int]:
        """Read one timestamp per captured sample via the burst DR.

        The wide-core counterpart of :meth:`read_sample_block`: a deep wide
        capture's timestamp window can start past the 16-bit register space,
        so it must not be read through the window.  Raises
        :class:`BurstUnavailableError` when burst readout is off, and
        :class:`BurstIntegrityError` when a burst ran but returned the wrong
        number of timestamps.
        """
        if n_timestamps <= 0:
            return []
        if not self._burst_available:
            raise BurstUnavailableError("burst readout is off for this transport")
        values = self._burst_with_hint(
            n_timestamps, timestamp=True, element_width=timestamp_width,
            on_control_chain=on_control_chain,
        )
        if len(values) != n_timestamps:
            raise BurstIntegrityError(
                f"timestamp burst returned {len(values)} values, expected {n_timestamps}"
            )
        return values

    def read_run_length_block(
        self, n_entries: int, lane_width: int, *, on_control_chain: bool = False
    ) -> List[int]:
        """Read one run count per captured entry via the burst DR, on the
        control chain with *on_control_chain* (a core manager's slot).

        Counts travel on the timestamp lane, ``lane_width`` bits per element
        (the core's timestamp width, or its RLE_W without timestamps).  Raises
        :class:`BurstUnavailableError`, before any scan, when burst readout is
        off, and :class:`BurstIntegrityError` when a burst ran but returned the
        wrong number of counts.
        """
        if n_entries <= 0:
            return []
        if not self._burst_available:
            raise BurstUnavailableError("burst readout is off for this transport")
        values = self._burst_with_hint(
            n_entries,
            timestamp=True,
            element_width=lane_width,
            run_lengths=True,
            on_control_chain=on_control_chain,
        )
        if len(values) != n_entries:
            raise BurstIntegrityError(
                f"run-length burst returned {len(values)} values, expected {n_entries}"
            )
        return values

    def read_timestamp_block(self, addr: int, words: int, timestamp_width: int) -> List[int]:
        """Read timestamp words through the configured burst mode when available."""
        if words <= 0:
            return []
        if timestamp_width > 0 and self.bursts_data_window(timestamp=True):
            return self._burst_with_hint(
                words,
                timestamp=True,
                element_width=timestamp_width,
            )
        return self._read_block_user1(addr, words)

    def _burst_with_hint(self, words: int, **kwargs) -> List[int]:
        """Run :meth:`_read_block_burst`; a burst that fails is raised with
        the build options that would explain it, never read around."""
        try:
            return self._read_block_burst(words, **kwargs)
        except RuntimeError as exc:
            if type(exc) is not RuntimeError:
                raise  # BurstIntegrityError and other typed errors, unchanged
            if self.single_chain_burst:
                hint = (
                    "If this bitstream was built with SINGLE_CHAIN_BURST=0, pass "
                    "--two-chain-burst (single_chain_burst=False)"
                )
            else:
                hint = (
                    "If this bitstream was built with BURST_EN=0, it has no USER2 "
                    "burst path"
                )
            raise RuntimeError(
                f"burst readback failed: {exc}. {hint}; if it has no burst path at "
                "all, pass --no-burst (burst=False)."
            ) from exc

    def _parse_burst_bits(
        self,
        output: str,
        total_words: int,
        *,
        skip_scans: int = 0,
        element_width: int | None = None,
        expected_scans: int | None = None,
        header_timestamp: bool | None = None,
    ) -> List[int]:
        """Parse burst DR output: each token is a 256-bit string packing
        samples (SAMPLE_W bits each, LSB first).

        With *expected_scans*, any other number of scan tokens raises
        :class:`BurstIntegrityError` rather than returning a short or
        misaligned burst.  With *header_timestamp* (the burst ran on the
        hub's chain), the first skipped scan is checked as the burst header
        (:meth:`_check_burst_header`).
        """
        if element_width is None:
            element_width = self._burst_sample_width()
        sw = element_width
        sps = max(1, self.BURST_DR_BITS // sw)
        values: list[int] = []
        scan_idx = 0
        burst_offset = self._dr_data_offset()
        min_len = burst_offset + self.BURST_DR_BITS
        for token in output.replace("{", " ").replace("}", " ").split():
            token = token.strip()
            if not token or len(token) < min_len:
                continue
            if set(token) - {"0", "1"}:
                continue
            if scan_idx < skip_scans:
                if scan_idx == 0 and header_timestamp is not None:
                    self._check_burst_header(
                        self._bits_to_int(token, burst_offset, self.BURST_DR_BITS),
                        timestamp=header_timestamp,
                    )
                scan_idx += 1
                continue
            scan_idx += 1
            for s in range(sps):
                if len(values) >= total_words:
                    break
                offset = burst_offset + s * sw
                val = self._bits_to_int(token, offset, sw)
                values.append(val)
        if expected_scans is not None and scan_idx != expected_scans:
            raise BurstIntegrityError(
                f"burst returned {scan_idx} scans, expected {expected_scans}"
            )
        if len(values) < total_words:
            raise BurstIntegrityError(
                f"burst returned {len(values)} values, expected {total_words}"
            )
        return values[:total_words]

    def _read_block_user1(self, addr: int, words: int) -> List[int]:
        """Non-burst block read via the 49-bit DR on the active chain.

        DATA/timestamp windows are read-only after capture completion.  Uses one
        pipelined ``jtag sequence`` per ``_BLOCK_CHUNK`` words -- priming
        (``USER1_PIPE_PRIME_READS``) discards the stale register-pipeline word
        and the RTL jtag_rdata fill latency -- rather than a per-word round trip.
        This is the fallback for narrow ELAs when USER2 burst is unavailable and
        the primary readback for wide cores (SAMPLE_W > 32, e.g. the AXI monitor,
        whose 5-word samples do not fit the sample-packing burst DR).  Reading a
        160-bit x depth buffer per-word cost tens of seconds of xsdb round trips;
        the pipelined path is ~25x faster and returns identical data (validated
        on Arty against the per-word path).
        """
        check_data_window(addr, words, self.data_window_end)
        results: list[int] = []
        for start in range(0, words, self._BLOCK_CHUNK):
            end = min(start + self._BLOCK_CHUNK, words)
            chunk_size = end - start
            tcl = self._burst_read_tcl(addr, start, chunk_size)
            out = self._send(tcl)
            results.extend(
                self._parse_block_bits(
                    out,
                    chunk_size,
                    skip_words=self.USER1_PIPE_PRIME_READS,
                )
            )
        # Flush JTAG pipeline
        self.read_reg(0x0000)
        return results

    def _burst_read_tcl(self, base_addr: int, offset: int, count: int) -> str:
        """Generate TCL for burst block read using a single jtag sequence.

        All scans go into one sequence object: one address setup,
        USER1_PIPE_PRIME_READS discarded priming captures, then N returned
        captures.  Each address-bearing scan ends in an explicit UPDATE-DR
        and a short idle follows it before the next capture, so the
        fabric-domain read request can cross, read RAM, and resynchronize
        before CAPTURE samples jtag_rdata.
        """
        n = self._user_dr_bits(self.DR_BITS)
        idle = self.READ_IDLE_CYCLES
        # Target the ACTIVE chain, not a hardcoded USER1: the DATA window of a
        # core on another chain (e.g. the AXI monitor on USER2) must be read on
        # that chain, or this returns USER1's data instead.
        ir_cmd = self._irshift_tcl("_q", chain=self._active_chain)
        frames: list[str] = []
        for i in range(count):
            frames.append(
                self._pad_dr(
                    self._frame_bits(addr=base_addr + (offset + i) * 4, data=0, write=False)
                )
            )
        flush_frame = self._pad_dr(self._frame_bits(addr=0x0000, data=0, write=False))

        parts: list[str] = [
            "set _q [jtag sequence]",
            *self._slot_select_tcl(
                "_q", [base_addr + (offset + i) * 4 for i in range(count)]
            ),
            # Scan 0: set first address, no capture
            f"{ir_cmd}; "
            f"$_q drshift -state DRUPDATE -bits {n} {frames[0]}",
            f"$_q state IDLE {idle}",
        ]
        # Prime captures: discard the stale register-pipeline word plus the
        # RTL jtag_rdata fill latency before counting returned words. If the
        # RTL adds another registered readback stage, this constant must grow
        # with that latency.
        for _ in range(self.USER1_PIPE_PRIME_READS):
            parts.append(
                f"{ir_cmd}; "
                f"$_q drshift -state DRUPDATE -capture -bits {n} {frames[0]}"
            )
            parts.append(f"$_q state IDLE {idle}")
        # Scans 1..N-1: capture previous AND set next address.
        for i in range(1, count):
            parts.append(
                f"{ir_cmd}; "
                f"$_q drshift -state DRUPDATE -capture -bits {n} {frames[i]}"
            )
            parts.append(f"$_q state IDLE {idle}")
        # Final scan: capture last result
        parts.append(
            f"{ir_cmd}; "
            f"$_q drshift -state DRUPDATE -capture -bits {n} {flush_frame}"
        )
        parts.append("puts [$_q run -bits]; $_q delete")
        return "; ".join(parts)

    def read_regs_pipelined_user1(self, addrs: List[int]) -> List[int]:
        """Read several CSR addresses in one ``jtag sequence`` / :meth:`_send` round-trip.

        Uses the same USER1 pipelined capture pattern as :meth:`_burst_read_tcl`
        (IR+DR per step; capture carries the previous address's data).  A final
        :meth:`read_reg` to VERSION flushes the JTAG pipeline for later accesses.
        """
        return self._pipelined_reads(addrs, self._slot_select_tcl("_pq", addrs))

    def read_regs_after_write(
        self, write_addr: int, value: int, addrs: List[int]
    ) -> List[int]:
        """The write and the reads run as one ``jtag sequence``."""
        # One unit with the chain and slot read once: hold off any other
        # thread's scope, as the base implementation does.
        with self.transaction_lock():
            if not addrs:
                self.write_reg(write_addr, value)
                return []
            n = self._user_dr_bits(self.DR_BITS)
            frame = self._pad_dr(self._frame_bits(addr=write_addr, data=value, write=True))
            head = [
                *self._slot_select_tcl("_pq", [write_addr, *addrs]),
                f"{self._irshift_tcl('_pq')}; $_pq drshift -state DRUPDATE -bits {n} {frame}",
                f"$_pq state IDLE {self._write_idle_cycles}",
            ]
            return self._pipelined_reads(addrs, head)

    def _pipelined_reads(self, addrs: List[int], head: List[str]) -> List[int]:
        """Pipelined reads of *addrs* in one sequence, after the scans in *head*."""
        if not addrs:
            return []
        n = self._user_dr_bits(self.DR_BITS)
        idle = self.READ_IDLE_CYCLES
        ir_cmd = self._irshift_tcl("_pq")
        frames = [
            self._pad_dr(self._frame_bits(addr=a, data=0, write=False))
            for a in addrs
        ]
        count = len(frames)
        parts: list[str] = [
            "set _pq [jtag sequence]",
            *head,
            f"{ir_cmd}; "
            f"$_pq drshift -state DRUPDATE -bits {n} {frames[0]}",
            f"$_pq state IDLE {idle}",
        ]
        for i in range(1, count):
            parts.append(
                f"{ir_cmd}; "
                f"$_pq drshift -state DRUPDATE -capture -bits {n} {frames[i]}"
            )
            parts.append(f"$_pq state IDLE {idle}")
        parts.append(
            f"{ir_cmd}; "
            f"$_pq drshift -state DRUPDATE -capture -bits {n} {frames[-1]}"
        )
        parts.append("puts [$_pq run -bits]; $_pq delete")
        tcl = "; ".join(parts)
        out = self._send(tcl)
        vals = self._parse_block_bits(out, count)
        self.read_reg(0x0000)
        return vals


    # -- chain shape helpers -------------------------------------------------

    # Idle TCKs after a write: on MPSoC in -register mode writes need more
    # settling TCKs (~100) after the explicit UPDATE-DR.  On 7-series
    # READ_IDLE_CYCLES (20) suffices.
    WRITE_IDLE_CYCLES_REGISTER = 100
    BURST_PREFILL_IDLE_CYCLES = 160

    @property
    def _write_idle_cycles(self) -> int:
        """Idle TCKs after a register write's UPDATE-DR (see _write_reg_tcl)."""
        if self.use_register_ir:
            return self.WRITE_IDLE_CYCLES_REGISTER
        return self.READ_IDLE_CYCLES

    # The selection is written in the same sequence as the access, and
    # hw_server runs a sequence as one uninterrupted unit.
    atomic_slot_select = True

    def _slot_select_tcl(self, seq_var: str, addrs: List[int]) -> List[str]:
        """Scans that write the calling thread's slot selection (see
        :meth:`Transport.slot_scope`), for the head of a ``jtag sequence``
        whose accesses reach *addrs*.

        Nothing when no slot is selected, when the access is on another
        chain, or when every address is in the manager's own block: the
        manager answers those for any slot, and a select ahead of a read of
        ``MGR_ACTIVE`` would overwrite what the read is after.  The write
        scan is not captured, so the sequence's output is unchanged; its
        idle matches :meth:`write_reg`'s.
        """
        sel = self.current_slot_selection()
        if sel is None or sel.chain != self._active_chain:
            return []
        if sel.chain not in self.__dict__.get("_fcapz_manager_chains", ()):
            # Not (or no longer) known to hold a manager: on any other core
            # 0xF008 is some other register, an EJTAG-AXI bridge's reset.
            return []
        if addrs and all(_in_manager_block(a) for a in addrs):
            return []
        # This sequence moves MGR_ACTIVE behind the cache, and may fail
        # after doing so: a later cached select must write for real.
        self.invalidate_manager_instance_cache()
        self._count_manager_select(sel.chain)
        n = self._user_dr_bits(self.DR_BITS)
        ir = self._irshift_tcl(seq_var, chain=sel.chain)
        tcl: List[str] = []
        caps = self.__dict__.get("_fcapz_manager_caps", {}).get(sel.chain, 0)
        if not caps & 0x08:
            # A manager without epochs (MGR_CAPS bit 3) predates the stable
            # burst owner and ignores an ACTIVE write while its burst engine
            # loads, which another client's burst can leave it doing.  A
            # command scan (an uncaptured VERSION read) ends burst mode and
            # the idle outlasts the last fill, as after a burst.
            neutral = self._pad_dr(self._frame_bits(addr=0x0000, data=0, write=False))
            tcl += [
                f"{ir}; ${seq_var} drshift -state DRUPDATE -bits {n} {neutral}",
                f"${seq_var} state IDLE {self.BURST_DRAIN_IDLE_CYCLES}",
            ]
        frame = self._pad_dr(
            self._frame_bits(addr=sel.active_addr, data=sel.slot, write=True)
        )
        return tcl + [
            f"{ir}; ${seq_var} drshift -state DRUPDATE -bits {n} {frame}",
            f"${seq_var} state IDLE {self._write_idle_cycles}",
        ]

    def _ir_hex(self, value: int) -> str:
        """Format an IR opcode as the right-width hex string for ``-hex N``."""
        return f"{value:0{self._ir_hex_digits}x}"

    def _irshift_tcl(self, seq_var: str, chain: int | None = None) -> str:
        """Return the ``irshift`` TCL fragment for *seq_var* targeting *chain*.

        In ``use_register_ir`` mode, emits ``-register user{chain}`` which
        lets xsdb handle the multi-TAP IR routing internally (needed on
        Zynq US+ MPSoC).  Otherwise emits ``-hex {ir_length} {opcode}``
        using the chain's entry in ``ir_table``.
        """
        ch = chain if chain is not None else self._active_chain
        if self.use_register_ir:
            return f"${seq_var} irshift -state IRUPDATE -register user{ch}"
        ir = self._ir_hex(self.ir_table[ch])
        return f"${seq_var} irshift -state IRUPDATE -hex {self.ir_length} {ir}"

    def _user_dr_bits(self, frame_bits: int) -> int:
        """Total bits to shift on a DR scan whose fcapz portion is *frame_bits*."""
        return frame_bits + self.dr_extra_bits

    def _pad_dr(self, frame: str) -> str:
        """Add BYPASS bits to *frame* so the chain-total DR width is correct.

        ``dr_extra_position == "tdo"`` puts BYPASS bits at the LSB end (shifted
        out first, i.e. the bypass TAP is closer to TDO than the fcapz TAP).
        ``"tdi"`` puts them at the MSB end.  The values are zeros — BYPASS
        just relays, so the shift-in bits are don't-care.
        """
        if self.dr_extra_bits == 0:
            return frame
        bypass = "0" * self.dr_extra_bits
        if self.dr_extra_position == "tdo":
            return bypass + frame
        return frame + bypass

    def _dr_data_offset(self) -> int:
        """Index into a captured DR token where the fcapz frame begins."""
        return self.dr_extra_bits if self.dr_extra_position == "tdo" else 0

    # -- frame helpers -------------------------------------------------------

    @staticmethod
    def _frame_bits(addr: int, data: int, write: bool) -> str:
        """Build 49-char '0'/'1' string: bits[31:0]=data, [47:32]=addr, [48]=rnw."""
        chars: list[str] = []
        for i in range(32):
            chars.append("1" if (data >> i) & 1 else "0")
        for i in range(16):
            chars.append("1" if (addr >> i) & 1 else "0")
        chars.append("1" if write else "0")
        return "".join(chars)

    # -- TCL generation ------------------------------------------------------

    def _read_reg_tcl(
        self, frame: str, var_suffix: str = "", *, addr: int | None = None
    ) -> str:
        """Return TCL that performs one register read and returns the bit string.

        One jtag sequence: IR, command DR ending in an explicit UPDATE-DR,
        READ_IDLE_CYCLES idle TCKs for the core to accept the command and
        stage the response, then IR and the capture DR.  ``state IDLE n``
        clocks TCK; ``delay`` would not (it only waits), so it must not be
        used to give the TCK-domain core time.
        """
        v = f"_s{var_suffix}"
        n = self._user_dr_bits(self.DR_BITS)
        idle = self.READ_IDLE_CYCLES
        padded = self._pad_dr(frame)
        ir_cmd = self._irshift_tcl(v)
        select = self._slot_select_tcl(v, [] if addr is None else [addr])
        return (
            f"set {v} [jtag sequence]; "
            + "".join(f"{part}; " for part in select)
            + f"{ir_cmd}; "
            f"${v} drshift -state DRUPDATE -bits {n} {padded}; "
            f"${v} state IDLE {idle}; "
            f"{ir_cmd}; "
            f"${v} drshift -state DRUPDATE -capture -bits {n} {padded}; "
            f"puts [${v} run -bits]; ${v} delete"
        )

    def _write_reg_tcl(self, frame: str, *, addr: int | None = None) -> str:
        n = self._user_dr_bits(self.DR_BITS)
        padded = self._pad_dr(frame)
        ir_cmd = self._irshift_tcl("_w")
        if self.use_register_ir:
            # On MPSoC in -register mode, writes need explicit DRUPDATE
            # state (the -state IDLE shortcut doesn't reliably fire the
            # UPDATE-DR event through the named-register path) and more
            # settling TCKs.
            idle = self.WRITE_IDLE_CYCLES_REGISTER
        else:
            idle = self.READ_IDLE_CYCLES
        select = self._slot_select_tcl("_w", [] if addr is None else [addr])
        return (
            "set _w [jtag sequence]; "
            + "".join(f"{part}; " for part in select)
            + f"{ir_cmd}; "
            f"$_w drshift -state DRUPDATE -bits {n} {padded}; "
            f"$_w state IDLE {idle}; "
            f"$_w run; $_w delete"
        )

    # -- output parsing ------------------------------------------------------

    @staticmethod
    def _bits_to_int(bits: str, offset: int, length: int) -> int:
        result = 0
        for i in range(length):
            if bits[offset + i] == "1":
                result |= 1 << i
        return result

    def _parse_bits_u32(self, output: str) -> int:
        """Extract a 32-bit value from the last bit-string line in *output*."""
        offset = self._dr_data_offset()
        min_len = offset + 32
        for line in reversed(output.strip().splitlines()):
            line = line.strip()
            if line and set(line) <= {"0", "1"} and len(line) >= min_len:
                return self._bits_to_int(line, offset, 32)
        raise RuntimeError(
            "xsdb: no bit string in output. "
            f"stdout={output!r}; "
            f"recent stderr={self._stderr_lines[-10:]!r}"
        )

    def _parse_block_bits(
        self,
        output: str,
        expected: int,
        *,
        skip_words: int = 0,
    ) -> List[int]:
        """Extract *expected* 32-bit values from bit-string tokens."""
        values: list[int] = []
        seen = 0
        offset = self._dr_data_offset()
        min_len = offset + 32
        # Split on whitespace and braces (TCL list elements)
        for token in output.replace("{", " ").replace("}", " ").split():
            token = token.strip()
            if token and set(token) <= {"0", "1"} and len(token) >= min_len:
                if seen < skip_words:
                    seen += 1
                    continue
                seen += 1
                values.append(self._bits_to_int(token, offset, 32))
        if len(values) < expected:
            raise RuntimeError(
                f"xsdb: expected {expected} results, got {len(values)}. "
                f"stdout={output[:500]!r}; "
                f"recent stderr={self._stderr_lines[-10:]!r}"
            )
        return values[:expected]

    def _parse_scan_bits(self, output: str, width: int, total: int) -> int:
        """Extract one raw DR scan result of *width* bits from XSDB output."""
        results = self._parse_scan_bits_list(output, [width], [total])
        return results[0]

    def _parse_scan_bits_list(
        self,
        output: str,
        widths: List[int],
        totals: List[int],
    ) -> List[int]:
        """Extract raw DR scan results with per-scan widths from XSDB output."""
        tokens: list[str] = []
        for token in output.replace("{", " ").replace("}", " ").split():
            token = token.strip()
            if token and set(token) <= {"0", "1"}:
                tokens.append(token)
        offset = self._dr_data_offset()
        out: list[int] = []
        token_idx = 0
        for width, total in zip(widths, totals):
            min_len = max(total, offset + width)
            while token_idx < len(tokens) and len(tokens[token_idx]) < min_len:
                token_idx += 1
            if token_idx >= len(tokens):
                raise RuntimeError(
                    f"xsdb: expected {len(widths)} raw scan results, got {len(out)}. "
                    f"stdout={output[:500]!r}; "
                    f"recent stderr={self._stderr_lines[-10:]!r}"
                )
            out.append(self._bits_to_int(tokens[token_idx], offset, width))
            token_idx += 1
        return out

    # -- process I/O ---------------------------------------------------------

    def _send(
        self, tcl: str, *, check: bool = False, timeout_sec: float | None = None
    ) -> str:
        """Send *tcl* to the persistent xsdb process and return output.

        xsdb reports a failure by *printing* a message and carrying on — a
        piped session has no per-command exit status — so by default this
        returns whatever was printed and the caller decides what it means.
        That suits the read commands, whose output is parsed anyway.

        Pass ``check=True`` for commands whose only failure signal IS that
        message (``targets -set``, ``fpga -file``): the command then runs
        inside a Tcl ``catch`` and a failure raises ``RuntimeError`` instead
        of being swallowed.  Without it a target filter that matches nothing
        programs nothing, the session continues against whatever was already
        in the FPGA, and the user gets wrong data rather than an error.

        Bounded by ``read_timeout_sec`` (or ``timeout_sec`` for one call).
        Waiting forever is not an option: xsdb can stay alive and stop
        answering, and the caller is often a thread that owns the only
        hardware session there is.

        Set environment variable ``FCAPZ_LOG_XSDB=1`` to log every TCL
        request and every xsdb response to ``stderr`` — use this for
        wire-level debugging on unusual chains (e.g. investigating why a
        read returns wrong data on Zynq US+ MPSoC).  The output is noisy
        but decodable: one ``tcl>`` line per request, one ``tdo>`` line
        per response.
        """
        log = os.environ.get("FCAPZ_LOG_XSDB") == "1"
        budget = self.read_timeout_sec if timeout_sec is None else float(timeout_sec)
        if check:
            if "\n" in tcl:
                raise ValueError("check=True needs a single-line TCL command")
            if self._ERR_MARKER in tcl:
                raise ValueError("TCL command contains the error marker")
            # Nothing is printed on success, so a caller that ignores the
            # return value sees exactly what it saw before.  On failure the
            # marker is followed by xsdb's own message, which can run to many
            # lines (a rejected target filter prints the whole target tree),
            # so everything up to the sentinel belongs to it.
            wire = (
                "if {[catch {" + tcl + "} __fcapz_err]} { "
                'puts "' + self._ERR_MARKER + ' $__fcapz_err" }'
            )
        else:
            wire = tcl
        with self._xsdb_io_lock:
            if self._poisoned:
                raise RuntimeError(
                    "xsdb transport was torn down after a timeout or cancel; "
                    "reconnect before using it again"
                )
            if not self._proc or not self._proc.stdin or not self._proc.stdout:
                raise RuntimeError("not connected — call connect() first")
            if log:
                sys.stderr.write(f"[fcapz xsdb] tcl> {wire}\n")
                sys.stderr.flush()
            self._proc.stdin.write(wire + "\n")
            self._proc.stdin.write(f'puts "{self._SENTINEL}"\n')
            self._proc.stdin.flush()

            lines: list[str] = []
            # One deadline for the whole exchange, not per line: a process
            # dribbling one line per interval would otherwise reset the
            # timeout forever and never finish.
            deadline = time.monotonic() + budget
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._poison_after_timeout()
                    raise TimeoutError(
                        "timed out waiting for the xsdb response sentinel "
                        f"after {budget:.1f}s; the session was torn down and "
                        "must be reconnected"
                    )
                try:
                    raw = self._stdout_lines.get(timeout=remaining)
                except queue.Empty:
                    continue
                if raw is None:
                    stderr = "\n".join(self._stderr_lines[-20:])
                    raise ConnectionError(
                        f"xsdb process exited unexpectedly. stderr:\n{stderr}"
                    )
                line = raw.rstrip("\n\r")
                if line.strip() == self._SENTINEL:
                    break
                lines.append(line)
            out = "\n".join(lines)
            if log:
                sys.stderr.write(f"[fcapz xsdb] tdo> {out!r}\n")
                sys.stderr.flush()
            if check and out.lstrip().startswith(self._ERR_MARKER):
                detail = out.lstrip()[len(self._ERR_MARKER):].strip()
                raise RuntimeError(f"xsdb rejected {tcl!r}: {detail}")
            return out

    def _poison_after_timeout(self) -> None:
        """Kill the process so the next caller fails fast instead of hanging.

        A process that missed its deadline has an unread reply in flight;
        reusing the pipe would pair that reply with the next request. Killing
        it also releases whatever the reader thread is blocked on.
        """
        self._poisoned = True
        self.close_fast()

    def _drain_stderr(self) -> None:
        if not self._proc or not self._proc.stderr:
            raise RuntimeError("xsdb process not initialized")
        for raw in self._proc.stderr:
            self._stderr_lines.append(raw.rstrip("\n\r"))

    def _drain_stdout(self) -> None:
        """Move stdout into the queue so no caller ever blocks on the pipe."""
        proc = self._proc
        if not proc or not proc.stdout:
            return
        sink = self._stdout_lines
        try:
            for raw in proc.stdout:
                sink.put(raw)
        except (ValueError, OSError):
            # The pipe was closed under us by close()/cancel(). Expected.
            pass
        sink.put(None)


def hw_server_chain_shape_kwargs(fpga_name: str) -> dict[str, object]:
    """Return the :class:`XilinxHwServerTransport` kwargs for *fpga_name*'s family.

    Meant to be ``**``-unpacked alongside the usual host/port/bitfile
    arguments; the CLI, the GUI and the RPC server all build their hw_server
    transports through it.  An empty dict means "use transport defaults"
    (7-series single-device 6-bit IR, no bypass padding).

    MPSoC (Zynq UltraScale+, ``xck*`` / ``xczu*``) gets only
    ``use_register_ir=True``: xsdb's ``-register userN`` mode routes the
    IR through the PL TAP and ARM DAP and pads the DAP's 1-bit DR BYPASS
    itself, so the host shifts plain fcapz frames.  The PL still sees one
    extra shift clock per DR scan, which the RTL tolerates.  Raw hex IR
    opcodes on that two-TAP chain do not select USER2-4.

    Versal parts (xcvm/xcvc/xcvp/xcve/xcvh) don't use BSCANE2 and aren't
    supported by fcapz; they fall through to defaults and fail loudly at
    the identity check rather than silently pretending to work.
    """
    name_lc = fpga_name.lower()
    # Standalone UltraScale / UltraScale+ (Kintex, Virtex, Artix US+):
    # 6-bit IR, different USER opcodes from 7-series.  Checked before the
    # xck* / xczu* branch below because ``xcku040`` starts with ``xck``.
    if name_lc.startswith(("xcku", "xcvu", "xcau")):
        return {
            "ir_table": XilinxHwServerTransport.IR_TABLE_XILINX_ULTRASCALE,
            "ir_length": 6,
        }
    # Zynq UltraScale+ MPSoC (Kria xck24/xck26, ZCU+ xczu*): register-IR
    # mode handles the PL TAP + ARM DAP routing and padding.
    if name_lc.startswith(("xck", "xczu")):
        return {"use_register_ir": True}
    # 7-series (xc7a / xc7k / xc7v / xc7s / xc7z) and anything else.
    return {}


class VendorStubTransport(Transport):
    """Placeholder adapter for future non-Xilinx backends."""

    def __init__(self, vendor: str):
        self.vendor = vendor

    def connect(self) -> None:
        raise NotImplementedError(f"{self.vendor} transport not implemented")

    def close(self) -> None:
        return None

    def read_reg(self, addr: int) -> int:
        raise NotImplementedError

    def write_reg(self, addr: int, value: int) -> None:
        raise NotImplementedError

    def read_block(self, addr: int, words: int) -> List[int]:
        raise NotImplementedError
