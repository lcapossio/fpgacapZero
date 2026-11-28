# Architecture

## Goal
Vendor-agnostic JTAG logic analyzer core with configurable features,
designed to fit on any FPGA with minimal resource usage.

## Core Blocks
- **Probe Input**: User-defined probe buses flattened into `SAMPLE_W` bits (1-256).
- **Trigger Block** (`trig_compare.v` × 2 per stage): Dual comparators (A and B)
  with lightweight default compare modes (==, !=, rising, falling, changed),
  optional relational modes (<, >, <=, >=), and boolean combine
  (A-only, B-only, AND, OR). Optional multi-stage sequencer
  (2-4 states) with occurrence counter and state transitions. Builds with
  `INPUT_PIPE>=1` also register comparator hits internally, keeping optional
  relational compares off the capture-control critical path.
  Controlled by `TRIG_STAGES` parameter (1 = simple, 2-4 = sequencer).
- **Feature-gated ELA Core**: disabled feature groups stop accepting writes,
  cross as constants, and read back fixed values so synthesis can remove their
  registers and muxes. Small builds use the same `fcapz_ela.v` implementation
  as full builds.
- **Storage Qualification**: Optional condition that filters which samples
  are stored, effectively multiplying buffer depth. `STOR_QUAL` parameter
  (0 = off, 1 = on; see the resource table below for its cost).
- **Sample Buffer**: Dual-port BRAM (`dpram.v`) for pre-trigger history plus
  post-trigger capture. Port A on sample_clk, port B on jtag_clk.
- **Capture Controller**: Arm, trigger detect, post-trigger countdown, done.
- **JTAG Register Map** (`jtag_reg_iface.v`): 49-bit DR on USER1 for
  control/status + per-word data readback.
- **Single-Chain Pipe** (`jtag_pipe_iface.v`): default AMD/Xilinx path that
  carries both 49-bit register packets and 256-bit burst packets on USER1.
- **Burst Readback** (`jtag_burst_read.v`): legacy separate-chain 256-bit DR
  for fast block reads (32 8-bit samples per scan).
- **Embedded I/O** (`fcapz_eio.v`): JTAG-accessible input/output probe registers
  on USER3 (CHAIN=3). `IN_W`-bit input bus synchronised to jtag_clk;
  `OUT_W`-bit output register driven to fabric.  Parameters: `IN_W`, `OUT_W`.
- **TAP Wrappers** (`jtag_tap/`): Vendor-specific JTAG primitives for
  AMD/Xilinx, Lattice, Intel/Altera, Gowin, Microchip, and Efinix
  (Trion/Titanium JTAG User TAP).

## Parameters
| Parameter | Default | Description |
|-----------|--------:|-------------|
| `SAMPLE_W` | 32 | Probe width in bits (1-256; wider fails elaboration) |
| `DEPTH` | 1024 | Sample buffer depth (power of 2) |
| `TRIG_STAGES` | 1 | Trigger sequencer stages (1 = simple, 2-4 = sequencer) |
| `STOR_QUAL` | 0 | Storage qualification (0 = off, 1 = on) |
| `NUM_CHANNELS` | 1 | Mutually exclusive probe buses (runtime mux when >1) |
| `INPUT_PIPE` | 0 | Optional pipeline registers on `probe_in`; also enables registered compare hits |
| `DECIM_EN` | 0 | Runtime decimation register |
| `EXT_TRIG_EN` | 0 | `trigger_in` / `trigger_out` ports |
| `TIMESTAMP_W` | 0 | Per-sample timestamp RAM (`0` = off, 32 or 48) |
| `NUM_SEGMENTS` | 1 | Segmented capture (`>1` adds segment RAM/control) |
| `PROBE_MUX_W` | 0 | Packed probe mux width (`0` = off; else runtime slice select) |
| `STARTUP_ARM` | 0 | Power-up value of the `STARTUP_ARM` register (1 = arm automatically after reset/programming) |
| `DEFAULT_TRIG_EXT` | 0 | Reset value of the external trigger mode (0-3) |
| `REL_COMPARE` | 0 | Relational compare modes (`<`, `>`, `<=`, `>=`) |
| `DUAL_COMPARE` | 1 | Comparator B and the combine modes (`0` = comparator A only) |
| `USER1_DATA_EN` | 1 | USER1 DATA window readback and `DATA_OFFSET` (`0` = burst-only readout) |
| `RLE_W` | 0 | Run-length capture count width (`0` = off, 1-16) |
| `WIDE_TRIG` | 0 | Comparator A programmable across the full `SAMPLE_W` through `WIDE_SEL`/`WIDE_DATA` (only above 32 bits) |
| `READBACK_RAM` | 1 | Keep the readback-only upper bits of value/mask registers (`SAMPLE_W < 32`) in a small inferred RAM; `0` = flops, for families without async-read LUT RAM (iCE40, Efinix) |

Continuous (segment-ring) capture has no parameter of its own: it is built
whenever `NUM_SEGMENTS > 1` and advertised by `COMPARE_CAPS` bit 23.
Wrappers add their own parameters (for example `SINGLE_CHAIN_BURST` on the
AMD/Xilinx wrappers); see [chapter 04](../04_rtl_integration.md).

When `TRIG_STAGES=1`, `STOR_QUAL=0`, `DECIM_EN=0`, `EXT_TRIG_EN=0`,
`TIMESTAMP_W=0`, `NUM_SEGMENTS=1`, `NUM_CHANNELS=1`, `INPUT_PIPE=0`,
`PROBE_MUX_W=0` and `RLE_W=0`, extra logic optimises away in synthesis
(`DUAL_COMPARE=0` and `USER1_DATA_EN=0` trim further).

EIO core parameters (separate module, `fcapz_eio.v`):

| Parameter | Default | Description |
|-----------|--------:|-------------|
| `IN_W` | 32 | Input probe width (fabric → host) |
| `OUT_W` | 32 | Output probe width (host → fabric) |

## Resource Usage (xc7a100t)

Canonical resource reference for the project. **Slice LUTs** and **FFs** are
from Vivado **synthesis** (2025.2); the `arty_a7_top` rows are **post–place &
route** totals from the shipped reference build (Apr 2026). The small rows are
wrapper-inclusive — they include the JTAG TAP / register / readout plumbing,
not only `fcapz_ela.v`. The sample buffer uses dual-port BRAM, so scaling
wider or deeper adds BRAM, not LUTs.

| Config | Slice LUTs | FFs | BRAM | Notes |
|--------|-----:|----:|-----:|-------|
| 8b x 1024, A-only, slow USER1 readout | 596 | 779 | 0.5 | Smallest practical 1024-sample ELA; `DUAL_COMPARE=0`, optional features off |
| 8b x 1024, A-only, single-chain fast readout | 912 | 1,234 | 0.5 | One BSCANE2; 256-bit USER1 burst via `SINGLE_CHAIN_BURST=1` |
| 8b x 1024, dual comparator, `REL_COMPARE=0` | 2,021 | 1,725 | 0.5 | Compatibility trigger shape; EQ/NEQ/edges/changed |
| 8b x 1024, dual comparator, `REL_COMPARE=1`, `INPUT_PIPE=1` | 2,010 | 1,754 | 0.5 | Adds `<`, `>`, `<=`, `>=`; compare hit registered for timing |
| 8b x 1024, +storage qualification | 2,521 | 1,749 | 0.5 | Same compatibility harness with `STOR_QUAL=1` |
| 8b x 1024, 4-stage sequencer | 2,954 | 2,788 | 0.5 | `TRIG_STAGES=4`, `STOR_QUAL=0` |
| 32b x 1024, dual comparator, `REL_COMPARE=0` | 2,472 | 2,099 | 1.0 | Wider samples mainly add BRAM/FFs |
| `arty_a7_top` (placed, pre-`DEBUG_EN` always-on debug) | 3,244 | 4,562 | 3.5 | Historical baseline for the same validation reference |
| `arty_a7_top` (placed, `DEBUG_EN=0`) | 2,318 | 3,168 | 3.5 | Bridge debug telemetry disabled; previous reference before the EJTAG-AXI FIFO trim |
| **`arty_a7_top` (placed, trimmed EJTAG-AXI FIFOs, `DEBUG_EN=0`)** | **2,371** | **3,356** | **1.5** | Current reference: USER1 debug manager with 2x ELA (`INPUT_PIPE=1`, `DECIM_EN`, `EXT_TRIG_EN`, `TIMESTAMP_W=32`, `NUM_SEGMENTS=4`) + 2x EIO 8/8 + EJTAG-AXI + `axi4_test_slave`; bridge debug telemetry disabled; EJTAG-AXI command/response queues set to 16 entries |

Enabling timestamp, segmentation, decimation, external trigger, or a wide
probe mux adds registers, comparators, and usually **extra BRAM** (e.g.
timestamp storage); the reference row above is the authoritative full-feature
footprint. Per-core deltas are not additive in synthesis because Vivado
optimises across hierarchy.

**Fmax (reference build):** `sys_clk` @ 100 MHz with positive WNS after route
on `arty_a7_top` (xc7a100t, 2025.2). JTAG `tck_bscan` is constrained at 10 MHz
(adapter-dependent in practice, often higher).

### Against the AMD/Xilinx ILA

[`scripts/ila_comparison.tcl`](../../scripts/ila_comparison.tcl) builds
fcapz and the Vivado ILA (v6.2) at the same sample width and depth with
matching trigger features, on xc7a100t with Vivado 2025.2, and counts
each core after `opt_design`.  The ILA counts include its `dbg_hub`
(the BSCANE2 and JTAG hub Vivado inserts at `opt_design`, 490 LUTs and
741 FFs here), and the fcapz counts include `fcapz_ela_xilinx7`'s own
BSCANE2, register interface and readout, so both are what one core
costs in a design.  LUTs include LUTRAM and SRLs (ILA uses some; fcapz
uses 24 LUTRAM in the 8-bit sequenced builds, for the readback-only bits of
its value and mask registers, and none elsewhere).  Every pair uses the same BRAM: 0.5 tiles at 8b x 1024, 7.5 at
64b x 4096.

LUTs / FFs:

| Profile | fcapz 8b x 1024 | ILA + `dbg_hub` 8b x 1024 | fcapz 64b x 4096 | ILA + `dbg_hub` 64b x 4096 |
|---|---:|---:|---:|---:|
| fcapz minimum: one EQ-or-change comparator, slow USER1 readout, one segment | 560 / 779 | — | 688 / 932 | — |
| Basic: one comparator, 4 segments, fast readout (ILA: 1 comparator) | 1,126 / 1,780 | 1,078 / 1,775 | 1,240 / 1,954 | 1,218 / 2,050 |
| Dual: storage qualification, trigger in/out, input pipe (ILA: 2 comparators, capture control, basic trigger) | 1,200 / 1,961 | 1,172 / 1,920 | 1,386 / 2,377 | 1,341 / 2,363 |
| Sequenced: 4-stage sequencer with 2 comparators per stage (ILA: advanced trigger, 8 comparators) | 1,830 / 2,623 | 2,985 / 4,466 | 2,534 / 4,167 | 3,325 / 5,581 |
| ILA advanced trigger with 2 comparators | — | 2,773 / 3,902 | — | 2,938 / 4,345 |
| fcapz sequenced plus decimation and 32-bit timestamps (no ILA equivalent; +1 / +4 BRAM) | 2,011 / 2,803 | — | 2,673 / 4,355 | — |

What it shows:

- The smallest fcapz build takes 52-57% of the LUTs of the smallest
  ILA, which always has relational compares and a fast readout.  It is
  the build for a design that has little room left.
- The basic and dual fcapz builds take 2-4% more LUTs than the ILA,
  and within 5% of its FFs, and do less: without the sequencer
  (`TRIG_STAGES=1`) the fcapz trigger compares only for equal or
  changed, while every ILA match unit also has the relational modes.
  Most of their area is the segment and streaming logic and the
  256-bit burst readout, not the comparator.
- With the sequencer, fcapz takes 39% fewer LUTs and 41% fewer FFs
  than the ILA at 8 bits, and 24% fewer LUTs and 25% fewer FFs at 64
  bits.
- fcapz grows faster with sample width: each comparator keeps its
  value and mask in flip-flops and compares in LUTs, where the ILA loads
  SRL-based match units.  Its stage comparators match only the low 32
  bits of the sample, though, where the ILA's match all 64 (`WIDE_TRIG=1`
  widens comparator A of the simple trigger; these builds leave it off).
- `dbg_hub` is paid once per design and shared by every ILA and VIO.
  The fcapz equivalent is inside each wrapper, or shared by every core
  behind one core manager (`fcapz_debug_multi`).

Run it with `vivado -mode batch -source scripts/ila_comparison.tcl`; it
writes the table and a CSV under `vivado/ila_compare` and takes about
40 minutes.  `FPGACAP_ILA_SIZES` and `FPGACAP_ILA_CASES` pick other
sizes or a subset of the cases.

## Clocking
- `sample_clk` is the capture clock.
- JTAG clock (TCK) is independent; control/config paths cross through the
  core's synchronizer and toggle-handshake CDCs.
- The ELA settings cross as bundled data: the CTRL write that arms or
  soft-resets snapshots them in the TCK domain, and the synchronized toggle
  copies the snapshot (stable since that write) into the sample domain one
  clock before the arm / reset pulse latches it.
- Sample buffer uses true dual-port RAM (port A = sample_clk, port B = TCK).
- DATA-window readback is decoded in the JTAG domain and reads RAM port B.
  The sample domain exports completed-capture metadata through an acked
  snapshot CDC, so per-read sample payloads no longer cross as wide CDC buses.
- EIO probe_in uses a 2-FF synchroniser into jtag_clk. probe_out is in jtag_clk domain.

## Data Model
- Samples stored as packed `SAMPLE_W` vectors in BRAM.
- Wide samples (> 32 bits) read as multiple 32-bit chunks via USER1,
  or natively via the 256-bit burst DR.
- Timestamps: with `TIMESTAMP_W > 0` (32 or 48) a parallel timestamp RAM
  stores the sample-clock counter of each stored sample, read through the
  timestamp window after the DATA words or a timestamp burst. Without it,
  time is implicit in the sample index (scaled by decimation, and not
  recoverable under storage qualification).
- Run-length capture (`RLE_W > 0`, enabled per capture by `RLE_CTRL`): each
  entry stores a sample and how many sample clocks it held, in a parallel
  count RAM read on the timestamp lane; see
  [`rle_capture.md`](rle_capture.md).
- Segmented capture (`NUM_SEGMENTS > 1`) splits the buffer into equal
  windows, one per trigger. The same builds support continuous capture:
  the segments run as a ring that the host drains and releases
  (`STREAM_*` registers); see
  [Continuous capture](../05_ela_core.md#continuous-capture).

## JTAG-to-AXI4 Bridge (`fcapz_ejtagaxi.v`)

The bridge provides AXI4 master access from the JTAG port using a 72-bit
DR on USER4 (CHAIN=4). The pipeline is: **72-bit DR → command FIFO (CDC) →
AXI4 master FSM and write engine → AXI bus → response FIFO (CDC) → DR
capture**. (The original bridge crossed single requests with a toggle
handshake and acknowledged burst-write beats one at a time; the command and
response queues replaced that, and 0.5.2 added whole-burst write buffering,
the write engine and burst-read admission.)

**Data path:** On DR update, the TCK side decodes the command and pushes
AXI work (reads, writes, burst beats, burst-read and stream starts) into an
asynchronous command FIFO. In the `axi_clk` domain an FSM fetches each
command and dispatches it; a separate write engine owns AW, W and B. Every
queued command produces exactly one response (data + `resp`), pushed into an
asynchronous response FIFO. A DR capture shows the oldest queued response
with `prev_valid`, or no result (`prev_valid=0`, `busy`) while responses are
still owed, so the host drains completions with wait scans. `SET_ADDR`,
`BURST_SETUP`, `CONFIG` and `RESET` are handled on the TCK side; a `CONFIG`
result appears on the next scan and leaves queued responses in place.

**CDC strategy:** All TCK ↔ `axi_clk` traffic goes through asynchronous
FIFOs (Gray-coded pointers, or AMD/Xilinx XPM FIFOs when
`ASYNC_FIFO_IMPL=1`): the command FIFO (`CMD_FIFO_DEPTH`, default
`2*FIFO_DEPTH`), the response FIFO (`RESP_FIFO_DEPTH`, default
`2*FIFO_DEPTH`) and the burst-read data FIFO (`FIFO_DEPTH`). `RESET` crosses
as a toggle with an acknowledgment; new AXI commands are refused until it
completes. The `CFG_AXI_STATUS` flags cross through per-bit 2-FF
synchronisers.

**Burst admission:** A burst write is collected whole in the write buffer
(each beat answered OKAY when stored) and only then raises AW; the last
beat's response carries the B. Illegal bursts (4 KB crossing, bad
FIXED/WRAP, size, type, longer than `FIFO_DEPTH`) are refused with SLVERR
before the bus. A burst read raises AR only when all its beats fit in the
burst FIFO, so the R channel never waits on the host.

**Burst timing:** The AXI-side timeout (`TIMEOUT` parameter) is a
no-progress timeout on the bus: the write wait restarts on every AW, W or B
handshake (so it can expire between W beats), and a burst read restarts on
every accepted R beat. Collecting burst-write beats from JTAG is host-paced
and has no timeout. On a timeout the bridge answers SLVERR but still
finishes what it owes the slave: a write runs to its B, an AR stays up until
accepted, and late read beats are drained (`CFG_AXI_STATUS`).

**Burst read pipeline:** The FIFO read has a 1-scan pipeline delay: the
first `BURST_RDATA` scan sets `last_cmd` but does not capture FIFO data
(because `last_cmd` was still `BURST_RSTART` at CAPTURE time). The host
sends a priming `BURST_RDATA`, then N data scans for N words. A scan that
shows a burst word pops it at Update-DR, whatever command that scan shifts
in. The burst's own response (its `resp`) is queued like any other and can
arrive after the last data word.

**Host pacing:** Single-word paths issue roughly one JTAG round trip per
`raw_dr_scan`; auto-increment blocks and batched APIs amortise tool
overhead via `raw_dr_scan_batch` where the transport implements it.
Hardware-validated on Arty A7-100T: single read/write, auto-increment
blocks, and AXI4 burst read/write all pass.  Different JTAG adapters or
a raw TCF transport (bypassing XSDB) change how much of the cable's
bandwidth you actually see.

Parameters: `ADDR_W` (default 32), `DATA_W` (default 32), `FIFO_DEPTH`
(default 16), `CMD_FIFO_DEPTH` and `RESP_FIFO_DEPTH` (default
`2*FIFO_DEPTH`), `TIMEOUT` (default 4096 axi_clk cycles), `STREAM_EN`
(default 0), `DEBUG_EN` (default 0), `ASYNC_FIFO_IMPL` (core default 0,
portable FIFO; the AMD/Xilinx wrappers default to 1, XPM).

**Verified AMD/Xilinx 7-series IR codes** (xc7a100t):
USER1=0x02, USER2=0x03, USER3=0x22, USER4=0x23.

## Testing

| Level | Command | Coverage |
|-------|---------|----------|
| Unit (Python) | `pytest tests/test_host_stack.py` | Transport, Analyzer, EioController |
| RTL lint | `python sim/run_sim.py --lint-only` | Shared `iverilog -Wall` elaboration target list used by CI |
| Simulation | `python sim/run_sim.py` | Runs RTL lint first, then ELA behavior, ELA focused regressions, ELA configuration matrix, burst readout, single-chain pipe readout, EIO, core-manager, and channel-mux testbenches |
| Hardware | `pytest examples/arty_a7/test_hw_integration.py` | Arty A7-100T hardware regression for the reference bitstream |
| Hardware (other boards) | `pytest examples/<board>/test_hw_integration.py` | Per-board suites (see each example README), including the Arty S7-25 and DE0-Nano ELA + EIO examples (on `main`, unreleased; the contributor reported 3 passing tests on each board for PR #85) |
