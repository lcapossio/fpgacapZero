# 04 — RTL integration

> **Goal**: by the end of this chapter you can drop fcapz cores into
> your own design.  You will know which wrapper to instantiate, what
> every parameter does, how `fcapz_version.vh` fits in, and how to
> tie the cores into your existing fabric clock domain.
>
> **Audience**: junior FPGA dev who has written a `module` before
> and knows what `parameter` and `wire` mean, but has never
> instantiated a vendor primitive like BSCANE2 directly.

## The wrappers vs the cores

Every fcapz core ships in two flavors:

| Flavor | Files | Use when |
|---|---|---|
| **Vendor wrapper** | `rtl/fcapz_*_xilinx7.v`, `_xilinxus.v`, `_ecp5.v`, `_intel.v`, `_gowin.v` | **Almost always.** Single instantiation, bundles the TAP primitive + register interface + core internally.  No JTAG knowledge required. |
| **Vendor-agnostic core** | `rtl/fcapz_ela.v`, `fcapz_eio.v`, `fcapz_ejtagaxi.v`, `fcapz_ejtaguart.v` | Only if you already have your own JTAG TAP plumbing and want to wire the core's `tck`/`tdi`/`tdo`/`capture`/`shift`/`update`/`sel` directly.  Advanced use. |

**99% of users want the wrappers.**  This chapter is about wrappers.
The agnostic cores are documented in chapters 05-08 alongside the
features they expose.

## Picking the right wrapper for your FPGA

| Vendor / family | Wrapper suffix | Hardware-validated |
|---|---|---|
| Xilinx Artix-7, Kintex-7, Virtex-7, Spartan-7, Zynq-7000 | `_xilinx7` | ✅ Arty A7-100T |
| Xilinx Kintex / Virtex UltraScale | `_xilinxus` | ❌ implemented as a thin shim over `_xilinx7`, lint-clean, not yet HW-validated |
| Xilinx Artix / Kintex / Virtex / Zynq UltraScale+ | `_xilinxus` | ❌ same as above |
| Lattice ECP5 | `_ecp5` | ❌ implemented in RTL, not yet HW-validated |
| Intel / Altera (Cyclone, Arria, Stratix) | `_intel` | ❌ |
| Gowin GW1N / GW2A | `_gowin` | ❌ |
| Xilinx Versal (XCVM/VC/VP/VE/VH) | **none** | not supported — Versal uses a different TAP primitive |

If your vendor isn't on the list, see [chapter 14](14_transports.md)
"Adding a new transport / vendor wrapper" for the porting guide.

> **Why the UltraScale wrapper is a "thin shim"**: AMD's BSCANE2
> primitive is byte-identical between 7-series, UltraScale, and
> UltraScale+.  The `_xilinxus` files are 33-88 LOC each and
> instantiate the corresponding `_xilinx7` module verbatim.  This
> means any future fix to the 7-series wrapper auto-applies to the
> UltraScale path.  Your `set_property top` and Vivado source-file
> list still get a clean per-vendor entry point.

## The version header (`fcapz_version.vh`)

Every fcapz RTL file starts with:

```verilog
`include "fcapz_version.vh"
```

This is an **auto-generated** Verilog header at
[`../rtl/fcapz_version.vh`](../rtl/fcapz_version.vh).  It exposes
the project version and per-core ASCII identifiers as `\`define`s:

```verilog
`define FCAPZ_VERSION_MAJOR   8'h00
`define FCAPZ_VERSION_MINOR   8'h03
`define FCAPZ_VERSION_PATCH   8'h00
`define FCAPZ_VERSION_STRING  "0.3.0"
`define FCAPZ_ELA_CORE_ID     16'h4C41   // "LA" — Logic Analyzer
`define FCAPZ_EIO_CORE_ID     16'h494F   // "IO" — Embedded I/O
`define FCAPZ_ELA_VERSION_REG {`FCAPZ_VERSION_MAJOR, `FCAPZ_VERSION_MINOR, `FCAPZ_ELA_CORE_ID}
`define FCAPZ_EIO_VERSION_REG {`FCAPZ_VERSION_MAJOR, `FCAPZ_VERSION_MINOR, `FCAPZ_EIO_CORE_ID}
```

The header is **regenerated** from the canonical
[`../VERSION`](../VERSION) file by
[`../tools/sync_version.py`](../tools/sync_version.py).  When you
bump the version you edit `VERSION` and re-run the script; the
header, the Python `fcapz.__version__`, the RTL `VERSION` registers,
and the ELA testbench all stay in lockstep automatically.  CI fails
the build if the header has drifted from `VERSION`.  See
[chapter 16](16_versioning_and_release.md) for the full story.

**You don't need to do anything special** to make the header
visible to your RTL: it lives in `rtl/` next to all the core files,
and any tool that reads them (Vivado `add_files`, iverilog with
`-I rtl`, your synthesis flow) will pick it up.  The reference
[`build_arty.tcl`](../examples/arty_a7/build_arty.tcl) explicitly
adds it as a "Verilog Header" file type and marks it
`is_global_include = true` so every source file in the project sees
it.

## Minimal instantiation: ELA only

The smallest useful design — capture an 8-bit bus into a 1024-sample
buffer, no advanced features:

```verilog
fcapz_ela_xilinx7 #(
    .SAMPLE_W (8),
    .DEPTH    (1024)
) u_ela (
    .sample_clk  (clk_100mhz),
    .sample_rst  (rst),
    .probe_in    (my_8bit_signal),
    // External trigger ports — tie off if not used
    .trigger_in  (1'b0),
    .trigger_out ()
);
```

That's it.  No TAP primitive instantiation, no JTAG plumbing, no
register file declarations.  The wrapper takes care of:

- Instantiating two `BSCANE2` primitives (USER1 for control, USER2
  for burst data readback)
- Instantiating `jtag_reg_iface` (the 49-bit DR register protocol)
- Instantiating `jtag_burst_read` (the 256-bit DR burst engine)
- Instantiating `fcapz_ela` (the actual capture core)
- Wiring everything together

Resource usage: ~1,594 LUTs + 0.5 BRAM on Artix-7 for the baseline
config (8b × 1024).  See [`specs/architecture.md`](specs/architecture.md)
for the full table.

## Adding more cores in the same design

The reference Arty A7 design uses three cores in one bitstream:

```verilog
// 1. ELA on USER1 (control) + USER2 (burst data)
fcapz_ela_xilinx7 #(
    .SAMPLE_W (8),
    .DEPTH    (1024)
) u_ela (
    .sample_clk  (clk_100mhz),
    .sample_rst  (rst),
    .probe_in    (counter[7:0]),
    .trigger_in  (1'b0),
    .trigger_out ()
);

// 2. EIO on USER3
fcapz_eio_xilinx7 #(
    .IN_W  (8),
    .OUT_W (8)
) u_eio (
    .probe_in  (gpio_in),
    .probe_out (gpio_out)
);

// 3. EJTAG-AXI bridge on USER4
fcapz_ejtagaxi_xilinx7 #(
    .ADDR_W     (32),
    .DATA_W     (32),
    .FIFO_DEPTH (16)
) u_axi (
    .axi_clk      (clk_100mhz),
    .axi_rst      (rst),
    // ... 30 AXI signals connected to your AXI slave or interconnect ...
);
```

Each core uses a different USER chain so they don't collide.  The
default chain assignments are:

| Core | Default chain | Default IR (7-series) |
|---|---|---|
| ELA control | USER1 | `0x02` |
| ELA burst data | USER2 | `0x03` |
| EIO | USER3 | `0x22` |
| EJTAG-AXI / EJTAG-UART | USER4 | `0x23` |

If you need different chains (e.g. you have another debug core
already on USER1), every wrapper has `CHAIN` parameters you can
override at instantiation:

```verilog
fcapz_ela_xilinx7 #(
    .SAMPLE_W   (8),
    .DEPTH      (1024),
    .CTRL_CHAIN (3),     // move ELA control to USER3
    .DATA_CHAIN (4)      // move ELA burst data to USER4
) u_ela (
    ...
);
```

If you do this, **also update the host's `ir_table`** to match —
see [chapter 14](14_transports.md).

## ELA wrapper parameter reference

```verilog
module fcapz_ela_xilinx7 #(
    parameter SAMPLE_W     = 8,      // probe width per channel
    parameter DEPTH        = 1024,   // sample buffer depth
    parameter TRIG_STAGES  = 1,      // 1=simple, 2..4=sequencer
    parameter STOR_QUAL    = 0,      // storage qualification 0/1
    parameter INPUT_PIPE   = 0,      // input register stages 0..N
    parameter NUM_CHANNELS = 1,      // number of probe channels for the channel mux
    parameter DECIM_EN     = 0,      // sample decimation 0/1
    parameter EXT_TRIG_EN  = 0,      // external trigger I/O 0/1
    parameter TIMESTAMP_W  = 0,      // 0=off, 32 or 48
    parameter NUM_SEGMENTS = 1,      // number of memory segments
    parameter PROBE_MUX_W  = 0,      // total bus width for runtime probe mux (0=off)
    parameter BURST_W      = 256,    // USER2 burst DR width (don't change)
    parameter CTRL_CHAIN   = 1,      // BSCANE2 USER chain for control
    parameter DATA_CHAIN   = 2       // BSCANE2 USER chain for burst data
) ( ... );
```

| Parameter | Type | Range | Effect |
|---|---|---|---|
| `SAMPLE_W` | int | 1..256 | Width of each probe sample.  Costs FFs proportionally; default 8 is small. |
| `DEPTH` | int | 16..16M, **power of 2** | Buffer depth.  Stored in dual-port BRAM; ~512 LUTs at depth=1024.  Larger means more BRAM. |
| `TRIG_STAGES` | int | 1..4 | Number of trigger sequencer stages.  `1` = single-stage simple trigger; `2..4` = multi-stage state machine.  Each extra stage adds two comparators and ~50 LUTs. |
| `STOR_QUAL` | bit | 0/1 | Storage qualification: filter which samples get stored based on a comparator.  +21 LUTs.  Up to ~10× effective depth on sparse signals. |
| `INPUT_PIPE` | int | 0..N | Pipeline registers between `probe_in` and the comparators.  Use this if your fabric has tight timing on the probe path; each stage adds 1 cycle of latency. |
| `NUM_CHANNELS` | int | 1..256 | Channel mux: lets one ELA observe `N` separate buses, one selected at arm time.  Probe input width becomes `SAMPLE_W * NUM_CHANNELS` bits. |
| `DECIM_EN` | bit | 0/1 | Enables the `--decimation` runtime option.  +24-bit divider.  Free if disabled. |
| `EXT_TRIG_EN` | bit | 0/1 | Enables `trigger_in` / `trigger_out` ports.  Free if disabled. |
| `TIMESTAMP_W` | int | 0, 32, 48 | Per-sample timestamp counter width.  `0` = off (no timestamps in capture results); `32` or `48` enable a parallel timestamp BRAM the same depth as the sample BRAM.  +1 BRAM. |
| `NUM_SEGMENTS` | int | 1..16, **power of 2 dividing DEPTH** | Splits the buffer into N segments and auto-rearms after each segment fills.  Useful for capturing multiple trigger events in one run. |
| `PROBE_MUX_W` | int | 0 or N×SAMPLE_W | Runtime probe mux: connect a wide bus and runtime-select a SAMPLE_W slice via the `PROBE_SEL` register.  `0` disables the feature. |
| `BURST_W` | int | 256 | USER2 burst DR width.  Don't change unless you know exactly what you're doing. |
| `CTRL_CHAIN` | int | 1..4 | BSCANE2 USER chain for the control register interface. |
| `DATA_CHAIN` | int | 1..4 | BSCANE2 USER chain for the burst data readback. |

The minimum-area config (every feature off) is the default if you
omit a parameter.  The reference Arty A7 design uses:

```verilog
fcapz_ela_xilinx7 #(
    .SAMPLE_W     (8),
    .DEPTH        (1024),
    .DECIM_EN     (1),
    .EXT_TRIG_EN  (1),
    .TIMESTAMP_W  (32),
    .NUM_SEGMENTS (4),
    .TRIG_STAGES  (4),
    .STOR_QUAL    (1)
) u_ela ( ... );
```

This is the "everything on" config and what the hardware integration
tests exercise.  See [chapter 05](05_ela_core.md) for what each
feature actually does at runtime.

## EIO wrapper parameter reference

```verilog
module fcapz_eio_xilinx7 #(
    parameter IN_W  = 32,    // input bus width  (fabric → host)
    parameter OUT_W = 32,    // output bus width (host → fabric)
    parameter CHAIN = 3      // BSCANE2 USER chain (default USER3)
) ( ... );
```

| Parameter | Range | Effect |
|---|---|---|
| `IN_W` | 1..N | Width of `probe_in` bus.  Adds N FFs for the 2-FF synchroniser. |
| `OUT_W` | 1..N | Width of `probe_out` bus.  Adds N FFs for the output register. |
| `CHAIN` | 1..4 | Which BSCANE2 USER chain to attach to. |

That's all there is to EIO.  See [chapter 06](06_eio_core.md) for
the runtime API.

## EJTAG-AXI wrapper parameter reference

```verilog
module fcapz_ejtagaxi_xilinx7 #(
    parameter ADDR_W     = 32,
    parameter DATA_W     = 32,
    parameter FIFO_DEPTH = 16,
    parameter TIMEOUT    = 4096,
    parameter CHAIN      = 4
) ( ... );
```

| Parameter | Range | Effect |
|---|---|---|
| `ADDR_W` | 32, 64 | AXI address width.  64 is supported but not hardware-validated. |
| `DATA_W` | 32 | AXI data width.  Only 32 is supported today. |
| `FIFO_DEPTH` | 1..256, **power of 2** | Async FIFO depth for burst reads.  Limits the maximum burst length the host can request — the host caches this from `FEATURES[23:16]` and rejects oversized requests at the API boundary.  See [chapter 07](07_ejtag_axi_bridge.md). |
| `TIMEOUT` | int | AXI handshake timeout in `axi_clk` cycles.  Applies to `wready`/`bvalid`/`arready`/`rvalid` waits, **not** between burst beats. |
| `CHAIN` | 1..4 | BSCANE2 USER chain. |

## EJTAG-UART wrapper parameter reference

```verilog
module fcapz_ejtaguart_xilinx7 #(
    parameter JTAG_CHAIN    = 4,
    parameter CLK_HZ        = 100_000_000,
    parameter BAUD_RATE     = 115200,
    parameter TX_FIFO_DEPTH = 256,
    parameter RX_FIFO_DEPTH = 256,
    parameter PARITY        = 0
) ( ... );
```

| Parameter | Range | Effect |
|---|---|---|
| `JTAG_CHAIN` | 1..4 | BSCANE2 USER chain. |
| `CLK_HZ` | int | Frequency of `uart_clk`.  Used to compute the baud divider. |
| `BAUD_RATE` | int | Target UART baud rate.  Common values 9600 / 115200 / 921600. |
| `TX_FIFO_DEPTH` | power of 2 | TX async FIFO depth in bytes. |
| `RX_FIFO_DEPTH` | power of 2 | RX async FIFO depth in bytes. |
| `PARITY` | 0/1/2 | 0=none, 1=odd, 2=even. |

## Common pitfalls

### Probe width must match SAMPLE_W

```verilog
fcapz_ela_xilinx7 #(.SAMPLE_W(16), .DEPTH(1024)) u_ela (
    .sample_clk (clk),
    .sample_rst (rst),
    .probe_in   (my_8bit_signal),   // ❌ width mismatch!
    ...
);
```

Vivado will tell you `Width mismatch ... probe_in expected 16 bits, got 8`.
Either widen your probe (`{8'h0, my_8bit_signal}`) or set
`SAMPLE_W=8`.

### DEPTH must be a power of 2

```verilog
fcapz_ela_xilinx7 #(.SAMPLE_W(8), .DEPTH(1000)) u_ela ( ... );
```

Synthesis fails with `DEPTH_must_be_power_of_2 _depth_check_FAILED`
— that's a deliberate compile-time trap inside the core.  The next
power of 2 (1024 here) is what you want.  See
[chapter 17](17_troubleshooting.md) for the full list of
parameter-validation traps.

### NUM_SEGMENTS must divide DEPTH

```verilog
fcapz_ela_xilinx7 #(.DEPTH(1024), .NUM_SEGMENTS(3)) u_ela ( ... );
```

`1024 / 3` is not an integer.  Pick `NUM_SEGMENTS = 1, 2, 4, 8, ...`
that divides `DEPTH` evenly.  Same compile-time trap as DEPTH.

### TIMESTAMP_W must be 0, 32, or 48

```verilog
fcapz_ela_xilinx7 #(.TIMESTAMP_W(16)) u_ela ( ... );
```

Only `0` (off), `32`, or `48` are supported.  `64` doesn't fit in
the burst DR; arbitrary widths aren't supported.

### Forgetting to add `fcapz_version.vh` in your build flow

If you `add_files rtl/fcapz_ela.v` without also adding `fcapz_version.vh`,
Vivado synthesis dies with:

```
ERROR: [Synth 8-403] could not find file fcapz_version.vh
```

The fix is at the top of [`build_arty.tcl`](../examples/arty_a7/build_arty.tcl) —
copy that pattern.  iverilog needs `-I rtl` on the command line; the
project's [`sim/run_sim.py`](../sim/run_sim.py) already does this.

## Vendor wrapper differences

The wrappers all have **identical port lists** for a given core.  The
*only* difference is which TAP primitive lives inside.  Switching
vendors is a one-line change to your top-level:

```diff
-fcapz_ela_xilinx7 #(.SAMPLE_W(8), .DEPTH(1024)) u_ela (
+fcapz_ela_xilinxus #(.SAMPLE_W(8), .DEPTH(1024)) u_ela (
     .sample_clk (clk),
     .sample_rst (rst),
     .probe_in   (signals),
     .trigger_in (1'b0),
     .trigger_out()
 );
```

The host stack does not need to change — the same
`Analyzer.connect()` call works against either bitstream.  The only
host-side knob you may need to flip is the `ir_table` preset, since
UltraScale uses different IR opcodes than 7-series:

```python
from fcapz import XilinxHwServerTransport
transport = XilinxHwServerTransport(
    port=3121,
    fpga_name="xcku040",
    ir_table=XilinxHwServerTransport.IR_TABLE_US,   # USER1=0x24, ...
)
```

See [chapter 14](14_transports.md).

## What's next

- [Chapter 05 — ELA core](05_ela_core.md): the deep dive on every
  ELA feature, what each parameter does at runtime, and how to use
  them from the host.
- [Chapter 06 — EIO core](06_eio_core.md): EIO read/write,
  clock domain handling, host API.
- [Chapter 07 — EJTAG-AXI bridge](07_ejtag_axi_bridge.md): the AXI4
  bridge architecture and host API.
- [Chapter 08 — EJTAG-UART bridge](08_ejtag_uart_bridge.md): the UART
  bridge architecture and host API.
