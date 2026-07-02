# Architecture — v0.4.0

## Goal
Vendor-agnostic JTAG logic analyzer core with configurable features,
designed to fit on any FPGA with minimal resource usage.

## Core Blocks
- **Probe Input**: User-defined probe buses flattened into `SAMPLE_W` bits (1-256+).
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
  (0 = off, 1 = on, +21 LUTs).
- **Sample Buffer**: Dual-port BRAM (`dpram.v`) for pre-trigger history plus
  post-trigger capture. Port A on sample_clk, port B on jtag_clk.
- **Capture Controller**: Arm, trigger detect, post-trigger countdown, done.
- **JTAG Register Map** (`jtag_reg_iface.v`): 49-bit DR on USER1 for
  control/status + per-word data readback.
- **Single-Chain Pipe** (`jtag_pipe_iface.v`): default Xilinx path that
  carries both 49-bit register packets and 256-bit burst packets on USER1.
- **Burst Readback** (`jtag_burst_read.v`): legacy separate-chain 256-bit DR
  for fast block reads (32 8-bit samples per scan).
- **Embedded I/O** (`fcapz_eio.v`): JTAG-accessible input/output probe registers
  on USER3 (CHAIN=3). `IN_W`-bit input bus synchronised to jtag_clk;
  `OUT_W`-bit output register driven to fabric.  Parameters: `IN_W`, `OUT_W`.
- **TAP Wrappers** (`jtag_tap/`): Vendor-specific JTAG primitives for
  Xilinx, Lattice, Intel, and Gowin.

## Parameters
| Parameter | Default | Description |
|-----------|--------:|-------------|
| `SAMPLE_W` | 32 | Probe width in bits (1-256+) |
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

When `TRIG_STAGES=1`, `STOR_QUAL=0`, `DECIM_EN=0`, `EXT_TRIG_EN=0`,
`TIMESTAMP_W=0`, `NUM_SEGMENTS=1`, `NUM_CHANNELS=1`, `INPUT_PIPE=0`, and
`PROBE_MUX_W=0`, extra logic optimises away in synthesis.

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

## Clocking
- `sample_clk` is the capture clock.
- JTAG clock (TCK) is independent; control/config paths cross through the
  core's synchronizer and toggle-handshake CDCs.
- Sample buffer uses true dual-port RAM (port A = sample_clk, port B = TCK).
- DATA-window readback is decoded in the JTAG domain and reads RAM port B.
  The sample domain exports completed-capture metadata through an acked
  snapshot CDC, so per-read sample payloads no longer cross as wide CDC buses.
- EIO probe_in uses a 2-FF synchroniser into jtag_clk. probe_out is in jtag_clk domain.

## Data Model
- Samples stored as packed `SAMPLE_W` vectors in BRAM.
- Wide samples (> 32 bits) read as multiple 32-bit chunks via USER1,
  or natively via the 256-bit burst DR.
- Timestamps are implicit by sample index.

## JTAG-to-AXI4 Bridge (`fcapz_ejtagaxi.v`)

The bridge provides AXI4 master access from the JTAG port using a 72-bit
pipelined DR on USER4 (CHAIN=4). The pipeline is: **72-bit DR → shadow
registers → CDC → AXI4 master FSM → AXI bus**.

**Data path:** On DR update, the parsed command and address/data are latched
into shadow registers in the TCK domain. A toggle-handshake CDC transfers
the request to the `axi_clk` domain, where a 10-state FSM drives the AXI4
channels. The response is latched back and presented on the next DR capture.

**CDC strategy:** Single-word transactions use a toggle-handshake between
TCK and `axi_clk`. Burst reads use an asynchronous FIFO (Gray-coded
pointers, configurable `FIFO_DEPTH`) so the AXI side can fill data while
the host scans out words one per DR shift. Burst writes use per-beat
toggle handshake: the AXI FSM acks each beat (except the last) so the
host can queue the next.

**Burst timing:** The AXI-side timeout (`TIMEOUT` parameter) applies only
to AXI handshake waits (wready, bvalid, arready, rvalid). It does NOT
apply between burst write beats in `ST_BURST_W`, because inter-beat pacing
is host-controlled via JTAG scans — far longer than
any AXI-side timeout.

**Burst read pipeline:** The FIFO read has a 1-scan pipeline delay: the
first `BURST_RDATA` scan sets `last_cmd` but does not capture FIFO data
(because `last_cmd` was still `BURST_RSTART` at CAPTURE time). The host
sends a priming `BURST_RDATA`, then N data scans for N words.

**Host pacing:** Single-word paths issue roughly one JTAG round trip per
`raw_dr_scan`; auto-increment blocks and batched APIs amortise tool
overhead via `raw_dr_scan_batch` where the transport implements it.
Hardware-validated on Arty A7-100T: single read/write, auto-increment
blocks, and AXI4 burst read/write all pass.  Different JTAG adapters or
a raw TCF transport (bypassing XSDB) change how much of the cable's
bandwidth you actually see.

Parameters: `ADDR_W` (default 32), `DATA_W` (default 32), `FIFO_DEPTH`
(default 16), `TIMEOUT` (default 4096 axi_clk cycles).

**Verified Xilinx 7-series IR codes** (xc7a100t):
USER1=0x02, USER2=0x03, USER3=0x22, USER4=0x23.

## Testing

| Level | Command | Coverage |
|-------|---------|----------|
| Unit (Python) | `pytest tests/test_host_stack.py` | Transport, Analyzer, EioController |
| RTL lint | `python sim/run_sim.py --lint-only` | Shared `iverilog -Wall` elaboration target list used by CI |
| Simulation | `python sim/run_sim.py` | Runs RTL lint first, then ELA behavior, ELA focused regressions, ELA configuration matrix, burst readout, single-chain pipe readout, EIO, core-manager, and channel-mux testbenches |
| Hardware | `pytest examples/arty_a7/test_hw_integration.py` | Arty A7-100T hardware regression for the reference bitstream |
