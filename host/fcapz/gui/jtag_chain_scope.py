# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Temporarily select a BSCAN USER chain, then restore the ELA default (chain 1)."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from ..transport import Transport

# Analyzer register path uses USER1 (chain index 1 in the default IR table).
ELA_DEFAULT_CHAIN = 1


@contextmanager
def subsidiary_jtag_chain(transport: Transport, chain: int) -> Iterator[None]:
    transport.select_chain(chain)
    try:
        yield
    finally:
        transport.select_chain(ELA_DEFAULT_CHAIN)
