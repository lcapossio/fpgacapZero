<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
-->

# KV260: debug cores inserted after synthesis

The Zynq UltraScale+ counterpart of
[`examples/arty_a7_insert`](../arty_a7_insert/README.md): a design with no
fcapz RTL, its signals marked with `mark_debug`, and the debug cores added
to the synthesized netlist by
[`tools/fcapz_insert_vivado.tcl`](../../tools/fcapz_insert_vivado.tcl), which
picks the UltraScale TAP wrapper from the part. See
[RTL integration: insertion after synthesis](../../docs/04_rtl_integration.md#without-rtl-changes-insertion-after-synthesis-vivado)
for the flow and its options.

## The demo

The KV260 has no PL oscillator, so the clocks come from the PS:
`clk` is `pl_clk0` (from the block design in
[`examples/kv260/create_ps_bd.tcl`](../kv260/create_ps_bd.tcl)) and
`clk_div` is `pl_clk0 / 3` from a `BUFGCE_DIV`. `pl_clk0` runs at whatever
rate the boot firmware set (see [`examples/kv260`](../kv260/README.md)).

| Instance | Core | Signals |
| --- | --- | --- |
| 0 | ELA on `clk`, 1024 samples | `count`, `lfsr`, `tick`, `u_gen/triple`, `ctrl_q` |
| 1 | ELA on `clk_div`, 512 samples | `slow_count`, `slow_lfsr` |
| 2 | EIO | in: `ctrl_q`, `armed_flag`; out: `ctrl` |

The triggers are the Arty demo's: `tick` starts ELA 1 (`-trigger_in`),
ELA 1's trigger starts ELA 0 (`-cross_trigger`), and ELA 0's armed level
drives `armed_flag` (`-armed_out`).

## Build and check

Needs Vivado with the KV260 SOM board files (`kv260_som`, from the Vivado
board store), and the kit's USB-JTAG with `hw_server` on the default port.

```bash
vivado -mode batch -source examples/kv260_insert/build.tcl
PYTHONPATH=host python examples/kv260_insert/capture.py   # programs, then checks
```

`build.tcl` synthesizes in a project (for the PS block design), writes the
post-synthesis checkpoint, and continues non-project from the instrumented
one; it fails if timing is not met. `capture.py` runs the Arty demo's
checks against this build.

Built with Vivado 2025.2: timing met against the 200 MHz `pl_clk0`
constraint (WNS +1.445 ns, WHS +0.012 ns), and `capture.py` passes all 18
checks on a KV260 (the Arty's 19 less its switch read, as the KV260 has no
switches).
