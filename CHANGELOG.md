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
- Vendor wrappers: `fcapz_ejtagaxi_xilinx7.v`, `fcapz_ejtagaxi_intel.v`
- Reusable AXI4 test slave: `tb/axi4_test_slave.v`
- Testbench: `tb/fcapz_ejtagaxi_tb.sv` (29 assertions)
- Hardware-validated on Arty A7-100T (8/8 tests pass)

**Host software**
- `host/fcapz/ejtagaxi.py`: `EjtagAxiController` — `connect`, `axi_read`,
  `axi_write`, `read_block`, `write_block`, `burst_read`, `burst_write`, `close`
- `write_block`/`read_block` use `raw_dr_scan_batch` for throughput
- CLI: `axi-read`, `axi-write`, `axi-dump`, `axi-fill`, `axi-load`
- RPC: `axi_connect`, `axi_close`, `axi_read`, `axi_write`, `axi_dump`, `axi_write_block`

**Transport chain selection**
- `Transport` ABC: `select_chain()`, `raw_dr_scan()`, `raw_dr_scan_batch()`
- Both OpenOCD and hw_server transports support dynamic IR/chain selection
- Verified IR codes on xc7a100t: USER1=0x02, USER2=0x03, USER3=0x22, USER4=0x23
- `EioController` now uses `chain=3` and `select_chain()` — EIO hardware access unblocked

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
