# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Temporarily select a BSCAN USER chain, then restore the ELA default (chain 1)."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from ..transport import Transport

# Analyzer register path uses USER1 (chain index 1 in the default IR table).
ELA_DEFAULT_CHAIN = 1


class JtagBusyError(RuntimeError):
    """Another operation (a running capture) holds the transport."""


@contextmanager
def subsidiary_jtag_chain(
    transport: Transport, chain: int, *, timeout: float = 1.0
) -> Iterator[None]:
    """Run the body on *chain*, then restore chain 1.

    Holds the transport's transaction lock from the switch through the
    restore: the chain is shared transport state, and switching it without
    the lock lands between a capture worker's own chain select and its next
    access, sending that access down the wrong chain.

    Runs on the Qt thread, and a capture holds the lock for its whole wait,
    so this gives up after *timeout* seconds (``0`` means do not wait) with
    :class:`JtagBusyError` instead of freezing the window.
    """
    lock = transport.transaction_lock()
    if timeout > 0:
        acquired = lock.acquire(timeout=timeout)
    else:
        acquired = lock.acquire(blocking=False)
    if not acquired:
        raise JtagBusyError("A capture is running and holds the JTAG connection.")
    try:
        transport.select_chain(chain)
        try:
            yield
        finally:
            transport.select_chain(ELA_DEFAULT_CHAIN)
    finally:
        lock.release()
