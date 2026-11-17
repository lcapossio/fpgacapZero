# Arty A7: debug cores inserted after synthesis

This design contains no fcapz RTL. The signals to capture are marked
with `mark_debug`, the same as for Vivado's own ILA. After synthesis,
[`tools/fcapz_insert_vivado.tcl`](../../tools/fcapz_insert_vivado.tcl)
adds the debug cores to the netlist; the RTL does not change. The flow and
its options are described in
[RTL integration: insertion after synthesis](../../docs/04_rtl_integration.md#without-rtl-changes-insertion-after-synthesis-vivado).

## The demo

`insert_demo_top.v` runs two clock domains, the board's 100 MHz and
62.5 MHz from an MMCM. `build.tcl` inserts:

| Instance | Core | Signals |
| --- | --- | --- |
| 0 | ELA on `clk_IBUF_BUFG`, 1024 samples | `count`, `lfsr`, `tick`, `u_gen/triple`, `ctrl_q` |
| 1 | ELA on `clk_slow`, 512 samples | `slow_count`, `slow_lfsr` |
| 2 | EIO | in: `sw_q` (the switches), `ctrl_q`, `armed_flag`; out: `ctrl` |

and the triggers between them:

- `-trigger_in {clk_slow tick}`: `tick` (4 cycles of every 256 at 100 MHz)
  starts ELA 1.
- `-cross_trigger {clk_IBUF_BUFG clk_slow}`: ELA 1's trigger starts ELA 0.
- `-armed_out {clk_IBUF_BUFG armed_flag}`: ELA 0's armed level drives
  `armed_flag`, which the EIO reads back.

`ctrl` and `armed_flag` are placeholders: registers that hold 0, kept with
`dont_touch`, whose drivers the insertion replaces. The design registers
`ctrl` into `ctrl_q`, so a value the host writes comes back.

## Build and check

```bash
vivado -mode batch -source examples/arty_a7_insert/build.tcl
PYTHONPATH=host python examples/arty_a7_insert/capture.py   # programs, then checks
```

`build.tcl` writes `insert_demo_ela0.prob`, `insert_demo_ela1.prob`, the
`insert_demo.insert.json` manifest and the bitstream; timing and the TCK
crossings go to `vivado/arty_a7_insert/timing.rpt` and `cdc.rpt`.
`capture.py` checks each ELA's data, the EIO read-back, `armed_out`, the
cross-trigger and `trigger_in`.

Measured on an Arty A7-100T with Vivado 2025.2: timing met
(WNS +2.758 ns, WHS +0.061 ns), and `capture.py` passes all 19 checks.
