# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import threading
import unittest

from fcapz.gui.jtag_chain_scope import JtagBusyError, subsidiary_jtag_chain
from fcapz.transport import Transport


class _ChainTransport(Transport):
    def __init__(self) -> None:
        self.chains: list[int] = []

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def select_chain(self, chain: int) -> None:
        self.chains.append(chain)

    def read_reg(self, addr: int) -> int:
        return 0

    def write_reg(self, addr: int, value: int) -> None:
        pass

    def read_block(self, addr: int, words: int):
        return [0] * words


def _held_elsewhere(transport: Transport):
    """Hold the transaction lock on another thread, as a capture worker does."""
    taken = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with transport.transaction_lock():
            taken.set()
            release.wait(5)

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert taken.wait(5)
    return release, holder


class SubsidiaryJtagChainTests(unittest.TestCase):
    def test_switch_and_restore_happen_under_the_transaction_lock(self):
        """Switching the shared chain without the lock lands between another
        thread's chain select and its access."""
        t = _ChainTransport()
        seen = []

        def probe() -> None:
            lock = t.transaction_lock()
            got = lock.acquire(blocking=False)
            if got:
                lock.release()
            seen.append(got)

        with subsidiary_jtag_chain(t, 3):
            other = threading.Thread(target=probe)
            other.start()
            other.join(5)
        self.assertEqual(seen, [False], "the body ran without holding the lock")
        self.assertEqual(t.chains, [3, 1])

    def test_busy_transport_raises_without_touching_the_chain(self):
        t = _ChainTransport()
        release, holder = _held_elsewhere(t)
        try:
            with self.assertRaises(JtagBusyError):
                with subsidiary_jtag_chain(t, 3, timeout=0):
                    self.fail("body ran while another thread held the lock")
            with self.assertRaises(JtagBusyError):
                with subsidiary_jtag_chain(t, 3, timeout=0.05):
                    self.fail("body ran while another thread held the lock")
        finally:
            release.set()
            holder.join(5)
        self.assertEqual(t.chains, [])

    def test_restores_chain_1_and_releases_when_the_body_raises(self):
        t = _ChainTransport()
        with self.assertRaises(ValueError):
            with subsidiary_jtag_chain(t, 2):
                raise ValueError("boom")
        self.assertEqual(t.chains, [2, 1])
        lock = t.transaction_lock()
        self.assertTrue(lock.acquire(blocking=False))
        lock.release()


if __name__ == "__main__":
    unittest.main()
