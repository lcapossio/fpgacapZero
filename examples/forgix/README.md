<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
-->

# Forgix (Efinix Trion T8F49 + RP2354)

fpgacapZero on the [Forgix board](https://forgix.tech/) — a Teensy-footprint
board pairing an Efinix Trion T8F49 with a Raspberry Pi RP2354.

This is a worked example of the generic UART TAP path, not a special case: the
RTL and the host transport it uses are board- and vendor-agnostic. See
[`docs/14_transports.md`](../../docs/14_transports.md#tapbridgetransport) for
the general mechanism.

## Why this board needs it

**The Forgix board gives the FPGA fabric no JTAG whatsoever.**

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
identical ELA core from a virtual TAP fed by a byte stream.

## Wiring: none

The bridge **reuses the configuration SPI pins**, which sit idle once `DONE`
is high. No jumpers, no extra cable — just the USB-C lead.

| Pin | During configuration | After `DONE` | Fabric signal |
|---|---|---|---|
| RP2354 GPIO2 → FPGA **CCK** | SPI clock | UART0 TX | `uart_rxd` |
| RP2354 GPIO3 → FPGA **CDI** | SPI data in | UART0 RX | `uart_txd` |

This works because **CCK and CDI are dual-purpose configuration pins**: Efinix
[AN006](https://www.efinixinc.com/docs/an006-configuring-trion-fpgas-v6.6.pdf)
Table 3 states they may be used as general I/O in user mode. Note that
**CDONE is a _dedicated_ pin** (Table 2) and cannot be reused — which is why
the return path is CDI rather than DONE.

Assign `uart_rxd` to the CCK pin and `uart_txd` to the CDI pin in the Efinity
Interface Designer.

> **Pad function gotcha.** GPIO2/GPIO3 reach UART0 TX/RX only through pad
> function **11** (`UART_AUX`). The ordinary `GPIO_FUNC_UART` (function 2) maps
> to UART0's **CTS/RTS** on these two pads, so using it yields a dead link
> rather than a build error. The patch handles this.

> **Contention window.** During configuration the RP2354 drives CDI; once the
> T8 enters user mode the fabric drives it too. That is an output-vs-output
> conflict, not just noise, so the firmware calls `spi_deinit()` and reassigns
> the pads **the instant `DONE` is confirmed** — before the ACK is sent and
> before the USB flush, either of which can block. The changeover is still not
> simultaneous at both ends, so expect a few junk bytes right after
> programming; send a `CMD_INFO` first and discard what precedes its reply.

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

Override the defaults at configure time: `FCAPZ_BRIDGE_PIN_TX`,
`FCAPZ_BRIDGE_PIN_RX`, `FCAPZ_BRIDGE_BAUD_HZ`, or `FCAPZ_BRIDGE_ENABLE=0` to
build the stock loader.

## Building the FPGA design

[`forgix_top.v`](forgix_top.v) instantiates `fcapz_ela_uart` with a
free-running counter as the probe source, so a capture should read back a ramp.

Build it in Efinity for the **T8F49**, assigning `uart_rxd`/`uart_txd` to the
CCK/CDI pins in the Interface Designer, then load the resulting SPI-passive
`.hex`.

Add [`forgix.sdc`](forgix.sdc) as the project's constraint file. It is not
optional: `tap_tck` is generated inside the fabric, and Efinity does not infer
a clock for it — without the `create_generated_clock` in there, that domain
(roughly 940 flops plus both sample-RAM ports) is placed and routed but never
timed, and the report looks clean because it only covers `clk_in`.

> **Set `CLK_HZ` to your board's actual oscillator frequency.** The baud divider
> is derived from it. The Forgix oscillator (ECS-2520MV) is a family rather than
> one frequency, and a wrong value produces a garbled link rather than a build
> error. `BAUD_RATE` must match `FCAPZ_BRIDGE_BAUD_HZ` in the firmware.

## Connecting from the host

```python
from fcapz.transport import SerialTapTransport

t = SerialTapTransport("COM16", baudrate=1_000_000)   # /dev/ttyACM0 on Linux
t.connect()
print(t.num_chains, t.max_dr_bits)                    # identity from the bridge
```

Needs pyserial: `pip install 'fpgacapzero[serial]'`.

`connect()` probes the bridge for its `FCZU` identity before any register
access, so pointing it at the wrong port fails with a clear message instead of
returning garbage.

## Fitting the core in a T8

Measured, not estimated — Efinity 2025.1, T8F49, C2 timing model,
`optimization_level=TIMING_3`, placer seed 5, with [`forgix.sdc`](forgix.sdc)
and the defaults in [`forgix_top.v`](forgix_top.v) (8-bit x 1024,
`DUAL_COMPARE=0`, `BURST_W=64`):

| | Used | Available | Share |
|---|---:|---:|---:|
| Logic elements | 2,174 | 7,384 | 29.4 % |
| — LUTs/adders | 1,542 | 7,384 | 20.9 % |
| — registers | 1,140 | 5,280 | 21.6 % |
| Memory blocks | 2 | 24 | 8.3 % |
| Multipliers | 0 | 8 | 0 % |

The sample buffer maps to `EFX_RAM_5K` blocks, not LUT memory. Timing closes at
50 MHz: `clk_in` reaches 51.8 MHz, and the `tap_tck` domain 36.6 MHz against
the 25 MHz it needs.

> **The placer seed matters here.** The critical path is inside `fcapz_ela`,
> and across seeds 1/3/5/9/12 `clk_in` lands anywhere between 49.4 and
> 51.8 MHz — so some seeds miss 50 MHz by well under 1 %. If a build fails
> timing by a tenth of a nanosecond, try another seed before changing the
> design.

Where it goes:

| Block | LUTs | FFs |
|---|---:|---:|
| `fcapz_ela` | 552 | 639 |
| `fcapz_tap_bridge` | 388 | 184 |
| `jtag_burst_read` | 188 | 158 |
| `jtag_reg_iface` | 81 | 99 |

The transport used to cost more than the analyser it serves. It no longer does.

Getting there took three rounds against the real tool, and every one of them
was a wide structure in front of the 256-bit scan buffer that reads innocently
in Verilog:

- `scan_buf >> (BUF_W - scan_width)`, to justify the captured word, inferred a
  full 256-bit **barrel shifter**.
- `scan_buf[byte_index*8 +: 8] <= rx_data`, to place a payload byte, inferred a
  **32-way byte demux** across all 256 bits.
- Writing `scan_buf` from ten places in the FSM gave every bit a **wide
  next-state mux**, since each write site is a separate function of the buffer.

The first two are now shift registers with a few filler cycles; the third is
one decoded datapath with a 3:1 mux and a shared fill value. Together they were
**5,901 LE and Fmax 31 MHz** versus 2,744 LE and 51 MHz — the ELA core never
moved.

The fourth round was not a structure at all but a parameter. `BURST_W` was 256,
copied from the hard-TAP wrappers, and it sets both this module's scan buffer
and `jtag_burst_read`'s `sr`/`staging` pair. Once `CMD_BREAD` existed a wide DR
stopped buying throughput (see below), so it went to 64 — the floor set by the
49-bit control frame. That alone was **2,744 -> 2,174 LE and 1,726 -> 1,140
registers**, most of it out of the burst engine.

Turning `DUAL_COMPARE` back on, or widening `SAMPLE_W`, adds to the `fcapz_ela`
row; the other three are fixed cost.

## Throughput

The UART is not the bottleneck it looks like. The T8's entire 122.88 kbit of
BRAM is ~15 kB, so a full capture readback at 1 Mbaud takes well under a second.

Readback goes through the ELA's burst chain (chain 2), which returns 8 8-bit
samples per 64-bit scan — about **1.05 bytes per sample** on the wire, against
~48 for the per-word control-chain path. A 1024-sample capture is ~1.07 kB
rather than ~49 kB, or about 11 ms at 1 Mbaud.

Widening the scan does not improve that. Every scan in a `CMD_BREAD` batch is
packed samples under a single shared header, so the per-sample cost is
essentially the sample itself at any width; going to 256 bits would cost
~1,092 bytes rather than ~1,068, because the priming scan that gets discarded
grows too. Width is a pure area decision on this transport, which is why it is
64 here and 256 on the hard-TAP wrappers.

## Status

The RTL and host transport are covered by simulation and unit tests
([`tb/fcapz_uart_tap_tb.sv`](../../tb/fcapz_uart_tap_tb.sv),
[`tests/test_serial_tap_transport.py`](../../tests/test_serial_tap_transport.py)).

The design has been built through Efinity synthesis and place-and-route (see
the numbers above), so the fit and `Fmax` questions are answered.

**Hardware validation is still pending**, as is the firmware patch — it is
generated against the pinned upstream and verified to apply, but has not been
compiled with the Pico SDK or run on a board. The oscillator frequency and the
Interface Designer pin assignment still need a real board to confirm.
