# Changelog

All notable changes to this project are documented in this file.
Follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added

**EJTAG-AXI Bridge (`rtl/fcapz_ejtagaxi.v`)**
- New module: JTAG-to-AXI4 master bridge on USER4 (CHAIN=4)
- 72-bit pipelined streaming DR — one AXI transaction per scan, zero polling
- 12 commands: single read/write, auto-increment, burst setup/data, config, reset
- Toggle-handshake CDC (TCK → axi_clk) with shadow registers
- Async FIFO (Gray-coded pointers, configurable `FIFO_DEPTH`) for burst reads
- Per-beat toggle handshake for burst writes (no inter-beat timeout)
- Parameters: `ADDR_W`, `DATA_W`, `FIFO_DEPTH`, `TIMEOUT`
- `FIFO_DEPTH` exposed in `FEATURES[23:16]` as `(FIFO_DEPTH-1)` (AXI4 awlen
  convention so 256 fits in 8 bits) and validated at elaboration time
- Vendor wrappers: `fcapz_ejtagaxi_xilinx7.v`, `fcapz_ejtagaxi_intel.v`
- Reusable AXI4 test slave: `tb/axi4_test_slave.v`
- Testbench: `tb/fcapz_ejtagaxi_tb.sv` (29 assertions)
- Hardware-validated on Arty A7-100T

**EJTAG-UART Bridge (`rtl/fcapz_ejtaguart.v`)**
- New module: JTAG-to-UART bridge with bidirectional TX/RX async FIFOs
- 32-bit pipelined DR; commands: NOP, TX_PUSH, RX_POP, TXRX, CONFIG, RESET
- ~1.5 KB/s per direction (Arty A7 / FT2232H / XSDB)
- Use cases: debug console, firmware upload, printf-over-JTAG
- Vendor wrappers: `fcapz_ejtaguart_xilinx7.v`, `fcapz_ejtaguart_intel.v`
- Testbench `tb/fcapz_ejtaguart_tb.sv` and `host/fcapz/ejtaguart.py`
- CLI: `uart-send`, `uart-recv`, `uart-monitor`

**Async FIFO (`rtl/fcapz_async_fifo.v`)**
- Vendor-agnostic async FIFO with two implementations:
  `USE_BEHAV_ASYNC_FIFO=1` portable Gray-coded pointer FIFO (default)
  and `USE_BEHAV_ASYNC_FIFO=0` Xilinx XPM wrapper
- Equivalence testbench `tb/fcapz_async_fifo_equiv_tb.v` +
  `tb/xpm_fifo_async_stub.v` so the XPM branch elaborates and runs
  under iverilog without a vendor install
- Python regression test `tests/test_rtl_fifo_equiv.py` runs the
  equivalence sim via subprocess (skipped when iverilog not on PATH)

**ELA capture engine — advanced features**
- Storage qualification (STOR_QUAL): record only samples that match a
  secondary comparator, +21 LUTs for 10x effective depth on sparse
  signals; new RW registers `SQ_MODE` (0x0030), `SQ_VALUE` (0x0034),
  `SQ_MASK` (0x0038), exposed in Python API and CLI
- Sample decimation (DECIM_EN=1): /N divider, captures every N+1 cycles
- External trigger I/O (EXT_TRIG_EN=1): `trigger_in`/`trigger_out` ports
  with disabled / OR / AND combine modes
- Per-sample timestamp counter (TIMESTAMP_W=32 or 48), exported to VCD
- Segmented memory (NUM_SEGMENTS>1): auto-rearm after each segment
  fills, capturing multiple trigger events in a single run
- Runtime probe mux (PROBE_MUX_W>0): one ELA observes a wide bus and
  selects a SAMPLE_W slice at runtime via `PROBE_SEL` (0x00AC)

**Transport chain selection and hardening**
- `Transport` ABC: `select_chain()`, `raw_dr_scan()`, `raw_dr_scan_batch()`
- Both OpenOCD and hw_server transports support dynamic IR/chain selection
- Verified IR codes on xc7a100t: USER1=0x02, USER2=0x03, USER3=0x22, USER4=0x23
- `XilinxHwServerTransport.connect()` now waits until the FPGA responds
  with valid data after `program()` (configurable `ready_probe_addr` /
  `ready_probe_timeout`); raises `ConnectionError` on timeout with the
  last value, attempt count, and remediation hints
- `fpga_name` and `bitfile` validated against TCL-safe regexes to
  prevent command injection through XSDB session strings
- Parser failures now include the last 10 lines of captured xsdb stderr
  for diagnosability
- `assert` statements in `_cmd()` and `_drain_stderr()` replaced with
  `RuntimeError` (safe under `python -O`)

**Host API hardening**
- `analyzer.configure()` rejects sequences exceeding hardware
  `TRIG_STAGES`
- `ejtagaxi.close()` warns instead of swallowing reset failures silently
- `ejtagaxi.connect()` caches `FIFO_DEPTH` from FEATURES;
  `burst_read`/`burst_write` reject counts exceeding the bridge FIFO
  or AXI4 max (256)
- `rpc._parse_probes()` rejects negative `lsb` / non-positive `width`
- `rpc` validates `stor_qual_mode` in `{0, 1, 2}`
- `events.ProbeDefinition` validates `width > 0` and `lsb >= 0`
- `events.summarize()` always emits `longest_burst` / `first_edge` /
  `last_edge` keys for a stable output schema

**CLI hardening**
- `--port` validated to TCP range 1-65535
- `--timeout` validated `> 0`
- `--count` validated (positive on `axi-dump`/`axi-fill`,
  non-negative on `uart-recv`)
- `--trigger-sequence` JSON / file errors wrapped in
  `argparse.ArgumentTypeError`

**RTL parameter validation**
- `fcapz_ela.v`: `DEPTH` power-of-2, `TRIG_STAGES` 1..4, `SAMPLE_W` 1..256
- `fcapz_ejtagaxi.v`: `FIFO_DEPTH` 1..256 power-of-2
- `fcapz_async_fifo.v`: `DEPTH` power-of-2, `DATA_W >= 1`
- `fcapz_ejtaguart.v`: TX/RX FIFO depths power-of-2, baud / clock ratio
- All checks via `generate` synthesis traps + `initial $error` for sims

**Host software**
- `host/fcapz/ejtagaxi.py`: `EjtagAxiController` — `connect`, `axi_read`,
  `axi_write`, `read_block`, `write_block`, `burst_read`, `burst_write`, `close`
- `write_block`/`read_block` use `raw_dr_scan_batch` for throughput
- CLI: `axi-read`, `axi-write`, `axi-dump`, `axi-fill`, `axi-load`
- RPC: `axi_connect`, `axi_close`, `axi_read`, `axi_write`, `axi_dump`,
  `axi_write_block`
- `EioController` uses `chain=3` and `select_chain()` — EIO hardware access
  unblocked

**Tests**
- 158 Python unit tests (was 91 in v0.1.0): added coverage for
  `Transport` ABC, OpenOCD/XilinxHwServer failure modes, multi-segment
  capture, wide-sample (1-bit and 256-bit) reassembly, sequencer
  bounds, CLI argument validators, trigger-sequence JSON edge cases,
  ProbeDefinition extract edge cases, frequency_estimate corner cases,
  TCL injection rejection, burst FIFO_DEPTH guard rails, async FIFO
  equivalence

**Documentation**
- `CONTRIBUTING.md` with testing guidelines, OpenOCD validation gaps,
  multi-vendor board support
- `docs/specs/register_map.md` updated for SQ, FIFO_DEPTH encoding,
  ext trigger, timestamps, segmented memory, probe mux
- `README.md` linked to `no_commit/specs/` documents

**Build / lint**
- `ruff` added to dev deps and `E501` (line length, max 100) enforced
- All 24 pre-existing line-length violations fixed

### Fixed
- `jtag_trig_value_w`/`jtag_trig_mask_w` width mismatch for `SAMPLE_W != 32`
  (replaced one-line ternary with `generate` block)
- Same width mismatch for SQ and per-stage sequencer registers at
  `SAMPLE_W <= 32` (replication count went negative inside `always` blocks)
- TCL-safe regex split into `_TCL_NAME_RE` (strict, for the JTAG target
  filter inside double quotes) and `_TCL_PATH_RE` (permissive, allows
  backslash for Windows bitfile paths inside TCL braces) — the original
  combined regex rejected every Windows bitfile path

---

## [0.1.0] — 2026-03-16

### Added

**ELA Core (`rtl/fcapz_ela.v`)**
- Dual-port RAM sample buffer (`rtl/dpram.v`) — 78% LUT reduction vs. distributed-RAM shift-register design
- Dual comparators per trigger stage (A and B) with configurable combine logic (A, B, A&B, A|B)
- 9 compare modes per comparator: EQ, NEQ, LT, GT, LEQ, GEQ, RISING, FALLING, CHANGED
- Multi-stage sequencer trigger (configurable `TRIG_STAGES` parameter, default 4)
- Storage qualification (`STOR_QUAL` parameter) — record only samples that match a secondary comparator
- Probe channel mux (`NUM_CHANNELS` parameter) — one ELA instance observes up to 256 mutually exclusive
  signal buses selected at runtime via the `CHAN_SEL` register (0x00A0); channel is latched on ARM
- `ADDR_FEATURES` register (0x003C) exposes `TRIG_STAGES`, `STOR_QUAL`, and `NUM_CHANNELS` to the host
- `ADDR_CHAN_SEL` (0x00A0, RW) and `ADDR_NUM_CHAN` (0x00A4, RO) registers
- Out-of-range `CHAN_SEL` values are clamped to channel 0 on ARM

**EIO Core (`rtl/fcapz_eio.v`)**
- New module: Embedded I/O on JTAG USER3 chain
- Parameters: `IN_W` (input/probe width), `OUT_W` (output/drive width)
- Input probes synchronised to JTAG clock domain via 2-FF CDC
- Output registers live in JTAG clock domain and are driven combinatorially to `probe_out`
- Register map: `EIO_ID` (0x0000), `EIO_IN_W` (0x0004), `EIO_OUT_W` (0x0008),
  `IN[i]` (0x0010 + i×4), `OUT[i]` (0x0100 + i×4)

**Host software**
- `host/fcapz/eio.py`: `EioController` class — `connect`, `read_inputs`, `write_outputs`,
  `read_outputs`, `set_bit`, `get_bit`
- `host/fcapz/analyzer.py`: added `channel` field to `CaptureConfig`, `configure()` now writes
  `CHAN_SEL`; `probe()` now returns `num_channels`

**Simulation**
- `sim/run_sim.py`: multi-testbench runner (iverilog + vvp); supports `fcapz_ela`, `fcapz_eio`, `chan_mux`
- `tb/fcapz_ela_tb.sv`: rewritten with burst-port connections and RESET between tests (17 checks)
- `tb/fcapz_eio_tb.sv`: new testbench for EIO core (18 checks)
- `tb/chan_mux_tb.sv`: new testbench for channel mux feature (8 checks)
- `sim/bscane2_stub.v`: simulation stub for Xilinx BSCANE2 primitive

**CI**
- `.github/workflows/ci.yml`: 4-job pipeline — `lint-python` (ruff), `test-host` (pytest),
  `lint-rtl` (iverilog -Wall), `sim` (run_sim.py)

**Documentation**
- `docs/specs/register_map.md`: full EIO register map, ELA channel-mux registers
- `docs/specs/architecture.md`: EIO block, channel mux, testing section
- `README.md`: EIO instantiation example, Python API example, CI badge table, project structure

### Fixed
- BRAM write-enable alignment: `mem_we_a` was registered (one cycle late), causing the first
  captured sample to be written to address 1 instead of 0. Changed to a combinatorial wire
  `armed && !done && store_sample` so the enable and address align in the same clock cycle.
- BRAM read address: `rd_addr_sync2` was one pipeline stage behind the request-toggle edge,
  causing every first data read to use the previous read's address. Fixed by using `rd_addr_sync1`
  at edge-detection time (address and toggle are set in the same JTAG clock cycle and are
  therefore coherent).
- BRAM read latency: `rd_phase` was 1-bit (2 states), missing one wait cycle for synchronous
  BRAM read latency. Expanded to 2-bit (3 states) so `dout_a` is captured one cycle after
  `addr_a` is presented.
- Overflow flag used stale pre-arm values; changed to use `pretrig_len_sync2` / `posttrig_len_sync2`
  (values already synchronized at arm time).

---
