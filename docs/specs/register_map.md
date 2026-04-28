# JTAG Register Map — v0.3.0

<a id="regmap-top"></a>

## Index

- **[Overview](#regmap-overview)** — scope: per-core JTAG register space vs SoC memory map.
- **ELA** (logic analyzer, USER1 / USER2)
  - [Address map (USER1 control)](#regmap-ela-user1)
  - [SEQ_STAGE_N_CFG encoding](#regmap-seq-cfg)
  - [Compare modes](#regmap-compare-modes)
  - [Bitfields](#regmap-bitfields)
  - [DATA window readout (USER1)](#regmap-data-user1)
  - [Burst readout (USER2)](#regmap-burst-user2)
- **EIO** (USER3)
  - [Core register map](#regmap-eio) — [address table](#regmap-eio-addr), [clock domains](#regmap-eio-clk), [reset behaviour](#regmap-eio-rst)
- **EJTAG-AXI** (USER4)
  - [Bridge DR format](#regmap-ejtag-axi) — [shift-in](#regmap-ejtag-axi-in), [shift-out](#regmap-ejtag-axi-out), [command table](#regmap-ejtag-axi-cmd), [status bits](#regmap-ejtag-axi-status), [config registers (CMD_CONFIG)](#regmap-ejtag-axi-config)
- **EJTAG-UART** (USER4, mutually exclusive with AXI)
  - [32-bit DR format](#regmap-ejtag-uart) — [commands](#regmap-ejtag-uart-cmd), [CONFIG byte map](#regmap-ejtag-uart-config), [shift-out status](#regmap-ejtag-uart-status)

---

<a id="regmap-overview"></a>
## Overview
Registers are memory-mapped via a simple JTAG-accessible address space. All registers are 32-bit.

**Scope:** Each major section below (ELA, EIO, EJTAG-AXI, EJTAG-UART) defines
its **own** register or shift layout. An **address map** table lists
**32-bit word offsets** for the JTAG path described in that section (ELA
USER1 control, EIO USER3, etc.). Those offsets are **not** a single
chip-wide bus map and are **not** the same thing as AXI addresses — except
that EJTAG-AXI commands embed an AXI `addr` in the 72-bit DR, documented
in that bridge’s section.

[↑ Top](#regmap-top)

<a id="regmap-ela-user1"></a>
## ELA core — address map (USER1 control)
- `0x0000`: `VERSION` (ro) - Core identity and version. `[15:0]` is the
  ASCII core identifier `"LA"` (`0x4C41`, Logic Analyzer); `[23:16]` is
  the minor version; `[31:24]` is the major version. Hosts must verify
  the low-16 magic before trusting any other ELA register on this
  chain. Current value: `0x0002_4C41` (major=0, minor=2, id="LA").
- `0x0004`: `CTRL` (rw) - Control (arm, reset)
- `0x0008`: `STATUS` (ro) - Status (armed, triggered, done)
- `0x000C`: `SAMPLE_W` (ro) - Sample width in bits
- `0x0010`: `DEPTH` (ro) - Total capture depth in samples
- `0x0014`: `PRETRIG_LEN` (rw) - Pre-trigger samples
- `0x0018`: `POSTTRIG_LEN` (rw) - Post-trigger samples
- `0x001C`: `CAPTURE_LEN` (ro) - Captured sample count for current/last run
- `0x0020`: `TRIG_MODE` (rw) - Trigger mode
- `0x0024`: `TRIG_VALUE` (rw) - Compare value
- `0x0028`: `TRIG_MASK` (rw) - Mask bits
- `0x002C`: `BURST_PTR` (wo) - Write to initiate burst read from `start_ptr` via USER2.
  `bit[31]` selects the source BRAM: `0` = sample data (default), `1` = timestamp data.
  The host sets `bit[31]=1` when calling `read_timestamp_block()` to burst-read the
  timestamp BRAM through the same USER2 path.
- `0x0030`: `SQ_MODE` (rw) - Storage qualification mode (0=off, 1=value, 2=edge, 3=both; STOR_QUAL=1 only)
- `0x0034`: `SQ_VALUE` (rw) - Storage qualification match value
- `0x0038`: `SQ_MASK` (rw) - Storage qualification match mask
- `0x00D8`: `STARTUP_ARM` (rw) - Bit 0. When set, RESET leaves the core armed instead of idle. `STARTUP_ARM=1` in RTL changes the power-up default of this register so the bitstream can come up pre-armed immediately after configuration.
- `0x00DC`: `TRIG_HOLDOFF` (rw) - Trigger holdoff in sample-clock cycles (0..65535). Trigger hits are ignored for N cycles after ARM and after each segmented auto-rearm. Distinct from `TRIG_DELAY`.
- `0x00D4`: `TRIG_DELAY` (rw) - Post-trigger delay in sample-clock cycles (0..65535). When non-zero, the committed trigger sample is shifted N cycles after the trigger event, compensating for upstream pipeline latency. The pre/post-trigger sample counts and the buffer wrap behavior are unchanged — only the position of the "trigger" anchor moves forward.
- `0x00E0`: `COMPARE_CAPS` (ro) - Compare capability bitmask. Bits 0-8
  report compare modes implemented by this bitstream. Bit 16 reports
  comparator B / dual-combine support when bit 17 is set. Bit 17 marks the
  extended capability schema; older bitstreams omit bit 17 and should be
  treated as dual-compare capable for compatibility. Default lightweight,
  dual-comparator builds report `0x301C3`; `REL_COMPARE=1` dual-comparator
  builds report `0x301FF`; `DUAL_COMPARE=0` clears bit 16.
- `0x003C`: `FEATURES` (ro) - Feature flags: `[3:0]`=TRIG_STAGES, `[4]`=STOR_QUAL
- `0x0040+N*20+0`:  `SEQ_STAGE_N_CFG` (rw) - See encoding below
- `0x0040+N*20+4`:  `SEQ_STAGE_N_VALUE_A` (rw) - Comparator A match value
- `0x0040+N*20+8`:  `SEQ_STAGE_N_MASK_A` (rw) - Comparator A mask
- `0x0040+N*20+12`: `SEQ_STAGE_N_VALUE_B` (rw) - Comparator B match value
- `0x0040+N*20+16`: `SEQ_STAGE_N_MASK_B` (rw) - Comparator B mask

<a id="regmap-seq-cfg"></a>
### SEQ_STAGE_N_CFG encoding
- `[3:0]`   comparator A mode
- `[7:4]`   comparator B mode
- `[9:8]`   combine (0=A only, 1=B only, 2=A AND B, 3=A OR B)
- `[12]`    is_final (1 = this stage fires the trigger)
- `[31:16]` occurrence count target

<a id="regmap-compare-modes"></a>
### Compare modes (4 bits)
Modes 0, 1, 6, 7, and 8 are present in the default lightweight RTL build.
Modes 2-5 require the ELA `REL_COMPARE=1` parameter; otherwise they never
match.
Comparator B and combine modes 1-3 require `DUAL_COMPARE=1`; with
`DUAL_COMPARE=0`, hardware forces A-only comparison and the host rejects
B-combine sequencer configurations.

| Value | Mode | Operation |
|------:|------|-----------|
| 0 | EQ | `(probe & mask) == (value & mask)` |
| 1 | NEQ | `(probe & mask) != (value & mask)` |
| 2 | LT | `(probe & mask) <  (value & mask)` unsigned, requires `REL_COMPARE=1` |
| 3 | GT | `(probe & mask) >  (value & mask)` unsigned, requires `REL_COMPARE=1` |
| 4 | LEQ | `(probe & mask) <= (value & mask)` unsigned, requires `REL_COMPARE=1` |
| 5 | GEQ | `(probe & mask) >= (value & mask)` unsigned, requires `REL_COMPARE=1` |
| 6 | RISING | masked bits: all-zero → non-zero |
| 7 | FALLING | masked bits: non-zero → all-zero |
| 8 | CHANGED | any masked bit changed from previous sample |
- `0x0100`: `DATA` window (ro) - Sample data readout (per-word, via USER1).
  Present when `USER1_DATA_EN=1`; minimal USER2-only builds may disable this
  slow fallback window and return zero for these addresses.

[↑ Top](#regmap-top)

<a id="regmap-bitfields"></a>
## Bitfields
### VERSION
- [31:24] `major` (8-bit)
- [23:16] `minor` (8-bit)
- [15:0]  `core_id` — ASCII `"LA"` (`0x4C41`, Logic Analyzer) for the
  fcapz ELA core. Constant per-instance; never zero on a valid
  bitstream. Hosts use this as the core identity check.

### CTRL
- [0] `arm` (write 1 to arm)
- [1] `reset` (write 1 to reset)
- [31:2] reserved

### STATUS
- [0] `armed`
- [1] `triggered`
- [2] `done`
- [3] `overflow`
- [31:4] reserved

### TRIG_MODE
- [0] `value_match` (1 = compare TRIG_VALUE with mask)
- [1] `edge_detect` (1 = detect rising edge)
- [31:2] reserved

[↑ Top](#regmap-top)

<a id="regmap-data-user1"></a>
## DATA Window Readout (USER1, per-word)
- For SAMPLE_W <= 32: read from `0x0100 + (index * 4)` returns sample `index`, zero-padded.
- For SAMPLE_W > 32: each sample spans `ceil(SAMPLE_W / 32)` consecutive 32-bit words.
  Read `0x0100 + (index * words_per_sample + chunk) * 4` for chunk 0..N-1.
  Chunk 0 = bits[31:0], chunk 1 = bits[63:32], etc.
- Sample order is oldest to newest within the captured window.

[↑ Top](#regmap-top)

<a id="regmap-burst-user2"></a>
## Burst Readout (256-bit DR)
- Write to `BURST_PTR` (0x002C) via USER1 to start a burst from `start_ptr`.
  - `data[30:0]` — ignored (start pointer is latched from the capture state machine).
  - `data[31]` — BRAM select: `0` = sample BRAM, `1` = timestamp BRAM.
- Default Xilinx builds switch IR to USER2 (0x03) and perform 256-bit DR scans.
  Default `SINGLE_CHAIN_BURST=1` builds keep the 256-bit scans on USER1 (0x02).
- **Sample mode** (`bit[31]=0`): each scan returns `256 / SAMPLE_W` packed samples
  (e.g. 32 for 8-bit probes, 8 for 32-bit probes).  The first scan is a priming scan;
  read `N` scans to get `N × (256/SAMPLE_W)` samples.
- **Timestamp mode** (`bit[31]=1`): each scan returns `256 / TIMESTAMP_W` timestamps
  packed LSB-first.  The host uses `read_timestamp_block()` to retrieve timestamps
  via this path and discards the priming scan.
- Read pointer auto-increments; staging buffer is pre-filled during the SHIFT phase.
- Effective delivery rate depends on the host transport and cable;
  the burst path returns multiple words per 256-bit DR scan to amortise round trips.

[↑ Top](#regmap-top)

<a id="regmap-eio"></a>
## EIO Core Register Map (USER3, CHAIN=3)

The EIO core uses the same 49-bit DR protocol as the ELA control interface,
but on a separate JTAG USER chain (CHAIN=3, IR=`0x04`) so it coexists with
ELA USER1 and USER2.

<a id="regmap-eio-addr"></a>
### Address Map
- `0x0000`: `VERSION` (ro) — `{major[7:0], minor[7:0], core_id[15:0]}`,
  where `core_id` is ASCII `"IO"` (`0x494F`). Same encoding scheme as the
  ELA core's VERSION at `0x0000`. Hosts must verify the low-16 magic.
- `0x0004`: `EIO_IN_W` (ro) — Input probe width in bits
- `0x0008`: `EIO_OUT_W` (ro) — Output probe width in bits
- `0x0010 + i×4`: `IN[i]` (ro) — probe_in bits [(i+1)×32−1 : i×32], synchronised to jtag_clk via 2-FF
- `0x0100 + i×4`: `OUT[i]` (rw) — probe_out bits [(i+1)×32−1 : i×32], in jtag_clk domain

Number of IN words = ⌈IN_W / 32⌉; number of OUT words = ⌈OUT_W / 32⌉.

<a id="regmap-eio-clk"></a>
### Clock domains
- `probe_in` may be driven from any fabric clock. It passes through a 2-FF synchroniser into jtag_clk before being readable. For a debug/control tool this is acceptable.
- `probe_out` lives entirely in jtag_clk. If connecting to fast logic in a different clock domain, add a synchroniser stage after the `fcapz_eio` output.

<a id="regmap-eio-rst"></a>
### Reset behaviour
On `jtag_rst`: all OUT registers are cleared to zero. IN registers are not affected (they reflect the synchronised fabric value).

[↑ Top](#regmap-top)

<a id="regmap-ejtag-axi"></a>
## EJTAG-AXI Bridge DR Format (USER4, CHAIN=4)

The EJTAG-AXI bridge uses a 72-bit pipelined streaming DR. Each scan shifts
in a new command and shifts out the result of the **previous** command — zero
polling required.

<a id="regmap-ejtag-axi-in"></a>
### Shift-in (host → FPGA), 72 bits LSB-first

| Bits | Field | Description |
|------|-------|-------------|
| `[31:0]` | addr | AXI address or config register address |
| `[63:32]` | payload | Write data or burst config |
| `[67:64]` | wstrb | AXI write strobes (byte enables) |
| `[71:68]` | cmd | Command code (see table below) |

<a id="regmap-ejtag-axi-out"></a>
### Shift-out (FPGA → host), 72 bits

| Bits | Field | Description |
|------|-------|-------------|
| `[31:0]` | rdata | Read data from previous command |
| `[63:32]` | info | Additional info (address echo, burst count) |
| `[65:64]` | resp | AXI response code (OKAY=0, SLVERR=2, DECERR=3) |
| `[67:66]` | rsvd | Reserved |
| `[71:68]` | status | Status bits (see below) |

<a id="regmap-ejtag-axi-cmd"></a>
### Command table

| Code | Mnemonic | Description |
|-----:|----------|-------------|
| 0x0 | NOP | No operation; retrieves previous result |
| 0x1 | WRITE | Single AXI write at addr |
| 0x2 | READ | Single AXI read at addr |
| 0x3 | WRITE_INC | Write at auto-increment address |
| 0x4 | READ_INC | Read at auto-increment address |
| 0x5 | SET_ADDR | Set auto-increment base address |
| 0x6 | BURST_SETUP | Configure burst (len, size, type in payload) |
| 0x7 | BURST_WDATA | Push one word into burst write buffer |
| 0x8 | BURST_RDATA | Pop one word from burst read FIFO |
| 0x9 | BURST_RSTART | Initiate burst read (addr channel) |
| 0xE | CONFIG | Read bridge config register (addr selects register) |
| 0xF | RESET | Reset bridge state machines |

<a id="regmap-ejtag-axi-status"></a>
### Status bits `[71:68]`

| Bit | Meaning |
|----:|---------|
| 0 | `prev_valid` — rdata/resp are from a completed operation |
| 1 | `busy` — AXI transaction in flight (should not normally be seen) |
| 2 | `error` — sticky, last operation got non-OKAY AXI response |
| 3 | `fifo_notempty` — burst read FIFO has data available |

**Note:** Timeout applies only to AXI handshake waits (wready, bvalid,
arready, rvalid). Inter-beat timing in burst writes is host-paced via
JTAG scans and has no timeout. Burst reads have a 1-scan FIFO pipeline
delay — the host sends a priming `BURST_RDATA` before reading N words.

<a id="regmap-ejtag-axi-config"></a>
### Config registers (CMD_CONFIG)

| Address | Name | Value | Description |
|---------|------|-------|-------------|
| `0x0000` | BRIDGE_ID | `0x454A4158` | ASCII `"EJAX"` — identifies bridge core |
| `0x0004` | VERSION | `0x00010000` | `{major[15:0], minor[15:0]}` |
| `0x002C` | FEATURES | varies | `[7:0]`=ADDR_W, `[15:8]`=DATA_W, `[23:16]`=`FIFO_DEPTH-1` (AXI4 awlen convention; host adds 1 to recover the true depth, so FIFO_DEPTH=256 fits as 0xFF). The bridge cannot buffer bursts longer than `FIFO_DEPTH`; the host rejects oversized `burst_read`/`burst_write` requests. |

[↑ Top](#regmap-top)

<a id="regmap-ejtag-uart"></a>
## EJTAG-UART bridge — 32-bit DR (USER4, CHAIN=4)

Unlike the **ELA** and **EIO** cores, the UART bridge has **no memory-mapped
32-bit register file** addressed like `0x0004`, `0x0008`, ….  The host talks
to it through a **single 32-bit data register (DR)** per JTAG scan: a 4-bit
**command** plus an 8-bit **tx_byte** field on shift-in, and **status + FIFO
metadata + rx_byte** on shift-out.  That is the whole “register” interface.

Optional **identity / build parameters** are read with **`CMD_CONFIG`**: each
CONFIG scan selects one **byte address** (low nibble of `tx_byte`; `0x00`–`0x0F`).
The implementation is **pipelined** (like EJTAG-AXI): the byte returned on a
CONFIG scan is the result of the **previous** CONFIG address; the host issues
four CONFIG scans plus a trailing **NOP** to assemble one 32-bit value (see
`EjtagUartController._config_read_u32` in `host/fcapz/ejtaguart.py`).

See [chapter 08 — EJTAG-UART bridge](../08_ejtag_uart_bridge.md) for wiring,
FIFO behaviour, and the Python API.

<a id="regmap-ejtag-uart-cmd"></a>
### Shift-in (host → FPGA), 32 bits LSB-first

| Bits | Field | Description |
|------|-------|-------------|
| `[7:0]` | tx_byte | TX data for `TX_PUSH` / `TXRX`; **byte address** `[3:0]` for `CONFIG` (upper bits ignored) |
| `[27:8]` | reserved | Must be zero |
| `[31:28]` | cmd | Command code (table below) |

<a id="regmap-ejtag-uart-status"></a>
### Shift-out (FPGA → host), 32 bits

| Bits | Field | Description |
|------|-------|-------------|
| `[7:0]` | rx_byte | RX data (valid when `RX_VALID` set) or CONFIG byte (when `CONFIG` pipeline says so) |
| `[15:8]` | tx_free | Conservative lower bound of TX FIFO free space (bytes) |
| `[23:16]` | reserved | Zero |
| `[24]` | RX_READY | RX FIFO non-empty |
| `[25:27]` | reserved | Zero |
| `[28]` | RX_VALID | `rx_byte` holds a popped RX byte or a valid CONFIG byte |
| `[29]` | TX_FULL | TX FIFO full |
| `[30]` | RX_OVERFLOW | Sticky: RX FIFO overflow (cleared by `RESET`) |
| `[31]` | FRAME_ERR | Sticky: UART framing / parity error (cleared by `RESET`) |

### Command codes

| Code | Mnemonic | Description |
|-----:|----------|-------------|
| `0x0` | NOP | No FIFO action; read status / `tx_free` |
| `0x1` | TX_PUSH | Queue `tx_byte` into TX FIFO if not full |
| `0x2` | RX_POP | Pop one byte from RX FIFO; data appears on a **later** scan (pipelined) |
| `0x3` | TXRX | TX push and RX pop in one update |
| `0xE` | CONFIG | Select config byte `tx_byte[3:0]` for the **next** scan’s captured result |
| `0xF` | RESET | Reset bridge + flush FIFOs (host should follow with NOPs to clock reset) |

<a id="regmap-ejtag-uart-config"></a>
### CONFIG byte map (`CMD_CONFIG`, byte address in `tx_byte[3:0]`)

Byte addresses `0x0`–`0xF` decode a **16-byte** config window (aliases repeat
if more than 4 bits are set; RTL only uses the low nibble).  Four consecutive
bytes form one little-endian 32-bit word as read by the host stack:

| Byte addr | Assembled word | Name | Content |
|----------:|----------------|------|---------|
| `0x0`–`0x3` | word @ 0 | **UART_ID** | `0x454A5552` — ASCII **`EJUR`** (bridge identity). Hosts must match before trusting the core. |
| `0x4`–`0x7` | word @ 4 | **VERSION** | `[31:16]` = major, `[15:0]` = minor (RTL default `0x00010000` → v1.0). |
| `0x8`–`0xB` | word @ 8 | **FEATURES** | Packed build parameters from `fcapz_ejtaguart.v`: `[31:30]` = `PARITY` (0 none, 1 even, 2 odd); `[29:16]` = `TX_FIFO_DEPTH` (14 bits); `[15:2]` = `RX_FIFO_DEPTH` (14 bits); `[1:0]` = reserved (`2'b00`). Depths are the module parameters (power of 2). |
| `0xC`–`0xF` | word @ 12 | **BAUD_DIV** | Integer **uart_clk cycles per UART bit** (`CLK_HZ / BAUD_RATE` as synthesized). |

[↑ Top](#regmap-top)
