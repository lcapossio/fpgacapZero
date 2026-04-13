# Transport API — v0.3.0

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
```

## Implementations

### `XilinxHwServerTransport` (primary, hardware-validated)
- Persistent XSDB session via `subprocess.Popen` with stdin/stdout pipes.
- Uses `-bits` format for `drshift` (standard JTAG bit ordering).
- **Do not use `-hex` format** — XSDB applies a non-standard byte/nibble
  transformation that scrambles bit positions.
- Burst `read_block` via USER2 256-bit DR: `floor(256/SAMPLE_W)` samples per
  scan.  How fast samples stream depends on the adapter and how much
  per-scan overhead the transport adds (batched vs single DR).
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

#### Burst data readout (USER2)
256-bit DR via BSCANE2 USER2 (IR = `0x03`).  Each scan returns
`256 / SAMPLE_W` packed samples with auto-incrementing read pointer.

Flow (single `jtag sequence`):
1. IR shift to USER1, DR shift to write `BURST_PTR` (0x002C) — triggers
   staging buffer fill from `start_ptr`.
2. Idle 40 TCK cycles (staging buffer needs ~33 cycles to load).
3. IR shift to USER2, then N × 256-bit DR scans with capture.
4. Parse: each captured 256-bit token contains packed samples LSB-first.

### `OpenOcdTransport`
- Connects to OpenOCD TCL socket (default port 6666).
- Uses `irscan`/`drscan`/`runtest` commands.
- Not yet hardware-validated (pending test with FT2232).

### `VendorStubTransport`
- Placeholder for future non-Xilinx backends.
- Raises `NotImplementedError` on all operations.
