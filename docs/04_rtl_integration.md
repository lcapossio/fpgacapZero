# 04 — RTL integration

> [!NOTE]
> **Goal**: by the end of this chapter you can drop fcapz cores into
> your own design.  You will know which wrapper to instantiate, what
> every parameter does, how `fcapz_version.vh` fits in, and how to
> tie the cores into your existing fabric clock domain.

## The wrappers vs the cores

Every fcapz core ships in two flavors:

| Flavor | Files | Use when |
|---|---|---|
| **Vendor wrapper** | `rtl/fcapz_*_xilinx7.v`, `_xilinxus.v`, `_ecp5.v`, `_intel.v`, `_gowin.v`, `_polarfire.v`, `_efinix.v` (not every core exists for every vendor; Efinix has the ELA and the core-manager hub) | **Almost always.** Single instantiation, bundles the TAP primitive + register interface + core internally.  No JTAG knowledge required. |
| **Vendor-agnostic core** | `rtl/fcapz_ela.v`, `fcapz_eio.v`, `fcapz_ejtagaxi.v`, `fcapz_ejtaguart.v` | Only if you already have your own JTAG TAP plumbing.  Advanced use.  `fcapz_ejtagaxi` and `fcapz_ejtaguart` take the TAP signals (`tck`/`tdi`/`tdo`/`capture`/`shift`/`update`/`sel`) directly.  `fcapz_ela` and `fcapz_eio` take a decoded register bus (`jtag_clk`, `jtag_wr_en`, `jtag_addr`, `jtag_wdata`, `jtag_rdata`, ...); put [`jtag_reg_iface`](../rtl/jtag_reg_iface.v) (49-bit register DR) or [`jtag_pipe_iface`](../rtl/jtag_pipe_iface.v) (register DR plus single-chain 256-bit burst) between your TAP and the core, as the wrappers do. |

**99% of users want the wrappers.**  This chapter is about wrappers.
The agnostic cores are documented in chapters 05-08 alongside the
features they expose.

## Picking the right wrapper for your FPGA

| Vendor / family | Wrapper suffix |
|---|---|
| AMD/Xilinx Artix-7, Kintex-7, Virtex-7, Spartan-7, Zynq-7000 | `_xilinx7` |
| AMD/Xilinx Kintex / Virtex UltraScale | `_xilinxus` |
| AMD/Xilinx Zynq UltraScale+ MPSoC | `_xilinxus` |
| AMD/Xilinx Artix / Kintex / Virtex UltraScale+ (standalone) | `_xilinxus` |
| Lattice ECP5 | `_ecp5` |
| Intel / Altera (Cyclone, Arria, Stratix, Agilex) | `_intel` |
| Gowin GW1N / GW2A | `_gowin` |
| Microchip PolarFire / PolarFire SoC | `_polarfire` |
| Microchip SmartFusion2 / IGLOO2 | `_polarfire` |
| Efinix Trion / Titanium | `_efinix` |
| Any FPGA without fabric JTAG | `fcapz_ela_uart` (UART TAP bridge, see [chapter 14](14_transports.md)) |
| AMD/Xilinx Versal (XCVM/VC/VP/VE/VH) | **none** (not supported: Versal uses a different TAP primitive) |

Which boards each wrapper has been validated on is in the
[vendor support matrix](01_overview.md#vendor-support-matrix).  If your
vendor isn't on the list, see [chapter 14](14_transports.md) "Adding a new
transport / vendor wrapper" for the porting guide.

### Validation Levels

The ELA core is shared across vendors, so the behavioral simulation suite
exercises the same feature gates used by every wrapper. `python sim/run_sim.py`
includes the ELA configuration matrix for small/scalable builds:
`DUAL_COMPARE=0`, `USER1_DATA_EN=0`, disabled feature registers, and
`REL_COMPARE=1` with `INPUT_PIPE=1`.

Wrapper coverage is currently lighter than core coverage. The lint target
elaborates the vendor wrappers and catches parameter/port drift, while the
Arty A7 hardware test validates the AMD/Xilinx 7-series reference bitstream and
the BRS-100 smoke/stress path validates the Gowin wrapper. The DE25-Nano
test validates the Intel wrapper, and the PolarFire SoC Discovery Kit test
validates the PolarFire wrapper. The Kria KV260 test
([`examples/kv260`](../examples/kv260/)) validates Zynq UltraScale+ MPSoC: the
`_xilinxus` JTAG-UART and AXI bridge, and the `_xilinx7` multi-core manager
(4-stage sequencer, storage qualification, relational compares) and AXI
monitor, all on `xck26` over hw_server's `-register` mode. For the
remaining families (ECP5, standalone UltraScale / UltraScale+) see the
[vendor support matrix](01_overview.md#vendor-support-matrix); a family with
no board result there is RTL-implemented and lint-clean only.

> [!NOTE]
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
`define FCAPZ_VERSION_MINOR   8'h05
`define FCAPZ_VERSION_PATCH   8'h00
`define FCAPZ_VERSION_STRING  "0.5.0"
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

**Your build flow must make the header visible** to the RTL; don't
rely on the tool finding it on its own.  In Vivado, add `rtl/fcapz_version.vh` to the project with the other
sources, set its file type to "Verilog Header" and mark it
`is_global_include = true` so every source file sees it; the reference
[`build_arty_vex.tcl`](../examples/arty_a7/build_arty_vex.tcl) does exactly
this.  For iverilog, pass `-I rtl`.  See
[Forgetting to add `fcapz_version.vh`](#forgetting-to-add-fcapz_versionvh-in-your-build-flow)
for the error you get otherwise.

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

The wrapper does not pull in its submodules by itself.  For this example,
add these files from `rtl/` to your Vivado project (the paths are relative
to the repository root):

```tcl
add_files [list \
    rtl/fcapz_version.vh \
    rtl/fcapz_ela_xilinx7.v \
    rtl/jtag_tap/jtag_tap_xilinx7.v \
    rtl/reset_sync.v \
    rtl/jtag_pipe_iface.v \
    rtl/jtag_reg_iface.v \
    rtl/jtag_burst_read.v \
    rtl/fcapz_regbus_mux.v \
    rtl/fcapz_eio.v \
    rtl/fcapz_ela.v \
    rtl/trig_compare.v \
    rtl/dpram.v \
]
set_property file_type "Verilog Header" [get_files rtl/fcapz_version.vh]
set_property is_global_include true     [get_files rtl/fcapz_version.vh]
```

`jtag_reg_iface`, `jtag_burst_read`, `fcapz_regbus_mux` and `fcapz_eio` are
only instantiated for `SINGLE_CHAIN_BURST=0` or `EIO_EN=1`; keeping them in the
list lets you change those parameters without editing the file list, and the
unused ones cost nothing.  `fcapz_ela_xilinxus` needs the same list plus
`fcapz_ela_xilinxus.v`.  The LiteX helper's `ela_rtl_sources()` returns a
superset of this list (it adds the `fcapz_debug_multi_*` hub files) for each
vendor.

Resource usage: ~912 slice LUTs + 0.5 BRAM on xc7a100t (Vivado 2025.2
synthesis) for an 8b x 1024 single-comparator, single-chain fast-readout
configuration.  Simple USER1 register-readout builds are ~596 LUTs.  See
[`specs/architecture.md`](specs/architecture.md) for the full table —
sequencer, storage qualification, width/depth scaling, and the
`arty_a7_top` reference build.

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
The high-level `FcapzELA` wrapper currently targets the AMD/Xilinx 7-series and
UltraScale-style ELA wrappers; lower-level source manifests for the other RTL
wrappers are available through `ela_rtl_sources()` for custom integration.

## Adding more cores in the same design

The reference Arty A7 design uses one USER1 debug manager plus AXI on USER4:

```verilog
// 1. Managed USER1 debug chain: ELA0, ELA1, EIO0, EIO1.
fcapz_debug_multi_xilinx7 #(
    .NUM_ELAS(2),
    .EIO_EN(1),
    .NUM_EIOS(2),
    .SAMPLE_W(8),
    .DEPTH(1024),
    .EIO_IN_W(8),
    .EIO_OUT_W(8)
) u_debug (
    .ela_sample_clk({clk_130mhz, clk_150mhz}),
    .ela_sample_rst({rst_130mhz, rst_150mhz}),
    .ela_probe_in({counter_130 ^ 8'hA5, counter_150}),
    .ela_trigger_in(2'b00),
    .ela_trigger_out(),
    .ela_armed_out(),
    .eio_probe_in({eio1_in, eio0_in}),
    .eio_probe_out({eio1_out, eio0_out})
);

// 2. EJTAG-AXI bridge on USER4
fcapz_ejtagaxi_xilinx7 #(
    .ADDR_W     (32),
    .DATA_W     (32),
    .FIFO_DEPTH (16)
) u_axi (
    .axi_clk      (clk_150mhz),
    .axi_rst      (rst_150mhz),
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
    .CTRL_CHAIN (2)      // ELA control + single-chain burst on USER2
) u_ela (
    ...
);
```

Then point the host at that chain: `fcapz --chain 2 capture ...` on the CLI,
or `Analyzer(transport, chain=2)` from Python.  The `ir_table` does not need
to change: it maps every USER chain number to its IR opcode, so the
[preset](14_transports.md#ir-table-presets) for your part already covers
USER1..USER4.  hw_server's named-register mode (`use_register_ir=True`)
ignores `ir_table` altogether and selects `user<N>` directly.

Moving the legacy two-chain burst (`SINGLE_CHAIN_BURST=0`) is more limited:
`XilinxHwServerTransport` always issues those bursts on USER2, so keep
`DATA_CHAIN=2` for hw_server.  `OpenOcdTransport` and the TAP-bridge
transports take a `burst_data_chain=` argument for a different chain.  See
[chapter 14](14_transports.md).

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
    parameter USER1_DATA_EN = 1,     // 0=disable slow USER1 DATA window readback
    parameter RLE_W        = 0       // 0=off, 1..16=run-length capture count width
) ( ... );
```

| Parameter | Type | Range | Effect |
|---|---|---|---|
| `SAMPLE_W` | int | 1..256 | Width of each probe sample.  Costs FFs proportionally; default 8 is small. |
| `DEPTH` | int | 16..16M, **power of 2** | Buffer depth.  Stored in dual-port BRAM; ~512 LUTs at depth=1024.  Larger means more BRAM. |
| `TRIG_STAGES` | int | 1..4 | Number of trigger sequencer stages.  `1` = single-stage simple trigger; `2..4` = multi-stage state machine.  Each extra stage adds sequencer state and comparator configuration. |
| `STOR_QUAL` | bit | 0/1 | Storage qualification: filter which samples get stored based on a comparator.  +21 LUTs.  Up to ~10× effective depth on sparse signals. |
| `INPUT_PIPE` | int | 0..N | Pipeline registers between `probe_in` and the comparators.  Use this if your fabric has tight timing on the probe path; each stage adds 1 cycle of latency.  With `INPUT_PIPE>=1`, the ELA also registers the BRAM write command and internally enables a one-cycle `COMPARE_PIPE`, so wide relational compares do not sit on the capture-control critical path. With `EXT_TRIG_EN=1`, `INPUT_PIPE=0` is built as `1` so `trigger_in` (2-FF synchronized) lines up with the probe. |
| `NUM_CHANNELS` | int | 1..256 | Channel mux: lets one ELA observe `N` separate buses, one selected at arm time.  Probe input width becomes `SAMPLE_W * NUM_CHANNELS` bits. |
| `DECIM_EN` | bit | 0/1 | Enables the `--decimation` runtime option.  +24-bit divider.  Free if disabled. |
| `EXT_TRIG_EN` | bit | 0/1 | Enables `trigger_in` / `trigger_out` ports.  Free if disabled. |
| `TIMESTAMP_W` | int | 0, 32, 48 | Per-sample timestamp counter width.  `0` = off (no timestamps in capture results); `32` or `48` enable a parallel timestamp BRAM the same depth as the sample BRAM.  +1 BRAM.  The wrapper propagates `TIMESTAMP_W` into the burst read engine so it knows how many timestamps fit per 256-bit scan and can serve timestamp bursts when `BURST_PTR[31]=1`. |
| `RLE_W` | int | 0, 1..16 | Run-length capture: a parallel count RAM (`DEPTH x RLE_W`) lets one buffer entry hold a sample and how many clocks it repeated, up to `2^RLE_W`. `0` (default) builds none of it. With timestamps, `RLE_W` must not exceed `TIMESTAMP_W`; the counts share the timestamp burst lane. The post-trigger clock limit adds about 5 x `min(32, clog2(DEPTH+1) + RLE_W)` flip-flops, plus 3 x `NUM_SEGMENTS` x `clog2(DEPTH+1)` with segments. See [Run-length capture](05_ela_core.md#run-length-capture). |
| `NUM_SEGMENTS` | int | 1..16, **power of 2 dividing DEPTH** | Splits the buffer into N segments and auto-rearms after each segment fills.  Useful for capturing multiple trigger events in one run. |
| `PROBE_MUX_W` | int | 0 or N×SAMPLE_W | Runtime probe mux: connect a wide bus and runtime-select a SAMPLE_W slice via the `PROBE_SEL` register.  `0` disables the feature. |
| `STARTUP_ARM` | bit | 0/1 | Power-up default for the `STARTUP_ARM` register. When `1`, the core leaves reset already armed, which is handy for captures that need to begin immediately after configuration. |
| `DEFAULT_TRIG_EXT` | int | 0..3 | Power-up/reset default for `TRIG_EXT`. Useful with `STARTUP_ARM=1` when you want the bitstream to come up armed but wait for an external trigger condition instead of immediately matching the default internal comparator. |
| `REL_COMPARE` | bit | 0/1 | Enables relational trigger modes `<`, `>`, `<=`, and `>=`. Default `0` keeps the comparator path smaller and faster; EQ/NEQ/rising/falling/changed remain available. For high-frequency `REL_COMPARE=1` builds, use `INPUT_PIPE>=1`; that automatically registers compare hits for timing at the cost of one additional sample-clock decision latency. |
| `DUAL_COMPARE` | bit | 0/1 | Enables comparator B plus B-only/AND/OR trigger combinations. Default `1` preserves the full trigger sequencer. Set `0` for a smaller single-comparator ELA build; the host reports `has_dual_compare=False` and rejects B-combine sequences. |
| `USER1_DATA_EN` | bit | 0/1 | Enables the slow USER1 `DATA`/timestamp readback window. Default `1` preserves compatibility and supports fallback reads. Set `0` in minimal AMD/Xilinx builds that rely on fast burst readout to remove the sample-clock USER1 data CDC and part of the readback mux. Such a core can only be read by burst: when a capture would need the window (no burst on the transport, `--no-burst`, or a manager slot the transport's burst cannot reach), the host raises `DataWindowError` rather than returning the zeros the core answers. |
| `WIDE_TRIG` | bit | 0/1 | Not a parameter of the ELA vendor wrappers or the `fcapz_debug_multi_*` hubs: only the bare `fcapz_ela` core (default `0`) and the AXI monitor (`fcapz_axi_mon` and its `_xilinx7` / `_intel` wrappers, default `1`) expose it. Makes comparator A's value/mask programmable across the full `SAMPLE_W` via the `WIDE_SEL`/`WIDE_DATA` indexed-word window, instead of only the low 32 bits (upper bits masked to 0). Default `0` keeps the register path minimal and is bit-identical to prior builds. Set `1` on wide-sample cores (e.g. the AXI monitor) that need to trigger on fields above bit 31; `COMPARE_CAPS` bit 18 advertises it. Only meaningful when `SAMPLE_W > 32`. |
| `BURST_W` | int | 256 | Burst DR width.  Don't change unless you know exactly what you're doing. |
| `BURST_EN` | bit | 0/1 | AMD/Xilinx and PolarFire wrapper option to instantiate the legacy DATA_CHAIN (PolarFire: `IR_USER2`) burst read engine when `SINGLE_CHAIN_BURST=0`. Default `1` keeps that compatibility path available only when selected. |
| `SINGLE_CHAIN_BURST` | bit | 0/1 | AMD/Xilinx and PolarFire wrapper option to keep fast 256-bit burst readout on `CTRL_CHAIN` (PolarFire: `IR_USER1`) instead of using a second USER chain. Default `1`: one USER chain carries both 49-bit register packets and 256-bit data packets. Set `0` only for legacy two-chain builds, and construct the host transport with `single_chain_burst=False`. |
| `CTRL_CHAIN` | int | 1..4 | BSCANE2 USER chain for the control register interface. |
| `DATA_CHAIN` | int | 1..4 | BSCANE2 USER chain for the burst data readback. |
| `IR_USER1` / `IR_USER2` | 8-bit | `0x10..0x7F` | PolarFire wrappers only, in place of `CTRL_CHAIN` / `DATA_CHAIN`: the `UJTAG` IR opcodes of the two chains. Default `0x20` / `0x21`, clear of the PolarFire SoC MSS debug module at `0x10` / `0x11`. |
| `EIO_EN` | bit | 0/1 | When `1`, the ELA wrapper also instantiates an EIO core and muxes it onto `CTRL_CHAIN` via an address decoder — ELA registers live at `0x0000..0x7FFF`, EIO registers at `0x8000..0xFFFF`.  Lets you use both cores on a single USER chain when you want to conserve BSCAN primitives or share a chain for deployment reasons.  A standalone `fcapz_eio_xilinx7` / `_xilinxus` can still sit on a different, unused USER chain, but not on `CTRL_CHAIN`. |
| `NUM_EIOS` | int | 0..N | `fcapz_debug_multi_*` wrappers only. Number of managed EIO slots after the ELA slots. Defaults to `EIO_EN` for one-EIO compatibility; `NUM_ELAS=0` with `NUM_EIOS>0` builds an EIO-only hub. |
| `EIO_IN_W` | int | 1..N | EIO input bus width when `EIO_EN=1`. |
| `EIO_OUT_W` | int | 1..N | EIO output bus width when `EIO_EN=1`. |

**Migration note:** older AMD/Xilinx bitstreams may have been built with
`SINGLE_CHAIN_BURST=0`, where 256-bit burst scans live on `DATA_CHAIN`.
The current host default expects single-chain burst on `CTRL_CHAIN`. If a
legacy bitstream's capture fails with a burst error that names
`--two-chain-burst`, use that CLI option or construct
`XilinxHwServerTransport(single_chain_burst=False)`. A build with neither
burst path (`SINGLE_CHAIN_BURST=0`, `BURST_EN=0`) is opened with
`--no-burst` (`burst=False`) and read through the register window.

**Startup defaults:** `STARTUP_ARM` and `DEFAULT_TRIG_EXT` rely on the FPGA
and synthesis flow preserving register initial values at configuration time
(for example, AMD/Xilinx GSR/INIT behavior). If a target family or flow does not
guarantee those initial values, configure the registers from the host after
programming instead of relying on power-up auto-arm behavior.

The default config is intentionally small and single-chain, while still
keeping compatibility features such as comparator B and USER1 fallback
readout enabled. The reference Arty A7 design builds its two ELAs through
the debug manager with these overrides (both slots share them):

```verilog
fcapz_debug_multi_xilinx7 #(
    .NUM_ELAS         (2),
    .EIO_EN           (1),
    .NUM_EIOS         (2),
    .SAMPLE_W         (8),
    .DEPTH            (1024),
    .INPUT_PIPE       (1),
    .DECIM_EN         (1),
    .EXT_TRIG_EN      (1),
    .TIMESTAMP_W      (32),
    .NUM_SEGMENTS     (4),
    .STARTUP_ARM      (1),
    .DEFAULT_TRIG_EXT (2),
    .EIO_IN_W         (8),
    .EIO_OUT_W        (8)
) u_debug ( ... );
```

Everything else stays at the defaults: `TRIG_STAGES=1`, `STOR_QUAL=0`,
`REL_COMPARE=0`, `DUAL_COMPARE=1`, `USER1_DATA_EN=1`, `NUM_CHANNELS=1`,
`PROBE_MUX_W=0`, and no run-length capture.  This is the configuration the
Arty hardware integration tests exercise; the sequencer, storage
qualification and relational compares are covered by the KV260 test
instead.  See [chapter 05](05_ela_core.md) for what each feature actually
does at runtime.

### Combining ELA + EIO on a single USER chain (`EIO_EN=1`)

Two cases to use this mode:

1. **Resource-constrained parts** with only one spare USER chain (ECP5
   designs with heavy logic, small Lattice / Gowin parts, etc.).
2. **Zynq UltraScale+ MPSoC (xck26 / xczu*) without named-register
   IR mode.**  Through xsdb, raw hex IR opcodes reach only USER1 on
   these parts (USER2..USER4 alias to USER1 or put the TAP in BYPASS).
   The hw_server transport's named-register mode
   (`use_register_ir=True`, which a tap named `xck…` / `xczu…`
   selects automatically in the CLI, GUI, RPC server and MCP server) reaches all four USER chains, so a standalone
   `fcapz_eio_xilinxus` works there — see [chapter 14 "Zynq UltraScale+
   MPSoC — how the JTAG chain works with xsdb"](14_transports.md#zynq-ultrascale-mpsoc--how-the-jtag-chain-works-with-xsdb).
   Only when you drive the PL TAP without that mode, set `EIO_EN=1` on
   the ELA wrapper, drop the standalone `fcapz_eio_xilinxus` instance
   from your top level, and EIO will ride along on USER1.

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
- With the default `SINGLE_CHAIN_BURST=1`, the 256-bit burst readback
  shares USER1 too, so the whole ELA + EIO pair uses one chain.  Only a
  legacy `SINGLE_CHAIN_BURST=0` build keeps burst readback on its own
  `DATA_CHAIN` (USER2 by default).
- A standalone `fcapz_eio_xilinx7` / `_xilinxus` must not reuse the same
  USER chain (two BSCANE2s on one chain).  On another unused chain, such
  as USER3, it works alongside the shared one.
- For multiple ELAs plus EIO on one chain, prefer the
  `fcapz_debug_multi_<vendor>` hub (`xilinx7`, `xilinxus`, `intel`, `ecp5`,
  `polarfire`, `efinix`, `gowin`); it uses
  the descriptor-capable `"CM"` active-slot manager instead of the older fixed
  `0x8000` EIO address window.

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
| `ADDR_W` | 32 | AXI address width.  Only 32 is supported: the JTAG command DR carries a 32-bit address field (`[31:0]`) and the host masks every address to 32 bits.  The parameter accepts a wider value, but nothing above bit 31 is host-reachable: the set-address and burst-setup paths zero-extend the 32-bit field, and the direct read/write path part-selects past it.  Wider builds are untested. |
| `DATA_W` | 32 | AXI data width.  Only 32 is supported today. |
| `FIFO_DEPTH` | 1..256, **power of 2** | Async FIFO depth for burst reads.  Limits the maximum burst length the host can request — the host caches this from `FEATURES[23:16]` and rejects oversized requests at the API boundary.  See [chapter 07](07_ejtag_axi_bridge.md). |
| `CMD_FIFO_DEPTH` | power of 2 | TCK-to-AXI command queue depth. The wrapper default follows the core (`2*FIFO_DEPTH`) for compatibility; AMD/Xilinx XPM FIFO builds require at least 16. |
| `RESP_FIFO_DEPTH` | power of 2 | AXI-to-TCK response queue depth. The wrapper default follows the core (`2*FIFO_DEPTH`) for compatibility; AMD/Xilinx XPM FIFO builds require at least 16. |
| `TIMEOUT` | int | AXI handshake timeout in `axi_clk` cycles.  Applies to `wready`/`bvalid`/`arready`/`rvalid` waits, **not** between burst beats. |
| `DEBUG_EN` | 0, 1 | Enables the 256-bit debug buses and debug CONFIG capture records. Defaults off to let synthesis prune debug-only storage and counters. |
| `CMD_FIFO_MEMORY_TYPE` | `"auto"`, `"block"`, `"distributed"` | AMD/Xilinx XPM storage selector for the command queue. Ignored by the portable behavioral FIFO. |
| `RESP_FIFO_MEMORY_TYPE` | `"auto"`, `"block"`, `"distributed"` | AMD/Xilinx XPM storage selector for the response queue. Ignored by the portable behavioral FIFO. |
| `BURST_FIFO_MEMORY_TYPE` | `"auto"`, `"block"`, `"distributed"` | AMD/Xilinx XPM storage selector for the burst read FIFO. Ignored by the portable behavioral FIFO. |
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
| `PARITY` | 0/1/2 | 0=none, 1=even, 2=odd. |

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

### Only sample bits [31:0] can trigger without `WIDE_TRIG`

Without `WIDE_TRIG=1`, comparator A's value and mask are 32 bits wide, so
an ELA wider than 32 bits can trigger only on sample bits `[31:0]`.  The
limit shows up only at `configure()` time, as "trigger value/mask exceed 32
bits".  The ELA vendor wrappers and the `fcapz_debug_multi_*` hubs build
without `WIDE_TRIG` and have no parameter to turn it on, so put the signals
you want to trigger on in the low 32 bits of `probe_in`.  `WIDE_TRIG=1` is
available only on the bare `fcapz_ela` core and on the AXI monitor, where it
is on by default.  `probe()` reports `has_wide_trigger`.

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

The fix is to add the header and the two `set_property` lines from the
[minimal file list](#minimal-instantiation-ela-only) (the same pattern
[`build_arty_vex.tcl`](../examples/arty_a7/build_arty_vex.tcl) uses).  iverilog needs `-I rtl` on the command line; the
project's [`sim/run_sim.py`](../sim/run_sim.py) already does this.

## Vendor wrapper differences

The wrappers share the same fabric-side ports (`sample_clk`,
`sample_rst`, `probe_in`, ...), but the port lists are not identical
across vendors:

- `_xilinx7` and `_xilinxus` have identical ports and parameters; only the
  module name differs.
- `_intel` matches them for an ELA-only design but has no EIO ports
  (`EIO_EN` is not a parameter there).
- `_ecp5` has no external-trigger ports (`trigger_in` / `trigger_out` /
  `armed_out`).
- `_gowin` and `_polarfire` need top-level JTAG pad connections
  (`*_pad_i` / `tdo_pad_o`); Gowin also takes a `clk` input and drives a
  `jtag_activity` output.
- `_efinix` exposes two groups of TAP signals (`jtag1_*`, `jtag2_*`) that
  you connect to the JTAG User TAP blocks set up in Efinity's Interface
  Designer.

So only the AMD/Xilinx 7-series to UltraScale(+) switch is a one-line
change to your top-level:

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
`Analyzer.connect()` call works against either bitstream.  On UltraScale(+)
use xsdb's register-IR mode, which looks up each part's USER instructions
(the CLI, GUI, web UI and MCP pick it from the part name):

```python
from fcapz import XilinxHwServerTransport
transport = XilinxHwServerTransport(
    port=3121,
    fpga_name="xcku040",
    use_register_ir=True,
)
```

Single-die UltraScale parts also answer the 7-series raw opcodes
(`USER1..USER4 = 0x02, 0x03, 0x22, 0x23`); multi-die parts (KU085, KU115,
most Virtex UltraScale+) have a longer IR.

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
