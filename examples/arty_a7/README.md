# Arty A7-100T Reference Design

This example is the hardware-validation design for fpgacapZero on the
Digilent Arty A7-100T (`xc7a100tcsg324-1`). It instantiates the Xilinx
7-series wrappers for:

- two managed ELA slots on USER1
- two EIO slots on USER1
- one EJTAG-AXI bridge on USER4 connected to an AXI4 test slave

The design is intentionally self-stimulating, so you can build it, program the
board, and exercise the debug cores without adding any external user logic.

## Files

| File | Purpose |
| --- | --- |
| `arty_a7_top.v` | Top-level reference design |
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
