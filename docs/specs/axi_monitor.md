# AXI Monitor (`fcapz_axi_mon.v`) — design spec

> **Status: proposed / draft.** No RTL exists yet. This is the canonical
> design plan for a portable, vendor-agnostic passive AXI monitor core. It is the
> ground truth the implementation must follow; when a future chapter and this
> spec disagree, this spec wins.

## Goal

Give fpgacapZero a **portable, vendor-agnostic AXI bus monitor**: a core
you drop onto an existing **AXI4 / AXI4-Lite / AXI4-Stream** interface to
**passively** capture and trigger on **transactions** — "trigger on a write of
`0xDEAD` to `0x4000_0000` that returns `SLVERR`", "show me every burst to this
peripheral", "stop on the first protocol violation" — and view the decoded
traffic in the waveform viewer.

Vendor AXI debug monitors are tied to a single toolchain. A portable, open, scriptable AXI monitor that also
**composes with the existing EJTAG-AXI master** (stimulate *and* observe the
same bus over JTAG) is a genuine differentiator, not catch-up.

### Why this is tractable

The ELA core ([`fcapz_ela.v`](../../rtl/fcapz_ela.v)) already provides the hard
part — the capture engine and a Vivado-ILA-class trigger sequencer (full
comparator set EQ/NEQ/LT/GT/LEQ/GEQ/RISING/FALLING/CHANGED, two match units per
stage, occurrence counters, a branching `next_state` FSM, storage qualification,
segmented windows, external trigger I/O, decimation, timestamps). The monitor is
therefore **`fcapz_ela` plus an AXI front-end**, not a new capture engine:

```
        AXI interface under test (passive tap; READY is never driven)
   AW* W* B* AR* R*  ──────────────┐
                                   ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ fcapz_axi_mon  (ACLK domain)                                   │
   │                                                                │
   │   ┌─ channel select / flatten ─┐   ┌─ transaction decoder ──┐  │
   │   │  AW/W/B/AR/R fields ->      │   │ handshakes, addr-range │  │
   │   │  one wide probe vector      │   │ resp codes, ID match,  │  │
   │   │                             │   │ burst, outstanding,    │  │
   │   │                             │   │ stall-for-N, violations│  │
   │   └──────────────┬──────────────┘   └───────────┬────────────┘  │
   │                  └──────────►  probe_in  ◄───────┘               │
   │                         ┌───────────────────┐                   │
   │                         │     fcapz_ela      │  (instantiated)   │
   │                         │  capture + trigger │                   │
   │                         └─────────┬──────────┘                   │
   └───────────────────────────────────┼───────────────────────────┘
              JTAG (USER chain) ────────┘     same regs / host / viewer
```

`sample_clk` = the monitored interface's `ACLK`; `probe_in` = the flattened
channel + decoder vector; everything downstream (registers, host `Analyzer`,
CLI/GUI/web, Surfer) is reused unchanged.

## Scope and non-goals

| Phase | Deliverable |
|-------|-------------|
| **P1** | Passive AXI4/AXI4-Lite tap → channel flatten → `fcapz_ela.probe_in`; Xilinx-7 wrapper; cocotb bench; a shipped **AXI probe map** so captures show named signals (`awaddr`, `bresp`, …). Gets "capture & view an AXI bus" working — ~80% of the value. |
| **P2** | **Transaction decoder**: derived trigger signals wired into the sequencer, plus host **AXI-trigger presets** (trigger on write/read to address-in-range, on response code, on ID). |
| **P3** | **Protocol checker**: AXI compliance assertions → a sticky `violation` probe bit + a violation-code register. |
| **P4** | **Transaction decode in the viewer**: emit transaction-stream metadata so Surfer renders AW→W→B / AR→R as a transaction/relation view, not just raw signals. |
| **P5** | **Vivado interop**: import a `.ltx` probe file into fcapz probe definitions; document coexistence with the Vivado hw_server (already a supported transport). |

Non-goals: bus-mastering or back-pressuring the monitored interface (it is
strictly passive — `*READY`/`*VALID` are inputs only); replacing the EJTAG-AXI
master; full AXI4-Stream packet reassembly in P1 (Stream is a flatten-only
target initially).

## RTL

### Module

```verilog
module fcapz_axi_mon #(
    // protocol + interface geometry
    parameter PROTO        = "AXI4",   // "AXI4" | "AXI4LITE" | "AXIS"
    parameter ADDR_W       = 32,
    parameter DATA_W       = 32,
    parameter ID_W         = 4,
    // which channels to flatten into the capture vector (bitmask AW,W,B,AR,R)
    parameter CAP_CHANNELS = 5'b11111,
    parameter DECODE_EN    = 0,        // P2: transaction decoder + derived events
    parameter PROTO_CHECK_EN = 0,      // P3: protocol checker
    parameter ADDR_FILTERS = 0,        // number of runtime address-range comparators
    // pass-through ELA capture/trigger configuration
    parameter DEPTH        = 1024,
    parameter TRIG_STAGES  = 4,
    parameter STOR_QUAL    = 1,
    parameter NUM_SEGMENTS = 1,
    parameter TIMESTAMP_W  = 32,
    parameter REL_COMPARE  = 1
) (
    // passive monitor tap (inputs only — wired in parallel with the real bus)
    input wire ACLK, input wire ARESETN,
    input wire [ID_W-1:0] AWID, input wire [ADDR_W-1:0] AWADDR, /* …AW* … */
    /* … W* B* AR* R* … */

    // JTAG register + burst interface (identical to fcapz_ela)
    input  wire jtag_clk, jtag_rst, jtag_wr_en, jtag_rd_en,
    input  wire [15:0] jtag_addr, input wire [31:0] jtag_wdata,
    output wire [31:0] jtag_rdata
    /* burst read port … */
);
```

Vendor wrappers (`fcapz_axi_mon_xilinx7`, `…_xilinxus`, `…_intel`, …) bundle the
JTAG plumbing exactly like the other cores. For IP-integrator flows the wrapper
can expose an AXI4 **monitor** interface so it drops onto a block-design
connection as a passive monitor.

### Capture-vector layout (P1)

The selected channels concatenate, LSB-first, into `probe_in`. The exact bit
layout is the contract the probe map and the host depend on, e.g. for AXI4-Lite
write+read with `ADDR_W=32, DATA_W=32`:

```
[ awaddr(32) | awvalid(1) | awready(1) |
  wdata(32)  | wstrb(4)   | wvalid(1)  | wready(1) |
  bresp(2)   | bvalid(1)  | bready(1)  |
  araddr(32) | arvalid(1) | arready(1) |
  rdata(32)  | rresp(2)   | rvalid(1)  | rready(1)  | … ]
```

`SAMPLE_W` is computed from `PROTO`, the widths, and `CAP_CHANNELS`. Full AXI4
adds `*ID/*LEN/*SIZE/*BURST/*LAST`. A generator emits both the RTL slice
constants and the matching probe map so they never drift.

### Transaction decoder (P2)

A small comb/seq block over the tapped channels produces **derived event bits**
appended to the capture vector and exposed to the sequencer comparators:

- handshake pulses: `aw_hs`, `w_hs`, `b_hs`, `ar_hs`, `r_hs` (`VALID & READY`);
- per-`ADDR_FILTERS` `awaddr_in_range[i]` / `araddr_in_range[i]` (runtime
  base/limit registers);
- `bresp`/`rresp` decode: `is_okay`, `is_slverr`, `is_decerr`;
- `awid`/`arid`/`bid`/`rid` match against a runtime ID register;
- burst info: `awlen`, `awsize`, `awburst` exposed as fields; `rlast`/`wlast`;
- `outstanding_w` / `outstanding_r` counters (AW issued minus B seen, etc.);
- `stall_n`: `VALID` asserted without `READY` for ≥ N cycles (backpressure).

Because these are just more probe bits, **no new trigger RTL is needed** — the
existing sequencer expresses transaction triggers directly. Example: "write to
`0x4000_0000`–`0x4000_0FFF` returning `SLVERR`" = stage A `awaddr_in_range[0] &
aw_hs` → stage B `is_slverr & b_hs`, `is_final`.

## Register map

The monitor **keeps the ELA register map verbatim** so the host `Analyzer` and
all existing tooling drive capture/trigger unchanged. AXI-monitor specifics live
in a reserved extension block and an identity register:

| Address | Reg | Notes |
|---------|-----|-------|
| `0x0000` | VERSION | ELA-compatible. `[15:0]` ASCII core ID. The monitor reports **`"AM"` = `0x414D`**; tooling that only checks for an ELA accepts a `FEATURES` "is-ELA" contract, while AXI-aware tooling keys off `"AM"`. (Final choice — dual-ID vs. FEATURES bit — is an open question below.) |
| `0x0004`–`0x00E0` | *(ELA register map)* | CTRL/STATUS/TRIG_*/SEQ_*/SQ_*/FEATURES/… exactly as [`register_map.md`](register_map.md). |
| `0x0100` | AXI_MON_ID | `[31:16]` = `"AM"`, `[15:8]` = `PROTO` code, `[7:0]` = capability flags (DECODE_EN, PROTO_CHECK_EN). |
| `0x0104` | AXI_GEOM | `[7:0]` ADDR_W, `[15:8]` DATA_W, `[19:16]` ID_W, `[24:20]` CAP_CHANNELS. |
| `0x0108` | DEC_CTRL | decoder/checker enables, ID-match register select. |
| `0x010C` | ID_MATCH | runtime `*ID` value to match. |
| `0x0110 + i*8` | ADDR_FILTER_i_BASE | per-filter base address. |
| `0x0114 + i*8` | ADDR_FILTER_i_LIMIT | per-filter limit address. |
| `0x0180` | VIOLATION | P3: sticky violation flags + code; write-1-clear. |

Allocate the AXI block at `0x0100+` to stay clear of the ELA's `0x0000–0x00E0`
window and its sequencer stages.

## Host & viewer integration

- **Probe map**: ship `probes/axi4lite_32.prob` (and AXI4 variants) describing
  the capture-vector layout as named signals. The web/CLI/GUI already load
  `.prob`/JSON probe definitions, so captures show `awaddr`/`bresp`/… with zero
  new host code. The generator emits the map alongside the RTL slice constants.
- **`AxiMonitor` host class** (thin, over the existing `Analyzer`): detects the
  `"AM"` identity, reads `AXI_GEOM`, applies the right probe map, and exposes
  **transaction-trigger presets** that compile to sequencer stages
  (`trigger_on_write(addr_range, resp=…)`, `trigger_on_id(id)`,
  `trigger_on_violation()`).
- **CLI / web / GUI**: an "AXI trigger" preset panel that builds the sequencer
  config; otherwise the existing capture/run/download/viewer flow is reused.
- **Surfer (P4)**: emit transaction-stream metadata in the export so Surfer
  renders AW→W→B / AR→R as transactions. Surfer supports transaction/relation
  views; until then the named-signal capture already reads well.

## Testing

- **cocotb** bench: an AXI master BFM + slave BFM drive a real interface; the
  monitor taps it. Assert (a) the flattened capture matches the driven
  transactions, (b) each transaction-trigger preset fires on the intended
  beat and not otherwise, (c) the protocol checker flags injected violations.
- Reuse the existing sim harness and lint-elaboration per vendor wrapper.
- `tools/sync_version.py` gains the `"AM"` core-ID constant.

## Open questions / decisions

1. **Identity**: dual-report (`"AM"` with an ELA-compatible `FEATURES`
   contract) vs. report `"LA"` and advertise AXI via a `FEATURES` bit + the
   `AXI_MON_ID` register. Leaning toward `"AM"` + a documented "is-ELA-capable"
   `FEATURES` bit so the generic `Analyzer` path still works.
2. **Clock domains**: capture runs in `ACLK`. JTAG register access already
   crosses to `jtag_clk` inside `fcapz_ela`; confirm the decoder's counters live
   wholly in `ACLK`.
3. **AXI4-Stream**: P1 flatten-only; packet reassembly/decode is a later phase.
4. **Width budget**: full AXI4 with wide `DATA_W` makes `SAMPLE_W` large; rely
   on `CAP_CHANNELS` + storage qualification + the runtime probe mux to keep
   captures affordable. Document a recommended default profile.

## See also

- [`register_map.md`](register_map.md) — the ELA register map the monitor reuses.
- [`architecture.md`](architecture.md) — block diagram and parameter conventions.
- [Chapter 05 · ELA core](../05_ela_core.md) — the capture/trigger engine this
  builds on.
- [Chapter 07 · EJTAG-AXI bridge](../07_ejtag_axi_bridge.md) — the AXI *master*
  this composes with.
