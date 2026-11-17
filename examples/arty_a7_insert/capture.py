#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Program the insertion demo onto an Arty A7 and check every inserted core.

Instance numbers and bit positions come from the ``insert_demo.insert.json``
manifest and the ``.prob`` files fcapz_insert_vivado.tcl wrote.  Checks:

* the 100 MHz ELA: ``count`` steps by one, ``lfsr`` follows its polynomial,
  ``u_gen/triple`` is three times the previous count;
* the 62.5 MHz ELA: ``slow_count`` steps by one, ``slow_lfsr`` follows its
  polynomial;
* the EIO: a value written to ``ctrl`` comes back on ``ctrl_q``, both
  through the EIO inputs and in a capture;
* ``-armed_out``: ``armed_flag`` is high while the 100 MHz ELA waits;
* ``-cross_trigger``: the 62.5 MHz ELA's trigger starts the 100 MHz ELA,
  armed to fire on its external trigger only;
* ``-trigger_in``: ``tick`` starts the 62.5 MHz ELA, armed the same way.

    python examples/arty_a7_insert/capture.py [--port 3121] [--no-program]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from fcapz.analyzer import Analyzer, CaptureConfig, TriggerConfig
from fcapz.eio import EioController
from fcapz.probes import load_probe_file
from fcapz.transport import XilinxHwServerTransport

HERE = Path(__file__).resolve().parent


def lfsr_next(v: int) -> int:
    fb = ((v >> 15) ^ (v >> 13) ^ (v >> 12) ^ (v >> 10)) & 1
    return ((v << 1) | fb) & 0xFFFF


class Demo:
    """The checks, for any build of this demo's design: *fast* and *slow*
    name the two ELAs (their clock nets), *slow_hz* the sample rate the
    slow ELA's .prob should carry (None: not checked)."""

    def __init__(self, transport, folder: Path, fast: str, slow: str,
                 slow_hz: int | None) -> None:
        self.t = transport
        manifest = json.loads((folder / "insert_demo.insert.json").read_text(encoding="utf-8"))
        self.elas = {e["name"]: e for e in manifest["elas"]}
        self.eio_map = manifest["eio"]
        self.probes = {
            name: load_probe_file(folder / e["prob"]) for name, e in self.elas.items()
        }
        self.fast, self.slow, self.slow_hz = fast, slow, slow_hz
        self.errors: list[str] = []

    def run(self) -> None:
        try:
            self.eio_loopback(0xA)
            self.fast_ela_data(0xA)
            self.eio_loopback(0x5)
            self.slow_ela_data()
            self.cross_trigger_and_armed()
            self.trigger_in()
        finally:
            self.eio().write_outputs(0)

    # ---- helpers ---------------------------------------------------------
    def check(self, ok: bool, what: str) -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {what}")
        if not ok:
            self.errors.append(what)

    def ela(self, name: str) -> Analyzer:
        a = Analyzer(self.t, instance=self.elas[name]["instance"])
        a.select_instance(self.elas[name]["instance"])
        return a

    def eio(self) -> EioController:
        e = EioController(self.t, chain=1, instance=self.eio_map["instance"])
        e.attach()
        return e

    def eio_field(self, value: int, name: str) -> int:
        f = next(s for s in self.eio_map["in"] if s["name"] == name)
        return (value >> f["lsb"]) & ((1 << f["width"]) - 1)

    def config(self, name: str, trigger: TriggerConfig, *, ext: int = 0,
               pre: int = 8, post: int = 56) -> CaptureConfig:
        prob = self.probes[name]
        return CaptureConfig(
            pretrigger=pre, posttrigger=post, trigger=trigger,
            sample_width=prob.sample_width, depth=self.elas[name]["depth"],
            sample_clock_hz=prob.sample_clock_hz, probes=prob.probes,
            ext_trigger_mode=ext,
        )

    def value_trigger(self, name: str, signal: str, value: int) -> TriggerConfig:
        p = next(p for p in self.probes[name].probes if p.name == signal)
        return TriggerConfig(mode="value_match", value=value << p.lsb,
                             mask=((1 << p.width) - 1) << p.lsb)

    def fields(self, name: str, samples: list[int], signal: str) -> list[int]:
        p = next(p for p in self.probes[name].probes if p.name == signal)
        return [(s >> p.lsb) & ((1 << p.width) - 1) for s in samples]

    # ---- checks ----------------------------------------------------------
    def fast_ela_data(self, ctrl: int) -> None:
        print(f"ELA {self.elas[self.fast]['instance']} ({self.fast}): value trigger")
        a = self.ela(self.fast)
        a.configure(self.config(self.fast, self.value_trigger(self.fast, "count", 0x40)))
        a.arm()
        a.select_instance(self.elas[self.fast]["instance"])
        r = a.capture(timeout=5.0)
        counts = self.fields(self.fast, r.samples, "count")
        lfsrs = self.fields(self.fast, r.samples, "lfsr")
        triples = self.fields(self.fast, r.samples, "u_gen/triple")
        ctrls = self.fields(self.fast, r.samples, "ctrl_q")
        n = len(r.samples)
        self.check(n == 65 and 0x40 in counts, f"{n} samples with count 0x40")
        self.check(all((counts[i] - counts[i - 1]) & 0xFF == 1 for i in range(1, n)),
                   "count steps by one")
        self.check(all(lfsrs[i] == lfsr_next(lfsrs[i - 1]) for i in range(1, n)),
                   "lfsr follows its polynomial")
        self.check(all(triples[i] == (counts[i - 1] * 3) & 0xFF for i in range(1, n)),
                   "u_gen/triple is 3 x the previous count")
        self.check(set(ctrls) == {ctrl}, f"ctrl_q holds the EIO value {ctrl:#x} ({set(ctrls)})")

    def slow_ela_data(self) -> None:
        print(f"ELA {self.elas[self.slow]['instance']} ({self.slow}): value trigger")
        a = self.ela(self.slow)
        a.configure(self.config(self.slow, self.value_trigger(self.slow, "slow_count", 0x40)))
        a.arm()
        a.select_instance(self.elas[self.slow]["instance"])
        r = a.capture(timeout=5.0)
        counts = self.fields(self.slow, r.samples, "slow_count")
        lfsrs = self.fields(self.slow, r.samples, "slow_lfsr")
        n = len(r.samples)
        self.check(n == 65 and 0x40 in counts, f"{n} samples with slow_count 0x40")
        self.check(all((counts[i] - counts[i - 1]) & 0xFF == 1 for i in range(1, n)),
                   "slow_count steps by one")
        self.check(all(lfsrs[i] == lfsr_next(lfsrs[i - 1]) for i in range(1, n)),
                   "slow_lfsr follows its polynomial")
        if self.slow_hz is not None:
            hz = self.probes[self.slow].sample_clock_hz
            self.check(hz == self.slow_hz,
                       f"sample clock in the .prob is {self.slow_hz} Hz ({hz})")

    def eio_loopback(self, value: int) -> None:
        print(f"EIO {self.eio_map['instance']}: write ctrl, read ctrl_q")
        e = self.eio()
        e.write_outputs(value)
        time.sleep(0.01)
        got = self.eio_field(e.read_inputs(), "ctrl_q")
        self.check(got == value, f"ctrl_q reads back {got:#x}, wrote {value:#x}")
        if any(s["name"] == "sw_q" for s in self.eio_map["in"]):
            print(f"       switches: {self.eio_field(e.read_inputs(), 'sw_q'):#06b}")

    def cross_trigger_and_armed(self) -> None:
        print(f"cross-trigger {self.slow} -> {self.fast}, armed_out")
        e = self.eio()
        fast = self.ela(self.fast)
        # Fires only on its external trigger: AND with an always-true compare.
        fast.configure(self.config(self.fast, TriggerConfig(mode="value_match", value=0, mask=0),
                                   ext=2, pre=4, post=11))
        fast.arm()
        time.sleep(0.2)
        fast.select_instance(self.elas[self.fast]["instance"])
        self.check(not fast.status()["triggered"], f"{self.fast} ELA waits without a trigger")
        self.check(self.eio_field(e.read_inputs(), "armed_flag") == 1,
                   "armed_flag is high while it waits")
        slow = self.ela(self.slow)
        slow.configure(self.config(self.slow, self.value_trigger(self.slow, "slow_count", 0x40)))
        slow.arm()
        slow.select_instance(self.elas[self.slow]["instance"])
        r_slow = slow.capture(timeout=5.0)
        fast.select_instance(self.elas[self.fast]["instance"])
        r_fast = fast.capture(timeout=5.0)
        self.check(len(r_slow.samples) == 65, f"{self.slow} ELA triggered on its value")
        self.check(len(r_fast.samples) == 16, f"{self.fast} ELA started by the cross-trigger")
        self.check(self.eio_field(e.read_inputs(), "armed_flag") == 0,
                   "armed_flag is low once it has captured")

    def trigger_in(self) -> None:
        print(f"trigger_in tick -> {self.slow}")
        slow = self.ela(self.slow)
        slow.configure(self.config(self.slow, TriggerConfig(mode="value_match", value=0, mask=0),
                                   ext=2, pre=4, post=11))
        slow.arm()
        slow.select_instance(self.elas[self.slow]["instance"])
        r = slow.capture(timeout=5.0)
        self.check(len(r.samples) == 16, f"{self.slow} ELA started by tick")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=3121)
    ap.add_argument("--fpga", default="xc7a100t")
    ap.add_argument("--no-program", action="store_true")
    args = ap.parse_args()

    bitfile = None if args.no_program else str(HERE / "insert_demo_top.bit")
    t = XilinxHwServerTransport(port=args.port, fpga_name=args.fpga, bitfile=bitfile)
    t.connect()
    demo = Demo(t, HERE, "clk_IBUF_BUFG", "clk_slow", 62_500_000)
    try:
        demo.run()
    finally:
        t.close()
    print(f"{len(demo.errors)} failure(s)")
    return 1 if demo.errors else 0


if __name__ == "__main__":
    sys.exit(main())
