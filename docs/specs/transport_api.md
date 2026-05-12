# Transport API — v0.4.0

## Purpose
Abstracts access to the JTAG register map across different backends (Xilinx `hw_server`, OpenOCD, other vendors).

## Interface (Python)
```python
class Transport(ABC):
    def connect() -> None
    def close() -> None
    def read_reg(addr: int) -> int
    def write_reg(addr: int, value: int) -> None
    def read_block(addr: int, words: int) -> list[int]

    # Optional — implement for timestamp burst readback acceleration:
    def read_timestamp_block(addr: int, words: int, timestamp_width: int) -> list[int]
```

`read_timestamp_block` is an **optional extension method**, not part of the ABC
contract.  The host checks for it via `getattr(transport, "read_timestamp_block",
None)` and falls back to `read_block` if absent.  Transports that support the
256-bit burst path should implement it to avoid the slow per-word USER1 readback
path for timestamp data.

## Implementations

### `XilinxHwServerTransport` (primary, hardware-validated)
- Persistent XSDB session via `subprocess.Popen` with stdin/stdout pipes.
- Uses `-bits` format for `drshift` (standard JTAG bit ordering).
- **Do not use `-hex` format** — XSDB applies a non-standard byte/nibble
  transformation that scrambles bit positions.
- Burst `read_block` via USER2 256-bit DR: `floor(256/SAMPLE_W)` samples per
  scan.  How fast samples stream depends on the adapter and how much
  per-scan overhead the transport adds (batched vs single DR).
- `read_timestamp_block(addr, words, timestamp_width)` — timestamp burst via the
  same USER2 path.  Sets `BURST_PTR` bit[31]=1 to select the timestamp BRAM.
  No priming scan required; the first 256-bit capture already holds valid data.
  Returns `words` integers of width `timestamp_width` bits each.
- Falls back to USER1 single-sequence pipelined reads for non-DATA addresses.
- All operations within a read use a single `jtag sequence` object to prevent
  stale-read bugs from inter-sequence timing gaps.
- Automatic FPGA programming via `bitfile=` constructor parameter.
- Default port: 3121.

#### JTAG protocol
49-bit DR via BSCANE2 USER1 (IR = `0x02`):
- `bits[31:0]` = data (write data TX / read data RX)
- `bits[47:32]` = addr (16-bit register address)
- `bits[48]` = rnw (1 = write, 0 = read)

A read requires two DR scans separated by idle TCK cycles:
1. Scan 1: shifts in the read frame (sets `reg_addr`, `reg_rd_en`).
2. Idle 20 TCK cycles for register read latency.
3. Scan 2: CAPTURE loads `reg_rdata` into `sr[31:0]`; TDO captures the value.

A write requires one DR scan followed by idle cycles:
1. Scan: shifts in write frame (`rnw=1`, `addr`, `data`).
2. Idle 20 TCK cycles for the write to propagate.

#### Burst data readout
Default Xilinx builds use a 256-bit DR via BSCANE2 USER2 (IR = `0x03`).
Default `SINGLE_CHAIN_BURST=1` builds use the same 256-bit packets on USER1
(IR = `0x02`) after the `BURST_PTR` write.  Each scan returns
`256 / SAMPLE_W` packed samples with auto-incrementing read pointer.

Flow (single `jtag sequence`):
For `SINGLE_CHAIN_BURST=1`, the burst-chain steps below remain on USER1
instead of switching to USER2.
1. IR shift to USER1, DR shift to write `BURST_PTR` (0x002C) — triggers
   staging buffer fill from `start_ptr`.
2. Idle 40 TCK cycles (staging buffer needs ~33 cycles to load).
3. IR shift to USER2, then N × 256-bit DR scans with capture.
4. Parse: each captured 256-bit token contains packed samples LSB-first.

### `OpenOcdTransport`
- Connects to OpenOCD TCL socket (default port 6666).
- Uses `irscan`/`drscan`/`runtest` commands.
- Not yet hardware-validated (pending test with FT2232).

### `QuartusStpTransport`
- Connects to a persistent `quartus_stp -s` subprocess for Intel/Altera
  USB-Blaster access.
- Uses Quartus virtual JTAG Tcl commands against `sld_virtual_jtag`:
  `device_virtual_ir_shift`, `device_virtual_dr_shift`, and
  `device_run_test_idle`.
- `select_chain()` / `raw_dr_scan(..., chain=...)` use the zero-based
  `sld_virtual_jtag` `instance_index`, not the 1-based USER-chain convention
  used by Xilinx/OpenOCD transports.
- USB cable discovery and device open were exercised on a DE25-Nano with
  Quartus Prime Lite 25.1std. Full fcapz register access still needs hardware
  validation with a bitstream that instantiates the Intel `sld_virtual_jtag`
  wrapper.

### `VendorStubTransport`
- Placeholder for future non-Xilinx backends.
- Raises `NotImplementedError` on all operations.
