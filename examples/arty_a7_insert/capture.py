#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Program the insertion demo onto an Arty A7 and check one capture.

The probe layout comes from the ``.prob`` file fcapz_insert_vivado.tcl wrote;
the capture triggers on ``count == 0x40`` and checks that ``count`` steps by
one, ``lfsr`` follows its feedback polynomial and ``u_gen/triple`` is three
times the previous count, on every sample.

    python examples/arty_a7_insert/capture.py [--port 3121] [--no-program]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fcapz.analyzer import Analyzer, CaptureConfig, TriggerConfig
from fcapz.probes import load_probe_file
from fcapz.transport import XilinxHwServerTransport

HERE = Path(__file__).resolve().parent


def lfsr_next(v: int) -> int:
    fb = ((v >> 15) ^ (v >> 13) ^ (v >> 12) ^ (v >> 10)) & 1
    return ((v << 1) | fb) & 0xFFFF


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=3121)
    ap.add_argument("--fpga", default="xc7a100t")
    ap.add_argument("--no-program", action="store_true")
    args = ap.parse_args()

    prob = load_probe_file(HERE / "insert_demo.prob")
    fields = {p.name: p for p in prob.probes}
    bitfile = None if args.no_program else str(HERE / "insert_demo_top.bit")

    a = Analyzer(XilinxHwServerTransport(port=args.port, fpga_name=args.fpga, bitfile=bitfile))
    try:
        a.connect()
        cnt = fields["count"]
        a.configure(CaptureConfig(
            pretrigger=8,
            posttrigger=56,
            trigger=TriggerConfig(mode="value_match", value=0x40 << cnt.lsb,
                                  mask=((1 << cnt.width) - 1) << cnt.lsb),
            sample_width=prob.sample_width,
            depth=1024,
            sample_clock_hz=prob.sample_clock_hz or 100_000_000,
            probes=prob.probes,
        ))
        a.arm()
        result = a.capture(timeout=5.0)
    finally:
        a.close()

    def field(sample: int, name: str) -> int:
        p = fields[name]
        return (sample >> p.lsb) & ((1 << p.width) - 1)

    counts = [field(s, "count") for s in result.samples]
    lfsrs = [field(s, "lfsr") for s in result.samples]
    triples = [field(s, "u_gen/triple") for s in result.samples]
    errors = []
    for i in range(1, len(result.samples)):
        if (counts[i] - counts[i - 1]) & 0xFF != 1:
            errors.append(f"count[{i}] {counts[i - 1]:#04x} -> {counts[i]:#04x}")
        if lfsrs[i] != lfsr_next(lfsrs[i - 1]):
            errors.append(f"lfsr[{i}] {lfsrs[i - 1]:#06x} -> {lfsrs[i]:#06x}")
        # u_gen/triple registers count * 3, so it trails count by a cycle.
        if triples[i] != (counts[i - 1] * 3) & 0xFF:
            errors.append(f"u_gen/triple[{i}] {triples[i]:#04x} != 3 * {counts[i - 1]:#04x}")
    for i in range(min(12, len(counts))):
        print(f"{i:3d}  count={counts[i]:#04x}  lfsr={lfsrs[i]:#06x}  "
              f"u_gen/triple={triples[i]:#04x}")
    print(f"{len(result.samples)} samples, 0x40 present: {0x40 in counts}, "
          f"{len(errors)} error(s)")
    for e in errors[:10]:
        print("  ", e)
    return 0 if not errors and 0x40 in counts and len(result.samples) > 1 else 1


if __name__ == "__main__":
    sys.exit(main())
