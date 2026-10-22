# Arty A7: post-synthesis ELA insertion (prototype)

This design contains no fcapz RTL. The signals to capture are marked
with `mark_debug`, the same as for Vivado's own ILA:

```verilog
(* mark_debug = "true" *) reg [7:0]  count;
(* mark_debug = "true" *) reg [15:0] lfsr;
```

After synthesis, [`tools/fcapz_insert_vivado.tcl`](../../tools/fcapz_insert_vivado.tcl)
adds an `fcapz_ela_xilinx7` to the netlist. Your RTL does not change.

## Build and check

```bash
vivado -mode batch -source examples/arty_a7_insert/build.tcl
PYTHONPATH=host python examples/arty_a7_insert/capture.py   # programs and captures
```

`build.tcl` runs the steps as a plain non-project flow. To use them in
your own flow, add `fcapz::insert` between synthesis and `opt_design`:

```tcl
source tools/fcapz_insert_vivado.tcl
fcapz::insert -in post_synth.dcp -out instrumented.dcp -rtl rtl \
    -prob design.prob [-depth 1024] [-chain 1] [-clock <net>] [-clock_hz <hz>]
# the instrumented design is left open: opt_design, place_design, ...
```

## What `fcapz::insert` does

1. It collects every MARK_DEBUG net. It also finds the clock that drives them,
   unless you pass `-clock`.
2. It synthesizes `fcapz_ela_xilinx7` out of context, with `SAMPLE_W` equal to
   the number of probe bits.
3. It creates a black-box cell and fills it from that checkpoint with
   `read_checkpoint -cell`.
4. It connects the probe nets to `probe_in` and the clock to `sample_clk`, and
   ties `sample_rst` and `trigger_in` low.
5. It constrains the BSCANE2 TCK and makes it asynchronous to every other
   clock.
6. It writes a `.prob` file that maps each signal to its bits, so the host
   can name them:

```json
{"format": "fpgacapzero.probes.v1", "core": "ela",
 "probes": [{"name": "count", "width": 8, "lsb": 0},
            {"name": "lfsr", "width": 16, "lsb": 8}],
 "sample_clock_hz": 100000000, "sample_width": 24}
```

## Limits of the prototype

- It inserts one ELA, sampling one clock domain. Nets from several clocks
  are refused.
- It supports Xilinx 7-series only.
- It inserts a standalone ELA on one USER chain, which must be free. It
  stops if another BSCANE2 already uses that chain, for example Vivado's
  `dbg_hub` on USER1.
- It does not add a multi-core manager or an EIO, and it does not support
  the external trigger.
