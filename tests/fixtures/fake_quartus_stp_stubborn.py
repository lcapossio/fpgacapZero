#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""A ``quartus_stp`` stand-in that refuses to exit.

Answers scripts normally so ``close()`` can still run its ``close_device``
teardown, but ignores ``exit`` and keeps running after stdin reaches EOF.
``close()`` must escalate to terminate/kill rather than return while this
process is alive still holding the cable.
"""

from __future__ import annotations

import sys
import time


SENTINEL = "<<FCAPZ_QUARTUS_STP_DONE>>"


def main() -> int:
    for line in sys.stdin:
        if line.strip() != "flush stdout":
            continue
        print("tcl> @1: FAKE_FPGA", flush=True)
        print(f"tcl> {SENTINEL}", flush=True)
    while True:  # stdin is closed and we still will not go away
        time.sleep(0.5)


if __name__ == "__main__":
    raise SystemExit(main())
