# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""A fake ELA transport for the broker tests, in-process and in the runtime.

The core manager holds two ELA slots.  A RESET leaves a slot idle, or armed
again when its runtime STARTUP_ARM register is set, as the core does.  An ARM
leaves a slot armed until it is triggered: by
:meth:`FakeElaTransport.trigger` in-process, or, in a runtime subprocess, by
a file ``trigger-<slot>`` in ``FCAPZ_BROKER_FAKE_DIR``
(removed when taken).  ``FCAPZ_BROKER_FAKE_AUTO=1`` triggers every arm at
once.  ``fail-connect`` in that directory makes ``connect()`` raise, and
``fail-io`` makes the next register access raise ``OSError`` once
(``fail_io = "always"`` in-process: every access, a dead cable).
``FCAPZ_BROKER_FAKE_CLOSE_S`` makes ``close()`` take that long, as a real
cable's does.

Chain 3 holds a plain EIO (no manager) whose outputs read back and whose
inputs read ``0xA5``.  Every access on a chain in ``missing_chains`` raises
``RuntimeError``, as quartus_stp does for a virtual JTAG instance that is
not there.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from fcapz import _version_tuple
from fcapz.analyzer import CORE_MANAGER_CORE_ID, expected_ela_version_reg
from fcapz.eio import EIO_CORE_ID
from fcapz.transport import Transport

_CTRL, _STATUS = 0x0004, 0x0008
_ARMED, _DONE = 0x1, 0x4
_MGR_ACTIVE = 0xF008
_STARTUP_ARM = 0x00D8


def _slot_regs() -> dict[int, int]:
    return {
        0x0000: expected_ela_version_reg(),
        0x000C: 8,            # SAMPLE_W
        0x0010: 1024,         # DEPTH
        0x0008: 0x0,          # STATUS idle
        0x00A4: 1,            # NUM_CHAN
        0x003C: 0x0001_0164,  # FEATURES
        0x00C4: 0,            # TIMESTAMP_W
        0x00B8: 1,            # NUM_SEGMENTS
        0x00E0: 0x3_01FF,     # COMPARE_CAPS
    }


class FakeElaTransport(Transport):
    def __init__(self, ctl_dir: str | None = None, auto: bool = False) -> None:
        self.ctl_dir = Path(ctl_dir) if ctl_dir else None
        self.auto = auto
        self.slots = {0: _slot_regs(), 1: _slot_regs()}
        self.active = 0
        self.chain = 1
        self.eio = {
            0x0000: ((_version_tuple()[0] & 0xFF) << 24)
            | ((_version_tuple()[1] & 0xFF) << 16)
            | EIO_CORE_ID,
            0x0004: 8,       # IN_W
            0x0008: 8,       # OUT_W
            0x0010: 0xA5,    # IN[0]
            0x0100: 0,       # OUT[0]
        }
        self.arms = {0: 0, 1: 0}
        self.connects = 0
        self.closed = 0
        self.fail_io = False
        self.missing_chains: set[int] = set()
        self._triggers = {0: threading.Event(), 1: threading.Event()}
        self._mgr = {
            0xF000: ((_version_tuple()[0] & 0xFF) << 24)
            | ((_version_tuple()[1] & 0xFF) << 16)
            | CORE_MANAGER_CORE_ID,
            0xF004: 2,       # MGR_COUNT
            _MGR_ACTIVE: 0,
            0xF00C: 0,
            0xF010: 1,
        }

    # ---- control -------------------------------------------------------

    def trigger(self, slot: int = 0) -> None:
        self._triggers[slot].set()

    def _ctl(self, name: str) -> bool:
        if self.ctl_dir is None:
            return False
        path = self.ctl_dir / name
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
            return True
        return False

    def _maybe_fail(self) -> None:
        if self.chain in self.missing_chains:
            raise RuntimeError(f"no virtual JTAG instance {self.chain}")
        if self.fail_io or self._ctl("fail-io"):
            if self.fail_io != "always":
                self.fail_io = False
            raise OSError("fake cable unplugged")

    # ---- Transport -----------------------------------------------------

    def connect(self) -> None:
        if self.ctl_dir is not None and (self.ctl_dir / "fail-connect").exists():
            raise OSError("fake cable not found")
        self.connects += 1

    def close(self) -> None:
        time.sleep(float(os.environ.get("FCAPZ_BROKER_FAKE_CLOSE_S") or 0))
        self.closed += 1

    def select_chain(self, chain: int) -> None:
        self.chain = int(chain)

    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        return bits

    def read_reg(self, addr: int) -> int:
        self._maybe_fail()
        if self.chain == 3:
            return self.eio.get(addr, 0)
        if addr in self._mgr:
            return self._mgr[addr]
        if addr == _STATUS:
            regs = self.slots[self.active]
            if regs[_STATUS] & _ARMED and (
                self.auto
                or self._triggers[self.active].is_set()
                or self._ctl(f"trigger-{self.active}")
            ):
                self._triggers[self.active].clear()
                regs[_STATUS] = _DONE
            return regs[_STATUS]
        return self.slots[self.active].get(addr, 0)

    def read_regs_pipelined_user1(self, addrs: list[int]) -> list[int]:
        out = [self.read_reg(a) for a in addrs]
        self.read_reg(0x0000)
        return out

    def write_reg(self, addr: int, value: int) -> None:
        self._maybe_fail()
        if self.chain == 3:
            self.eio[addr] = int(value)
            return
        if addr == _MGR_ACTIVE:
            self.active = int(value)
            self._mgr[addr] = int(value)
            return
        if addr in self._mgr:
            self._mgr[addr] = value
            return
        regs = self.slots[self.active]
        if addr == _CTRL:
            if value & 0x2:      # RESET: re-arms at once with STARTUP_ARM set
                regs[_STATUS] = _ARMED if regs.get(_STARTUP_ARM, 0) & 1 else 0
            if value & 0x1:      # ARM
                regs[_STATUS] = _ARMED
                self.arms[self.active] += 1
            return
        regs[addr] = value

    def read_block(self, addr: int, words: int):
        self._maybe_fail()
        base = 0x10 * (self.active + 1)
        return [(base + i) & 0xFF for i in range(words)]


def make_transport(spec) -> FakeElaTransport:
    """Runtime transport factory (``FCAPZ_BROKER_TRANSPORT_FACTORY``)."""
    return FakeElaTransport(
        os.environ.get("FCAPZ_BROKER_FAKE_DIR"),
        auto=os.environ.get("FCAPZ_BROKER_FAKE_AUTO") == "1",
    )
