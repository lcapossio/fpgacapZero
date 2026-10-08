#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""A ``quartus_stp`` stand-in whose ``open_device`` never finishes.

Prints a line every 10 ms and never the response sentinel, so a reader that
restarts its timeout on each line waits forever.  ``close()`` from another
thread -- a GUI cancel -- must still get through while ``connect()`` is stuck
here.
"""

from __future__ import annotations

import sys
import time


def main() -> int:
    for line in sys.stdin:
        if line.strip() != "flush stdout":
            continue
        while True:
            print("tcl> Info: still scanning the JTAG chain", flush=True)
            time.sleep(0.01)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
