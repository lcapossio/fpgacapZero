#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""A ``quartus_stp`` stand-in that leaves a child holding its output pipes.

Starts a long-lived child that inherits stdout and stderr, as quartus_stp can
when it launches a helper such as jtagd, and writes the child's pid to the
file named by the first argument.  It then answers scripts and exits normally.
Once it has gone, the transport's drain threads still see no EOF, because the
child keeps the write ends open; ``close()`` must return anyway.
"""

from __future__ import annotations

import subprocess
import sys


SENTINEL = "<<FCAPZ_QUARTUS_STP_DONE>>"


def main() -> int:
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
    )
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        f.write(str(child.pid))
    for line in sys.stdin:
        if line.strip() == "exit":
            break
        if line.strip() != "flush stdout":
            continue
        print("tcl> @1: FAKE_FPGA", flush=True)
        print(f"tcl> {SENTINEL}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
