#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Program the KV260 insertion demo and check every inserted core.

The same checks as examples/arty_a7_insert/capture.py (each ELA's data, the
EIO read-back, armed_out, the cross-trigger and trigger_in), on the KV260's
clk (pl_clk0) and clk_div (pl_clk0 / 3).  pl_clk0 runs at whatever rate the
boot firmware set, so the .prob sample rates are not checked.

    python examples/kv260_insert/capture.py [--port 3121] [--no-program]
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from fcapz.transport import XilinxHwServerTransport, hw_server_chain_shape_kwargs

HERE = Path(__file__).resolve().parent


def _arty_demo():
    path = HERE.parent / "arty_a7_insert" / "capture.py"
    spec = importlib.util.spec_from_file_location("arty_a7_insert_capture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Demo


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=3121)
    ap.add_argument("--fpga", default="xck26")
    ap.add_argument("--no-program", action="store_true")
    args = ap.parse_args()

    bitfile = None if args.no_program else str(HERE / "insert_demo_top.bit")
    t = XilinxHwServerTransport(
        port=args.port, fpga_name=args.fpga, bitfile=bitfile,
        **hw_server_chain_shape_kwargs(args.fpga),
    )
    t.connect()
    demo = _arty_demo()(t, HERE, "clk", "clk_div", None)
    try:
        demo.run()
    finally:
        t.close()
    print(f"{len(demo.errors)} failure(s)")
    return 1 if demo.errors else 0


if __name__ == "__main__":
    sys.exit(main())
