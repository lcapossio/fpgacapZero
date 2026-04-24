# 06 — EIO core

> **Goal**: understand the Embedded I/O core — the simplest of the
> four — and how to use it from the host stack to read fabric
> signals and drive them from your laptop in real time, without
> resynthesising the bitstream.

## What EIO is

EIO is a **JTAG-accessible register file** with two halves:

- **`probe_in`** — an `IN_W`-bit input bus.  Connect any signals
  from your fabric.  The host can read them at any time.
- **`probe_out`** — an `OUT_W`-bit output bus.  The host writes a
  value via JTAG; the core drives that value out to your fabric.

That is the entire core.  No trigger, no buffer, no waveform — just
"what is the current value of these signals" and "drive these
signals to this value".  Think of it as the in-system equivalent of
sticking a multimeter probe on a signal, except for digital values
and with the ability to drive a signal as well as observe it.

The reference Arty A7 design wires `probe_in` to the pushbuttons plus
a 1 Hz low-nibble counter, and wires `probe_out[3:0]` to the LEDs.
Higher `probe_out` bits are used as fabric-side debug controls for the
hardware tests: bit 4 is the manual ELA external trigger, bit 5 asks
the Arty top to emit an early one-shot trigger 2 cycles after the ELA
enters `ARMED`, and bit 6 asks it to assert a late trigger starting 8
cycles after `ARMED`.  After programming, you can:

```bash
$ fcapz eio-read
0xA7
$ fcapz eio-write 0x55
wrote 0x55
```

— and watch the LEDs change to `0x55` immediately, no rebuild.

### Arty A7 + desktop GUI

The board has **no separate “input LEDs”**: the **Inputs** row in the
EIO dock is a read-only mirror of `probe_in` in the GUI. Turn on
**Poll inputs** so it updates. The **four green LEDs** are driven only
from **Outputs** (`probe_out[3:0]`). You must click **Attach EIO**
first (chain **3** for [`arty_a7_top.v`](../examples/arty_a7/arty_a7_top.v)).
If the LEDs still ignore writes, confirm the FPGA is programmed with
that reference bitstream and rebuild if you changed the top-level
(after programming, `fcapz eio-write 0x0F` from the CLI is a quick
sanity check).  On this reference top, EIO bits above 3 do **not**
drive LEDs; they are intentionally reserved for internal trigger-test
plumbing used by the Arty hardware integration suite.

## Architecture

```
                       +------------------+
                       |  fcapz_eio       |
fabric → probe_in[*] → | (2-FF sync into  |  <-- jtag_clk
                       |  jtag_clk)       |
                       |                  |
                       |  Register file:  |  <-- USER3 (BSCANE2)
                       |  0x0000 VERSION  |  <-- 49-bit DR protocol
                       |  0x0004 IN_W     |
                       |  0x0008 OUT_W    |
                       |  0x0010+ IN[i]   |
                       |  0x0100+ OUT[i]  |
                       |                  |
                       |  Output regs     |
fabric ← probe_out[*]← | (jtag_clk)       |
                       +------------------+
```

The whole core is in [`../rtl/fcapz_eio.v`](../rtl/fcapz_eio.v) and
the Xilinx wrapper is
[`../rtl/fcapz_eio_xilinx7.v`](../rtl/fcapz_eio_xilinx7.v) (or
`_xilinxus.v`, `_ecp5.v`, `_intel.v`, `_gowin.v` for other vendors).

## Clock domains

EIO has a small but important CDC story:

- **`probe_in`** can come from any fabric clock domain.  The core
  uses a **2-FF synchroniser** to bring it into the `jtag_clk`
  domain before the host reads it.  This is a debug tool, so
  whole-bus synchronisation (rather than per-bit Gray coding) is
  acceptable — bits can be sampled half a fabric cycle apart, but
  for "what's the current state of this signal" that's fine.

- **`probe_out`** lives entirely in the `jtag_clk` domain.  It's
  driven combinatorially from a register inside the core.  If you
  consume `probe_out` in a fast fabric clock domain, you should
  add your own synchroniser stage **after** the EIO output:

  ```verilog
  reg [OUT_W-1:0] probe_out_sync1, probe_out_sync2;
  always @(posedge fast_clk) begin
      probe_out_sync1 <= probe_out;
      probe_out_sync2 <= probe_out_sync1;
  end
  // use probe_out_sync2 in your fast logic
  ```

  Why doesn't the core do this for you?  Because we don't know what
  your fast clock is.  The synchroniser cells need to live in your
  domain, not ours.

- **`probe_out` reset** — `jtag_rst` clears all `OUT[i]` registers
  to zero.  This means after a JTAG TAP reset (very rare in normal
  use) the host's last-written value is lost.  In practice
  `jtag_rst` is only asserted during fpga configuration, so this
  matches the "boots to zero" behavior you want.

## Identity check (new in v0.3.0)

EIO's register at `0x0000` is the per-core `VERSION` register with
the same `{major, minor, core_id}` layout as the ELA:

```
[31:24] = FCAPZ_VERSION_MAJOR  (= 0x00 in v0.3.0)
[23:16] = FCAPZ_VERSION_MINOR  (= 0x03)
[15:0]  = FCAPZ_EIO_CORE_ID   = ASCII "IO" = 0x494F
```

`EioController.connect()` reads this register and asserts that
`VERSION[15:0] == 0x494F` before touching any other EIO register on
the chain.  If the magic is wrong (no bitstream loaded, wrong chain,
wrong bitstream), it raises `RuntimeError` with a remediation hint.
This is the same defensive pattern as `Analyzer.probe()` — it
catches the failure at the API boundary instead of letting the
caller silently read garbage.

The decoded `version_major / version_minor / core_id` are exposed
on the controller instance after `connect()`:

```python
from fcapz.eio import EioController
eio = EioController(transport, chain=3)
eio.connect()
print(eio.version_major, eio.version_minor, hex(eio.core_id))
# 0 3 0x494f
```

## Host API: `EioController`

The host class is [`fcapz.eio.EioController`](../host/fcapz/eio.py).

### Constructing

```python
from fcapz import XilinxHwServerTransport
from fcapz.eio import EioController

transport = XilinxHwServerTransport(port=3121, fpga_name="xc7a100t")
eio = EioController(transport, chain=3)
eio.connect()
```

`chain=3` is the default — change it only if you instantiated the
EIO wrapper with a non-default `CHAIN` parameter (see
[chapter 04](04_rtl_integration.md)).  The host's `chain` argument
must match the RTL `CHAIN` parameter.

After `connect()`, the controller has cached `IN_W` and `OUT_W` from
the bitstream's identity registers, so subsequent reads/writes know
exactly how many words to scan.

### Reading inputs

```python
value = eio.read_inputs()        # returns the full IN_W bits as int
```

`read_inputs()` returns the entire input bus as one Python integer
(LSB = bit 0).  For an 8-bit `IN_W` you get `0..255`; for a 64-bit
`IN_W` you get `0..(2**64 - 1)`.  The result is masked to the exact
`IN_W` width — bits beyond `IN_W` are guaranteed zero.

### Reading a single bit

```python
bit5 = eio.get_bit(5)            # 0 or 1
```

Equivalent to `(eio.read_inputs() >> 5) & 1`, but more readable.
Raises `ValueError` if `bit` is out of range.

### Writing outputs

```python
eio.write_outputs(0xA5)          # set probe_out to 0xA5
```

Writes the entire output bus.  Bits beyond `OUT_W` are silently
masked off — you cannot accidentally drive bits that don't exist.

The write is committed to the FPGA the moment the JTAG scan
completes (typically <1 ms via hw_server).  No "transaction commit"
or staging — what you write is what the fabric sees.

### Reading the current output value back

```python
current = eio.read_outputs()     # returns the OUT_W-bit value last written
```

This reads the live hardware register, not a Python-side cache, so
if the FPGA was reset or another fcapz session wrote to it, you see
the real value.

### Setting / clearing one bit

```python
eio.set_bit(3, 1)                # set bit 3 to 1
eio.set_bit(3, 0)                # clear bit 3
```

Implemented as a **read-modify-write** under the hood:
`read_outputs() → modify the bit → write_outputs()`.  This is **not
atomic** with respect to other host sessions — if two `fcapz`
processes are both poking the same EIO at the same time, you can
race.  In practice EIO is for interactive debug, not concurrent
control plane, so this is fine.

### Closing

```python
eio.close()
```

Releases the transport.  After `close()`, all the `EioController`
methods raise `RuntimeError`.  You can construct a new
`EioController` against the same transport later.

## Worked example: a runtime control register

Suppose your design has a state machine you want to be able to
reset, enable, and configure from the host without rebuilding.
Wire EIO into your top-level:

```verilog
wire [7:0]  eio_in;
wire [7:0]  eio_out;

fcapz_eio_xilinx7 #(.IN_W(8), .OUT_W(8)) u_eio (
    .probe_in  (eio_in),
    .probe_out (eio_out)
);

// Inputs the host can observe:
//   eio_in[0]   = state machine "idle" indicator
//   eio_in[1]   = state machine "error" indicator
//   eio_in[7:2] = state machine current state (6-bit one-hot)
assign eio_in = {fsm_state[5:0], fsm_error, fsm_idle};

// Outputs the host can drive:
//   eio_out[0]   = soft reset (active high)
//   eio_out[1]   = enable
//   eio_out[7:2] = mode select
assign fsm_soft_rst = eio_out[0];
assign fsm_enable   = eio_out[1];
assign fsm_mode     = eio_out[7:2];
```

Now from the host:

```python
from fcapz import XilinxHwServerTransport
from fcapz.eio import EioController

t = XilinxHwServerTransport(port=3121, fpga_name="xc7a100t")
eio = EioController(t, chain=3)
eio.connect()

# Pulse soft reset
eio.set_bit(0, 1)              # assert reset
eio.set_bit(0, 0)              # deassert reset

# Enable + mode 5
eio.write_outputs((5 << 2) | 0x02)

# Poll until the state machine reaches state 3
import time
while True:
    inputs = eio.read_inputs()
    state = (inputs >> 2) & 0x3F
    print(f"state={state}, idle={inputs & 1}, error={(inputs >> 1) & 1}")
    if state == 3:
        break
    time.sleep(0.1)

eio.close()
```

This is the **bread and butter** use case for EIO and the most
common reason to add it to a design.

## CLI usage

For one-off interactive use, the CLI is faster than writing a
Python script:

```bash
# Read the input bus
$ fcapz eio-read
0xA7

# Write the output bus
$ fcapz eio-write 0x55
wrote 0x55

# Read back what you just wrote
$ fcapz eio-read
0xA7
```

(`eio-read` always reads `probe_in`, never `probe_out`.  The CLI
doesn't have a separate "read outputs" command because the use case
is rare; if you need it, use the Python API.)

The chain is `--chain 3` by default; override with `--chain N` if
your bitstream put EIO somewhere else:

```bash
fcapz eio-read --chain 4
```

## RPC usage

Same operations are exposed over the JSON-RPC server:

```json
{"cmd":"eio_connect","backend":"hw_server","port":3121,"chain":3}
{"cmd":"eio_read"}
{"cmd":"eio_write","value":85}
{"cmd":"eio_close"}
```

See [chapter 11](11_rpc_server.md) for the full RPC protocol.

## GUI usage

The desktop GUI ([chapter 12](12_gui.md)) has an EIO panel with
**Poll inputs** (and an ms-period preset combo), read-only input
indicators, and **per-bit output toggles**, so you can watch inputs
update and drive outputs interactively.  This is the easiest way to
use EIO if you have the GUI installed.

## Resource usage

EIO is tiny.  For a typical 8-in / 8-out config on Artix-7:

- Logic: ~30 LUTs (most of which is the JTAG register interface
  shared with the ELA pattern)
- FFs: `IN_W * 2` (for the synchroniser) + `OUT_W` (for the
  output register) = `2*8 + 8 = 24` for the example above
- BRAM: 0
- DSP: 0

For wider buses (`IN_W = OUT_W = 64`), it's ~80 LUTs and ~192 FFs.
Still trivially small.

## Testing

The Arty A7 hardware integration tests in
[`../examples/arty_a7/test_hw_integration.py`](../examples/arty_a7/test_hw_integration.py)
exercise EIO end-to-end:

| Test | What it covers |
|---|---|
| `test_eio_probe` | `connect()` reads identity + `IN_W` / `OUT_W` |
| `test_read_counter` | `read_inputs()` returns non-zero (probe_in is the counter) |
| `test_write_read_outputs` | `write_outputs(x)` followed by `read_outputs()` returns `x` |
| `test_set_clear_bit` | `set_bit()` modifies one bit without disturbing others |
| `test_output_roundtrip_all_bits` | every bit position works |
| `test_write_zero_outputs` | clears all bits |

The same Arty reference EIO outputs are also used by the ELA hardware
tests as deterministic control hooks:

- `probe_out[4]`: manual external trigger source for the ELA
- `probe_out[5]`: request a one-shot external trigger 2 sample clocks
  after the ELA enters `ARMED`
- `probe_out[6]`: request an external trigger level beginning 8 sample
  clocks after the ELA enters `ARMED`

Those bits are not part of the generic EIO core contract; they are
just how the checked-in Arty top-level chooses to use its spare output
bits for board-level validation.

The unit tests in [`../tests/test_host_stack.py`](../tests/test_host_stack.py)
cover the controller against a `FakeVioTransport` (no hardware
needed) including the new core_id magic check.

## What's next

- [Chapter 07 — EJTAG-AXI bridge](07_ejtag_axi_bridge.md): the
  bigger sibling — full AXI4 master access from JTAG.
- [Chapter 09 — Python API](09_python_api.md): full
  `EioController` API reference.
- [Chapter 10 — CLI reference](10_cli_reference.md): the `eio-read`
  / `eio-write` / `eio-probe` subcommands.
