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
| Microchip PolarFire / PolarFire SoC / SmartFusion2 / IGLOO2 | `_polarfire` | ❌ implemented in RTL, not yet HW-validated |
| Xilinx Versal (XCVM/VC/VP/VE/VH) | **none** | not supported — Versal uses a different TAP primitive |

If your vendor isn't on the list, see [chapter 14](14_transports.md)
"Adding a new transport / vendor wrapper" for the porting guide.

### Validation Levels

The ELA core is shared across vendors, so the behavioral simulation suite
exercises the same feature gates used by every wrapper. `python sim/run_sim.py`
includes the ELA configuration matrix for small/scalable builds:
`DUAL_COMPARE=0`, `USER1_DATA_EN=0`, disabled feature registers, and
`REL_COMPARE=1` with `INPUT_PIPE=1`.

Wrapper coverage is currently lighter than core coverage. The lint target
elaborates the vendor wrappers and catches parameter/port drift, while the
Arty A7 hardware test validates the Xilinx 7-series reference bitstream.
ECP5, Intel, Gowin, PolarFire, and UltraScale wrappers should be treated as
RTL-implemented and lint-clean until a board-level smoke test is added for
that family.

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

- Instantiating one or two `BSCANE2` primitives. The default uses USER1
  for both control and fast burst readback; `SINGLE_CHAIN_BURST=0`
  enables the legacy separate DATA_CHAIN burst path.
- Instantiating `jtag_reg_iface` (the 49-bit DR register protocol) or
  `jtag_pipe_iface` (mixed 49-bit register / 256-bit burst packets)
- Instantiating `jtag_burst_read` for legacy two-chain burst builds
- Instantiating `fcapz_ela` (the actual capture core)
- Wiring everything together

Resource usage: ~912 slice LUTs + 0.5 BRAM on xc7a100t (Vivado 2025.2
synthesis) for an 8b x 1024 single-comparator, single-chain fast-readout
configuration.  Simple USER1 register-readout builds are ~596 LUTs.  See
[`specs/architecture.md`](specs/architecture.md) and the
[README resource table](../README.md#resource-usage) for sequencer,
storage qualification, width/depth scaling, and the full `arty_a7_top`
reference.

## LiteX integration

LiteX designs can instantiate the same JTAG-accessible ELA wrapper through
the optional Python helper in `fcapz.litex`.  Install LiteX in your SoC
environment, then add the module to your design:

```python
from migen import ClockSignal, ResetSignal
from fcapz.litex import FcapzELA

soc.submodules.ela = FcapzELA(
    platform,
    vendor="xilinx7",
    sample_clk=ClockSignal("sys"),
    sample_rst=ResetSignal("sys"),
    probes={
        "bus_we": bus.we,
        "bus_adr": bus.adr,
        "bus_dat_w": bus.dat_w,
        "fsm_state": fsm_state,
    },
    depth=1024,
)

soc.ela.write_probe_file("build/ela.prob", sample_clock_hz=int(sys_clk_freq))
```

`probes` are packed with normal Migen `Cat` ordering: the first named signal
occupies the low bits of `probe_in`, and `FcapzELA.probe_fields` records each
field's name, width, and bit offset for capture metadata.  The helper also
adds the required RTL files to the LiteX platform, including the generated
`fcapz_version.vh` header and the selected vendor TAP wrapper.

The generated `.prob` sidecar can be passed directly to the host:

```bash
fcapz capture --probe-file build/ela.prob --format vcd --out capture.vcd
```

This first integration path keeps capture control on the existing JTAG
transport.  It does not consume LiteX CSRs or Wishbone address space.  Use
the normal `fcapz` CLI, GUI, or Python API against the programmed bitstream.
The high-level `FcapzELA` wrapper currently targets the Xilinx 7-series and
UltraScale-style ELA wrappers; lower-level source manifests for the other RTL
wrappers are available through `ela_rtl_sources()` for custom integration.

## Adding more cores in the same design

The reference Arty A7 design uses three cores in one bitstream:

```verilog
// 1. ELA on USER1 (control + burst data by default)
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

The checked-in [Arty top](../examples/arty_a7/arty_a7_top.v) enables more
ELA options (`DECIM_EN`, `EXT_TRIG_EN`, `TIMESTAMP_W`, `NUM_SEGMENTS`) and
ties `trigger_in` to an EIO-controlled fabric signal for hardware tests.
In that reference top:

- `probe_out[4]` is a manual external-trigger bit
- `probe_out[5]` requests an early one-shot trigger 2 sample clocks
  after the ELA enters `ARMED`
- `probe_out[6]` requests a late trigger source beginning 8 sample
  clocks after the ELA enters `ARMED`

That deterministic trigger-test plumbing is specific to the Arty
reference design, not a requirement of the generic wrappers.

Each core uses a different USER chain so they don't collide.  The
default chain assignments are:

| Core | Default chain | Default IR (7-series) |
|---|---|---|
| ELA control + default burst data | USER1 | `0x02` |
| ELA legacy burst data (`SINGLE_CHAIN_BURST=0`) | USER2 | `0x03` |
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
    .SINGLE_CHAIN_BURST(0), // use a separate burst-data chain
    .DATA_CHAIN (4)         // move ELA legacy burst data to USER4
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
    parameter STARTUP_ARM  = 0,      // 1=come up armed after reset/configuration
    parameter DEFAULT_TRIG_EXT = 0,  // reset/default external trigger mode
    parameter BURST_W      = 256,    // burst DR width (don't change)
    parameter BURST_EN     = 1,      // 0=omit legacy DATA_CHAIN burst path
    parameter SINGLE_CHAIN_BURST = 1, // 1=fast burst readout on CTRL_CHAIN
    parameter CTRL_CHAIN   = 1,      // BSCANE2 USER chain for control
    parameter DATA_CHAIN   = 2,      // BSCANE2 USER chain for burst data
    parameter REL_COMPARE  = 0,      // 1=enable <, >, <=, >= trigger modes
    parameter DUAL_COMPARE = 1,      // 0=A-only compare, 1=enable comparator B
    parameter USER1_DATA_EN = 1      // 0=disable slow USER1 DATA window readback
) ( ... );
```

| Parameter | Type | Range | Effect |
|---|---|---|---|
| `SAMPLE_W` | int | 1..256 | Width of each probe sample.  Costs FFs proportionally; default 8 is small. |
| `DEPTH` | int | 16..16M, **power of 2** | Buffer depth.  Stored in dual-port BRAM; ~512 LUTs at depth=1024.  Larger means more BRAM. |
| `TRIG_STAGES` | int | 1..4 | Number of trigger sequencer stages.  `1` = single-stage simple trigger; `2..4` = multi-stage state machine.  Each extra stage adds sequencer state and comparator configuration. |
| `STOR_QUAL` | bit | 0/1 | Storage qualification: filter which samples get stored based on a comparator.  +21 LUTs.  Up to ~10× effective depth on sparse signals. |
| `INPUT_PIPE` | int | 0..N | Pipeline registers between `probe_in` and the comparators.  Use this if your fabric has tight timing on the probe path; each stage adds 1 cycle of latency.  With `INPUT_PIPE>=1`, the ELA also registers the BRAM write command and internally enables a one-cycle `COMPARE_PIPE`, so wide relational compares do not sit on the capture-control critical path. |
| `NUM_CHANNELS` | int | 1..256 | Channel mux: lets one ELA observe `N` separate buses, one selected at arm time.  Probe input width becomes `SAMPLE_W * NUM_CHANNELS` bits. |
| `DECIM_EN` | bit | 0/1 | Enables the `--decimation` runtime option.  +24-bit divider.  Free if disabled. |
| `EXT_TRIG_EN` | bit | 0/1 | Enables `trigger_in` / `trigger_out` ports.  Free if disabled. |
| `TIMESTAMP_W` | int | 0, 32, 48 | Per-sample timestamp counter width.  `0` = off (no timestamps in capture results); `32` or `48` enable a parallel timestamp BRAM the same depth as the sample BRAM.  +1 BRAM.  The wrapper propagates `TIMESTAMP_W` into the burst read engine so it knows how many timestamps fit per 256-bit scan and can serve timestamp bursts when `BURST_PTR[31]=1`. |
| `NUM_SEGMENTS` | int | 1..16, **power of 2 dividing DEPTH** | Splits the buffer into N segments and auto-rearms after each segment fills.  Useful for capturing multiple trigger events in one run. |
| `PROBE_MUX_W` | int | 0 or N×SAMPLE_W | Runtime probe mux: connect a wide bus and runtime-select a SAMPLE_W slice via the `PROBE_SEL` register.  `0` disables the feature. |
| `STARTUP_ARM` | bit | 0/1 | Power-up default for the `STARTUP_ARM` register. When `1`, the core leaves reset already armed, which is handy for captures that need to begin immediately after configuration. |
| `DEFAULT_TRIG_EXT` | int | 0..3 | Power-up/reset default for `TRIG_EXT`. Useful with `STARTUP_ARM=1` when you want the bitstream to come up armed but wait for an external trigger condition instead of immediately matching the default internal comparator. |
| `REL_COMPARE` | bit | 0/1 | Enables relational trigger modes `<`, `>`, `<=`, and `>=`. Default `0` keeps the comparator path smaller and faster; EQ/NEQ/rising/falling/changed remain available. For high-frequency `REL_COMPARE=1` builds, use `INPUT_PIPE>=1`; that automatically registers compare hits for timing at the cost of one additional sample-clock decision latency. |
| `DUAL_COMPARE` | bit | 0/1 | Enables comparator B plus B-only/AND/OR trigger combinations. Default `1` preserves the full trigger sequencer. Set `0` for a smaller single-comparator ELA build; the host reports `has_dual_compare=False` and rejects B-combine sequences. |
| `USER1_DATA_EN` | bit | 0/1 | Enables the slow USER1 `DATA`/timestamp readback window. Default `1` preserves compatibility and supports fallback reads. Set `0` in minimal Xilinx builds that rely on fast burst readout to remove the sample-clock USER1 data CDC and part of the readback mux. |
| `BURST_W` | int | 256 | Burst DR width.  Don't change unless you know exactly what you're doing. |
| `BURST_EN` | bit | 0/1 | Xilinx wrapper option to instantiate the legacy DATA_CHAIN burst read engine when `SINGLE_CHAIN_BURST=0`. Default `1` keeps that compatibility path available only when selected. |
| `SINGLE_CHAIN_BURST` | bit | 0/1 | Xilinx wrapper option to keep fast 256-bit burst readout on `CTRL_CHAIN` instead of instantiating a second `BSCANE2`. Default `1`: one USER chain carries both 49-bit register packets and 256-bit data packets. Set `0` only for legacy two-chain builds, and construct the host transport with `single_chain_burst=False`. |
| `CTRL_CHAIN` | int | 1..4 | BSCANE2 USER chain for the control register interface. |
| `DATA_CHAIN` | int | 1..4 | BSCANE2 USER chain for the burst data readback. |
| `EIO_EN` | bit | 0/1 | When `1`, the ELA wrapper also instantiates an EIO core and muxes it onto `CTRL_CHAIN` via an address decoder — ELA registers live at `0x0000..0x7FFF`, EIO registers at `0x8000..0xFFFF`.  Lets you use both cores on a single USER chain when you want to conserve BSCAN primitives or share a chain for deployment reasons.  The standalone `fcapz_eio_xilinx7` / `_xilinxus` wrappers cannot coexist with this — pick one. |
| `EIO_IN_W` | int | 1..N | EIO input bus width when `EIO_EN=1`. |
| `EIO_OUT_W` | int | 1..N | EIO output bus width when `EIO_EN=1`. |

**Migration note:** older Xilinx bitstreams may have been built with
`SINGLE_CHAIN_BURST=0`, where 256-bit burst scans live on `DATA_CHAIN`.
The current host default expects single-chain burst on `CTRL_CHAIN`. If a
legacy bitstream falls back to slow USER1 reads or logs a single-chain burst
warning, use the CLI `--two-chain-burst` option or construct
`XilinxHwServerTransport(single_chain_burst=False)`.

**Startup defaults:** `STARTUP_ARM` and `DEFAULT_TRIG_EXT` rely on the FPGA
and synthesis flow preserving register initial values at configuration time
(for example, Xilinx GSR/INIT behavior). If a target family or flow does not
guarantee those initial values, configure the registers from the host after
programming instead of relying on power-up auto-arm behavior.

The default config is intentionally small and single-chain, while still
keeping compatibility features such as comparator B and USER1 fallback
readout enabled. The reference Arty A7 design uses:

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

### Combining ELA + EIO on a single USER chain (`EIO_EN=1`)

Two cases to use this mode:

1. **Resource-constrained parts** with only one spare USER chain (ECP5
   designs with heavy logic, small Lattice / Gowin parts, etc.).
2. **Zynq UltraScale+ MPSoC (xck26 / xczu*)** — this is the **required**
   path on MPSoC, not an optional one.  The PL TAP on these parts
   exposes only USER1 as a reachable chain through xsdb/hw_server at
   the device-level target (USER2..USER4 either alias to USER1 or put
   the TAP in BYPASS — see [chapter 14 "Zynq UltraScale+ MPSoC — known
   limitation: USER1 only"](14_transports.md#zynq-ultrascale-mpsoc--known-limitation-user1-only)).
   Set `EIO_EN=1` on the ELA wrapper, drop the standalone
   `fcapz_eio_xilinxus` instance from your top level, and EIO will
   ride-along on USER1.

The wrapper adds a
[`fcapz_regbus_mux`](../rtl/fcapz_regbus_mux.v) on the USER1 49-bit
register bus that splits the 16-bit address space:

| Host-side address | Routed to |
|---|---|
| `0x0000..0x7FFF` | ELA control (VERSION, CTRL, trigger regs, …) |
| `0x8000..0xFFFF` | EIO (bit 15 stripped, EIO sees `0x0000..0x7FFF`) |

```verilog
fcapz_ela_xilinxus #(
    .SAMPLE_W(32), .DEPTH(2048), .NUM_CHANNELS(2),
    .TIMESTAMP_W(32),
    .EIO_EN(1), .EIO_IN_W(1), .EIO_OUT_W(1)
) u_ela (
    .sample_clk   (sys_clk),
    .sample_rst   (~aresetn),
    .probe_in     (ela_channels),
    .trigger_in   (1'b0),
    .trigger_out  (),
    .eio_probe_in (1'b0),
    .eio_probe_out(cam_power)     // e.g. camera power-enable GPIO
);
```

Host-side, pass `base_addr=0x8000` when constructing the EIO
controller so every register access gets bit 15 OR'd in:

```python
from fcapz import EioController
eio = EioController(transport, chain=1, base_addr=0x8000)
eio.connect()    # reads VERSION at host address 0x8000 → mux routes to EIO 0x0000
eio.write_outputs(0x1)
```

**Limits:**
- The ELA burst readback still uses USER2 (256-bit DR) — that stays on
  its own chain; only the 49-bit register path is shared.
- You cannot also instantiate a standalone `fcapz_eio_xilinx7` /
  `_xilinxus` elsewhere in the same design (two BSCANE2s on the same
  USER chain).
- A future third core on the same chain (EJTAG-AXI/UART) would need a
  wider address mux or a hierarchical `fcapz_regbus_mux`.

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
    parameter CMD_FIFO_DEPTH  = FIFO_DEPTH * 2,
    parameter RESP_FIFO_DEPTH = FIFO_DEPTH * 2,
    parameter TIMEOUT    = 4096,
    parameter DEBUG_EN   = 0,
    parameter CMD_FIFO_MEMORY_TYPE   = "auto",
    parameter RESP_FIFO_MEMORY_TYPE  = "auto",
    parameter BURST_FIFO_MEMORY_TYPE = "auto",
    parameter CHAIN      = 4
) ( ... );
```

| Parameter | Range | Effect |
|---|---|---|
| `ADDR_W` | 32, 64 | AXI address width.  64 is supported but not hardware-validated. |
| `DATA_W` | 32 | AXI data width.  Only 32 is supported today. |
| `FIFO_DEPTH` | 1..256, **power of 2** | Async FIFO depth for burst reads.  Limits the maximum burst length the host can request — the host caches this from `FEATURES[23:16]` and rejects oversized requests at the API boundary.  See [chapter 07](07_ejtag_axi_bridge.md). |
| `CMD_FIFO_DEPTH` | power of 2 | TCK-to-AXI command queue depth. The wrapper default follows the core (`2*FIFO_DEPTH`) for compatibility; Xilinx XPM FIFO builds require at least 16. |
| `RESP_FIFO_DEPTH` | power of 2 | AXI-to-TCK response queue depth. The wrapper default follows the core (`2*FIFO_DEPTH`) for compatibility; Xilinx XPM FIFO builds require at least 16. |
| `TIMEOUT` | int | AXI handshake timeout in `axi_clk` cycles.  Applies to `wready`/`bvalid`/`arready`/`rvalid` waits, **not** between burst beats. |
| `DEBUG_EN` | 0, 1 | Enables the 256-bit debug buses and debug CONFIG capture records. Defaults off to let synthesis prune debug-only storage and counters. |
| `CMD_FIFO_MEMORY_TYPE` | `"auto"`, `"block"`, `"distributed"` | Xilinx XPM storage selector for the command queue. Ignored by the portable behavioral FIFO. |
| `RESP_FIFO_MEMORY_TYPE` | `"auto"`, `"block"`, `"distributed"` | Xilinx XPM storage selector for the response queue. Ignored by the portable behavioral FIFO. |
| `BURST_FIFO_MEMORY_TYPE` | `"auto"`, `"block"`, `"distributed"` | Xilinx XPM storage selector for the burst read FIFO. Ignored by the portable behavioral FIFO. |
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
