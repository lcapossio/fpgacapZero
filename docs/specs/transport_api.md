# Transport API — v0.4.0

## Purpose
Abstracts access to the JTAG register map across different backends (AMD/Xilinx
`hw_server`, OpenOCD, Quartus USB-Blaster, other vendors).

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

### Burst errors and options

- `BurstUnavailableError(RuntimeError)` — the transport cannot burst this
  request at all, raised before any scan (burst off, a non-DATA base, or a
  sample width outside 1..256).  The analyzer then reads the register window.
- `BurstIntegrityError(RuntimeError)` — a burst ran but returned the wrong
  number of scans or values, its priming scan was not the burst header the
  analyzer expected, or the hub or slot was reset under it (epochs changed).
  Raised to the caller.
- Any other exception from a burst propagates; nothing reads around it.
- `burst: bool = True` (constructor of the hw_server and Quartus transports) —
  declares whether the bitstream has a burst path.  It is never probed:
  `False` reads every capture through the register window.
- `burst_start_sync: bool` (attribute, default `False`) — set by the
  analyzer before a burst on a core manager with two or more slots and
  `MGR_CAPS` bit 2 clear.  The transport then adds, ahead of the prime scan
  and in the same JTAG transaction, one burst-length scan that is not
  returned and a second `BURST_PTR` write (see `MGR_CAPS` in
  [`register_map.md`](register_map.md)).
- `burst_expect: BurstExpectation | None` (attribute, default `None`) — set
  by the analyzer before a burst through a core manager with `MGR_CAPS` bit 4:
  what the burst header must say.  `BurstExpectation(slot, start_ptr,
  sample_w, tlr_count=None)` holds the slot, `SEG_START` and `SAMPLE_W` read
  just before the burst, and, on a hub with `MGR_CAPS` bit 6, `MGR_TLR_COUNT`.
  The transport decodes the priming scan as a `BurstHeader` and raises
  `BurstIntegrityError` unless it is a header for that slot, window, start
  pointer and sample width with an even slot epoch; another session's
  `MGR_OWNER` token is logged as a warning.  The header is kept in
  `last_burst_header`, and the analyzer compares its epochs with `MGR_EPOCH`
  / `MGR_SLOT_EPOCH`, and `tlr_count` with `MGR_TLR_COUNT`, after the burst.
  The analyzer clears both after every read.
- `bursts_data_window(*, timestamp=False) -> bool` — whether
  `read_block(0x0100, ...)` (with `timestamp`, `read_timestamp_block`) runs a
  burst rather than reading the register window.  A window read ends at
  `data_window_end`, so the analyzer pages it through `DATA_OFFSET` when it
  would pass the end; a burst does not.  The base returns `False`; the
  hw_server and Quartus transports return whether they would burst, and
  decide their own `read_block` with it.
- `release_manager_ownership()` — writes 0 to `MGR_OWNER` on each manager
  where this session wrote its token and the token is still there.  The
  token is written the first time the session selects a slot on a manager
  with `MGR_CAPS` bit 3; a different nonzero token found there is logged as a
  warning, not obeyed.  The hw_server, Quartus and OpenOCD transports call
  it from `close()` (not `close_fast()`), unless a scan is in flight on
  another thread.

### Core-manager slot selection

- `slot_scope(selection)` — context manager.  Every register access in the
  body reaches `selection`'s slot (`SlotSelection(chain, active_addr,
  slot)`), or carries no selection when it is `None`.  It holds
  `transaction_lock()` for the body; the selection belongs to the calling
  thread and is restored on exit.  `Analyzer`, `EioController` and
  `CoreManager` enter it for every operation.
- `atomic_slot_select: bool` (class attribute) — `True` when the backend
  writes `MGR_ACTIVE` at the head of each backend operation in the scope
  that reaches a slot, in the same uninterrupted transaction as the access.
  Then a second process on the same cable cannot redirect an access by
  moving `MGR_ACTIVE`.  Accesses to the manager's own block
  (`0xF000`-`0xF0FF`) are never prefixed.  Otherwise the scope selects once
  on entry with `select_manager_instance_cached`, which another process can
  undo between operations.  The hw_server, Quartus and OpenOCD transports
  are atomic.
- `read_regs_after_write(write_addr, value, addrs)` — a selector write and
  the reads it selects (`MGR_DESC_INDEX` and the slot descriptor), as one
  backend operation on an atomic backend.

Read-modify-write sequences (EIO `set_bit`, ELA configure then arm) are
still several operations: per-operation selection keeps each one on its
slot, but two processes driving the same slot can still interleave.

## Implementations

### `XilinxHwServerTransport` (primary, hardware-validated)
- Persistent XSDB session via `subprocess.Popen` with stdin/stdout pipes.
- Uses `-bits` format for `drshift` (standard JTAG bit ordering).
- **Do not use `-hex` format** — XSDB applies a non-standard byte/nibble
  transformation that scrambles bit positions.
- Burst `read_block` via the configured 256-bit burst path: `floor(256/SAMPLE_W)`
  samples per scan.  Default single-chain builds keep the burst scans on the
  selected ELA control chain; legacy two-chain AMD/Xilinx builds use USER2.
  How fast samples stream depends on the adapter and how much per-scan overhead
  the transport adds (batched vs single DR).
- `read_timestamp_block(addr, words, timestamp_width)` — timestamp burst via the
  same configured burst path.  Sets `BURST_PTR` bit[31]=1 to select the timestamp BRAM.
  Like the sample burst, the first 256-bit scan primes staging and is discarded.
  Returns `words` integers of width `timestamp_width` bits each.
- Falls back to control-chain single-sequence pipelined reads for non-DATA addresses.
- All operations within a read use a single `jtag sequence` object to prevent
  stale-read bugs from inter-sequence timing gaps.
- Inside a `slot_scope`, each sequence that reaches a slot starts with an
  uncaptured `MGR_ACTIVE` write and the register-write idle (20 TCKs, 100 in
  `-register` mode): one per register access, per block-read chunk and its
  flush, per pipelined read, and once before `BURST_PTR` in a burst, never
  between burst scans.  The captured output is unchanged.
- Automatic FPGA programming via `bitfile=` constructor parameter.
- Default port: 3121.

#### JTAG protocol
49-bit DR via the selected ELA control BSCAN USER chain:
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
Legacy two-chain AMD/Xilinx builds use a 256-bit DR via BSCANE2 USER2 (IR = `0x03`).
Default `SINGLE_CHAIN_BURST=1` builds use the same 256-bit packets on the
selected ELA control chain after the `BURST_PTR` write. Each scan returns
`256 / SAMPLE_W` packed samples with auto-incrementing read pointer.

Flow (single `jtag sequence`):
For `SINGLE_CHAIN_BURST=1`, the burst-chain steps below remain on the
selected ELA control chain instead of switching to USER2.
1. IR shift to the ELA control chain, DR shift to write `BURST_PTR` (0x002C) — triggers
   staging buffer fill from `start_ptr`.
2. Idle 40 TCK cycles (staging buffer needs ~33 cycles to load).
3. Perform N × 256-bit DR scans with capture. Legacy two-chain builds switch
   IR to USER2 first; default single-chain builds stay on the selected ELA
   control chain.
4. Parse: each captured 256-bit token contains packed samples LSB-first.

### `OpenOcdTransport`
- Connects to OpenOCD TCL socket (default port 6666).
- Uses `irscan`/`drscan`/`runtest` commands.
- Hardware-validated on Gowin BRS-100-GW1NR9. The AMD/Xilinx/OpenOCD path is still
  less exercised than the `hw_server` backend.
- Each register access is one Tcl command line (a read is
  `irscan; drscan; runtest; irscan; drscan`), which OpenOCD's Tcl server runs
  before serving another client.  Inside a `slot_scope`, a line that reaches
  a slot starts with the `MGR_ACTIVE` write and 20 idle TCKs.

### `QuartusStpTransport`
- Connects to a persistent `quartus_stp -s` subprocess for Intel/Altera
  USB-Blaster access.
- Uses Quartus virtual JTAG Tcl commands against `sld_virtual_jtag`:
  `device_virtual_ir_shift`, `device_virtual_dr_shift`, and
  `device_run_test_idle`.
- `select_chain()` / `raw_dr_scan(..., chain=...)` use the
  `sld_virtual_jtag` `instance_index` configured by the Intel RTL wrapper's
  `CHAIN` parameter. The default fcapz Intel control path is instance 1.
- USB cable discovery, device open, `fcapz probe`, EIO access, and ELA capture
  were exercised on a DE25-Nano with Quartus Prime Pro 26.1 and an Intel
  `sld_virtual_jtag` fcapz bitstream.  Quartus Lite is expected to work with
  the same Tcl commands, but this branch was not re-validated on Lite.
- Inside a `slot_scope`, each locked script that reaches a slot starts, after
  `device_lock`, with the `MGR_ACTIVE` write and 20 idle TCKs: one per
  register access and window read, and once before `BURST_PTR` in a burst.
  A burst on the control chain ends with a `VERSION` read and 258 idle TCKs.

### `VendorStubTransport`
- Placeholder for future vendor backends.
- Raises `NotImplementedError` on all operations.
