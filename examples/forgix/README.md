<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
-->

# Forgix (Efinix Trion T8F49 + RP2354)

fpgacapZero on the [Forgix board](https://forgix.tech/) — a Teensy-footprint
board pairing an Efinix Trion T8F49 with a Raspberry Pi RP2354.

## Why this board is different

**The Forgix board gives the FPGA fabric no JTAG whatsoever.** Every other
fpgacapZero target reaches the core through a hard JTAG TAP; here there is
nothing to reach:

- The Trion T8 has no configuration flash. The RP2354 reconfigures it from
  scratch at every power-up over a **passive SPI** link that is **write-only** —
  there is no MISO (`FPGA_PIN_MISO` is `-1` in the stock firmware).
- The T8's JTAG pins are not bonded out to a header pin, a test point, or a
  connector. The board's only debug connector (J2, Tag-Connect TC2030) is
  **ARM SWD for the RP2354**, not FPGA JTAG.

So [`rtl/fcapz_ela_efinix.v`](../../rtl/fcapz_ela_efinix.v), which binds the
T8's hard JTAG User TAP blocks, **cannot be used on this board** — those TAPs
are unreachable. This example uses
[`rtl/fcapz_ela_uart.v`](../../rtl/fcapz_ela_uart.v) instead, which drives the
identical ELA core from
[`fcapz_uart_tap`](../../rtl/fcapz_uart_tap.v), a virtual TAP fed by a serial
byte stream. Host side is
`fcapz.transport.SerialTapTransport`.

Nothing about that path is Forgix- or Efinix-specific; any JTAG-less board can
use it.

## Wiring: two jumpers required

Of the 24 header pins, 18 go straight to the Trion fabric (`PIN.4`–`PIN.6`,
`PIN.9`–`PIN.23`, where the label number is the header pin number) and 6 go to
the RP2354. **The RP2354 and the FPGA are not connected to each other except by
the configuration SPI**, so the UART link has to be closed at the header with
two jumper wires:

| From (RP2354) | Header pin | To (FPGA fabric) | Signal |
|---|---:|---|---|
| `RP.UART0_TX` (GPIO12) | 7 | any fabric pin, e.g. `PIN.9` | `uart_rxd` |
| `RP.UART0_RX` (GPIO13) | 8 | any fabric pin, e.g. `PIN.10` | `uart_txd` |

Pins 9 and 10 sit next to 7 and 8, so the jumpers are short. Any other fabric
pin works — just keep the Efinity pin assignment and the firmware defines in
agreement.

> GPIO12/13 are UART0 TX/RX in RP2350 silicon and are the only RP2354 UART pins
> on the header not already taken by the configuration SPI (which uses GPIO1–6
> and GPIO19). The header's other UART pair is labelled `RP.UART1_RX/TX` at
> GPIO8/9, where the schematic labels read inverted with respect to the silicon
> function map — avoid it unless you have checked it on your board.

## Firmware: the RP2354 has to become a bridge

The stock bitstream loader speaks a framed `FLDR` protocol on USB CDC and has
no passthrough mode, so fcapz cannot reach the fabric through it. The patch in
[`firmware/`](firmware/) adds one: after the FPGA reports `DONE`, the RP2354
stops framing and becomes a transparent USB-CDC ↔ UART pipe.

**Nothing in the upstream repository is modified.** The patch is vendored here
and applied to a local copy, pinned to an upstream revision:

```sh
python examples/forgix/firmware/apply_patch.py          # fetch + patch locally
python examples/forgix/firmware/apply_patch.py --check  # verify only
```

Then build with the Pico SDK and flash the resulting `.uf2` (BOOTSEL mode):

```sh
cmake -S <dest>/firmware/pico -B <dest>/firmware/pico/build \
      -DPICO_SDK_PATH="$PICO_SDK_PATH" -DPICO_BOARD=pico2
cmake --build <dest>/firmware/pico/build
```

Bridge mode is entered after a successful programming cycle and left only by
resetting the board. That is deliberate: the T8 has to be reprogrammed at every
power-up anyway, so a reset naturally returns you to loader mode — and it means
no escape sequence exists that an fcapz scan payload could accidentally spell.

Override the defaults at configure time if you wire the jumpers elsewhere:
`FCAPZ_BRIDGE_PIN_TX`, `FCAPZ_BRIDGE_PIN_RX`, `FCAPZ_BRIDGE_BAUD_HZ`,
`FCAPZ_BRIDGE_ENABLE=0` to build the stock loader.

## Building the FPGA design

[`forgix_top.v`](forgix_top.v) instantiates `fcapz_ela_uart` with a
free-running counter as the probe source, so a capture should read back a ramp.

Build it in Efinity for the **T8F49I2X**, assigning `uart_rxd` / `uart_txd` to
the fabric pins you jumpered, then load the resulting SPI-passive `.hex`.

> **Set `CLK_HZ` to your board's actual oscillator frequency.** The baud divider
> is derived from it. The Forgix oscillator (ECS-2520MV) is a family rather than
> one frequency, and a wrong value produces a garbled link rather than a build
> error. `BAUD_RATE` must match `FCAPZ_BRIDGE_BAUD_HZ` in the firmware.

## Connecting from the host

```python
from fcapz.transport import SerialTapTransport
from fcapz.analyzer import Analyzer

t = SerialTapTransport("COM16", baudrate=1_000_000)   # /dev/ttyACM0 on Linux
t.connect()
print(t.num_chains, t.max_dr_bits)                    # identity from the bridge
```

Needs pyserial: `pip install 'fpgacapzero[serial]'`.

`connect()` probes the bridge for its `FCZU` identity before any register
access, so pointing it at the wrong port fails with a clear message instead of
returning garbage.

## Fitting the core in a T8

The T8F49 has 7,384 LEs, 25 × 5-kbit BRAMs and 8 DSPs. Converting the
canonical xc7a100t figures in
[`docs/specs/architecture.md`](../../docs/specs/architecture.md#resource-usage-xc7a100t)
to Trion LUT4 logic elements (roughly ×1.8, since a slice LUT is a LUT6):

| Config | xc7a100t | Estimated T8 LEs | Share of T8 |
|---|---|---:|---:|
| EIO 8/8 | ~30 LUT / 24 FF | ~60 | <1 % |
| ELA 8b × 1024, A-only, smallest | 596 LUT / 779 FF | ~1,100 | ~15 % |
| ELA 8b × 1024, dual comparator | 2,021 LUT / 1,725 FF | ~3,600 | ~50 % |
| ELA 32b × 1024, dual comparator | 2,472 LUT / 2,099 FF | ~4,400 | ~60 % |

EIO is free in practice. A modest ELA leaves room for a real user design; the
wide dual-comparator configs take most of the part. `forgix_top.v` therefore
defaults to `DUAL_COMPARE=0`.

These are **estimates by conversion, not Efinity results** — the published rows
also include JTAG TAP plumbing that `fcapz_uart_tap` replaces (a UART plus
framing and scan FSM, roughly a wash). Treat the first Efinity run as the real
number.

## Throughput

The UART is not the bottleneck it looks like. The T8's entire 122.88 kbit of
BRAM is ~15 kB, so a full capture readback at 1 Mbaud takes well under a second.

## Status

The RTL and host transport are covered by simulation and unit tests
([`tb/fcapz_uart_tap_tb.sv`](../../tb/fcapz_uart_tap_tb.sv),
[`tests/test_serial_tap_transport.py`](../../tests/test_serial_tap_transport.py)).

**Hardware validation is pending**, as is the firmware patch — it is generated
against the pinned upstream and verified to apply, but has not been compiled
with the Pico SDK or run on a board. The oscillator frequency, the Efinity pin
assignment, and achievable `Fmax` on Trion all need a real build to confirm.
