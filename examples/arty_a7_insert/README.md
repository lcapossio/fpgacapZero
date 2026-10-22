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
    -prob design.prob -clock_hz 100000000
# the instrumented design is left open: opt_design, place_design, ...
```

Other options:
- `-depth`: number of samples, 1024 by default.
- `-chain`: the USER chain, 1 by default.
- `-clock`: the full hierarchical name of the sample clock net, when it can't
  be found automatically.
- `-tck_mhz`: the TCK constraint, 10 MHz by default. Set it to the speed
  your cable runs at.
- `-cell`: the instance name, `u_fcapz_ela` by default.
- `-part`: the FPGA part.

## What `fcapz::insert` does

1. It collects every MARK_DEBUG net. Each signal becomes one probe, named
   after its netlist net, for example `u_gen/triple`. A bus must be marked on
   every bit of its range. That range need not start at bit 0. The sample
   clock is the clock of the flip-flops that drive the nets. A net driven by
   anything else (a LUT, a RAM, a DSP) needs `-clock`.
2. It synthesizes `fcapz_ela_xilinx7` out of context, with `SAMPLE_W` equal to
   the number of probe bits.
3. It creates a black-box cell and fills it from that checkpoint with
   `read_checkpoint -cell`.
4. It connects the probe nets to `probe_in` and the clock to `sample_clk`, and
   ties `sample_rst` and `trigger_in` low.
5. It constrains the BSCANE2 TCK. Every path between TCK and the sample clock
   gets `set_max_delay -datapath_only` of one period of the faster clock.
   That keeps the ELA's multi-bit settings and readback bundles timed: each
   one must arrive before the synchronized toggle that tells the other side
   to copy it. `build.tcl` writes those paths to `cdc.rpt`. The sample clock
   must be constrained, or the script warns that the crossings are untimed.
6. It writes a `.prob` file that maps each signal to its bits, so the host
   can name them:

```json
{"format": "fpgacapzero.probes.v1", "core": "ela",
 "probes": [{"name": "count", "width": 8, "lsb": 0},
            {"name": "lfsr", "width": 16, "lsb": 8},
            {"name": "u_gen/triple", "width": 8, "lsb": 24}],
 "sample_clock_hz": 100000000, "sample_width": 32}
```

## Limits of the prototype

- It inserts one ELA, sampling one clock domain. Nets from several clocks
  are refused.
- It supports Xilinx 7-series only.
- It inserts a standalone ELA on one USER chain, which must be free. It
  stops if a BSCANE2 in the netlist already uses that chain. It also stops
  if the checkpoint holds Vivado debug cores whose hub will take the chain
  at `opt_design`. An ILA instantiated as IP in the RTL is not detected.
- It does not add a multi-core manager or an EIO, and it does not support
  the external trigger.
