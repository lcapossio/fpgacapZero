# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""The fcapz broker: several programs share one cable and core safely.

Opt-in (``fcapz --broker ...`` or ``FCAPZ_BROKER=1``).  The first client
starts a per-user runtime process that owns the transports; clients submit
whole operations (a capture from configure to readout, an EIO access, an
EJTAG-AXI transfer) and each core runs one at a time, in order.  See
``docs/21_broker.md``.
"""

from .coreref import CoreRef, TargetSpec
from .session import BrokerCapture, BrokerNotRunning, BrokerSession
from .wire import (
    BrokerConnectionLost,
    BrokerError,
    BrokerRemoteError,
    BrokerStartError,
    CoreBusy,
    ImageChanged,
    JobCancelled,
    TargetMismatch,
)

__all__ = [
    "BrokerCapture",
    "BrokerConnectionLost",
    "BrokerError",
    "BrokerNotRunning",
    "BrokerRemoteError",
    "BrokerSession",
    "BrokerStartError",
    "CoreBusy",
    "CoreRef",
    "ImageChanged",
    "JobCancelled",
    "TargetMismatch",
    "TargetSpec",
]
