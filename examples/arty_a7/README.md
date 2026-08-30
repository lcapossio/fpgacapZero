# Arty A7-100T Reference Design

This example is the hardware-validation design for fpgacapZero on the
Digilent Arty A7-100T (`xc7a100tcsg324-1`). It instantiates the Xilinx
7-series wrappers for:

- two managed ELA slots on USER1
- two EIO slots on USER1
- an AXI monitor on USER2, tapping the shared AXI bus
- a MicroBlaze soft CPU with its debug module (MDM) on USER3
- one EJTAG-AXI bridge on USER4

The design is intentionally self-stimulating, so you can build it, program the
board, and exercise the debug cores without adding any external user logic.

### Shared AXI bus + MicroBlaze

A small MicroBlaze subsystem (block design under `mb/`) puts a real CPU on the
same AXI bus as the EJTAG-AXI bridge. Both masters are merged by an in-BD
SmartConnect onto one AXI4 bus that drives a 32-word `axi4_test_slave` and is
passively tapped by the AXI monitor, so the monitor captures **real CPU bus
traffic** as well as host traffic:

```
MicroBlaze M_AXI_DP ─┐
                     ├─ SmartConnect ─ shared bus ─┬─ axi4_test_slave
EJTAG-AXI (USER4) ───┘   (USER3 MDM debug)         └─ AXI monitor (USER2)
```

The whole AXI fabric runs on a dedicated 100 MHz clock (the counter-capture
ELAs stay at 150/130 MHz). Baked-in firmware (`mb/fw/`) is host-gated: it writes
a known pattern (`0xCAFEF00D`/`0x1234ABCD`) to slave words 16/17 only while the
host raises a go flag (word 31), and otherwise just polls — so the CPU stays
write-quiet during the other hardware tests, which use slave words 0..15.

## Files

| File | Purpose |
| --- | --- |
| `arty_a7_top.v` | Top-level reference design |
| `mb/create_mb_bd.tcl` | Generates the MicroBlaze block design (CPU + LMB + MDM@USER3 + SmartConnect) |
| `mb/build_fw.tcl` | Compiles the CPU firmware with the MicroBlaze GCC shipped with Vivado |
| `mb/fw/` | Firmware source (`boot.S`, `main.c`, `lscript.ld`) baked into the LMB BRAM |
| `arty_a7.xdc` | Arty A7-100T pin and clock constraints |
| `build.py` | Preferred Vivado batch-build launcher |
| `build_arty.tcl` | Vivado project/script used by `build.py` |
| `arty_a7.cfg` | OpenOCD config for the onboard USB-JTAG adapter |
| `arty_a7_hs3.cfg` | OpenOCD config for an external Digilent HS3 cable |
| `test_hw_integration.py` | Hardware integration regression tests |
| `arty_a7_top.bit` | Generated/reference bitstream |

## Board I/O

- `clk` uses the Arty A7 100 MHz oscillator.
- `btn[0]` resets the generated sample clock domains.
- `btn[3:0]` are visible through EIO probe inputs.
- `led[3:0]` are driven from EIO0 `probe_out[3:0]`.

The design generates independent 150 MHz and 130 MHz sample domains. ELA0
captures an 8-bit counter in the 150 MHz domain; ELA1 captures a separate
counter in the 130 MHz domain. EIO0 `probe_out[4]` also feeds the ELA external
trigger input, which lets host software create deterministic trigger edges.

## Build

From the repository root:

```sh
python examples/arty_a7/build.py
```

The build writes Vivado outputs under `vivado/fpgacapZero_arty/` and copies
the bitstream to:

```text
examples/arty_a7/arty_a7_top.bit
```

If `vivado` is not on `PATH`, pass it explicitly:

```sh
python examples/arty_a7/build.py --vivado /path/to/vivado
```

## Connect With hw_server

For Xilinx boards, `hw_server` is the most tested path:

```sh
hw_server -d
```

Program the bitstream and probe the debug cores:

```sh
fcapz --backend hw_server --port 3121 --tap xc7a100t \
  --program examples/arty_a7/arty_a7_top.bit probe
```

Run a simple ELA capture:

```sh
fcapz --backend hw_server --port 3121 --tap xc7a100t \
  --program examples/arty_a7/arty_a7_top.bit \
  capture --pretrigger 64 --posttrigger 192 \
  --trigger-value 66 --trigger-mask 0xff \
  --out capture.json --format json
```

Exercise the EIO LEDs:

```sh
fcapz --backend hw_server --port 3121 --tap xc7a100t \
  eio-write --chain 1 --instance 2 0x0f
fcapz --backend hw_server --port 3121 --tap xc7a100t \
  eio-read --chain 1 --instance 2
```

## Connect With OpenOCD

Start OpenOCD with the onboard adapter config:

```sh
openocd -f examples/arty_a7/arty_a7.cfg
```

Then use the OpenOCD backend from another terminal:

```sh
fcapz --backend openocd --host 127.0.0.1 --port 6666 \
  --tap xc7a100t.tap probe
```

For a Digilent HS3 cable, use `arty_a7_hs3.cfg` instead.

OpenOCD does not program the FPGA through the fpgacapZero transport, so program
`arty_a7_top.bit` separately before running host commands.

## Hardware Tests

With an Arty A7 connected, the bitstream built, and `hw_server` running:

```sh
python -m pytest examples/arty_a7/test_hw_integration.py -v
```

To run the same tests through OpenOCD, start OpenOCD first and select that
backend:

```sh
openocd -f examples/arty_a7/arty_a7.cfg
FPGACAP_BACKEND=openocd python -m pytest examples/arty_a7/test_hw_integration.py -v
```

To skip hardware tests in an environment without the board:

```sh
FPGACAP_SKIP_HW=1 python -m pytest examples/arty_a7/test_hw_integration.py -v
```

## More Detail

- Main README quick start: [`../../README.md`](../../README.md)
- First capture walkthrough: [`../../docs/03_first_capture.md`](../../docs/03_first_capture.md)
- Transport notes: [`../../docs/14_transports.md`](../../docs/14_transports.md)
