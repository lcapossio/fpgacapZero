# DE25-Nano Reference Design

This example targets the Terasic DE25-Nano Agilex 5 board connected through
the onboard USB-Blaster III cable. It instantiates the fpgacapZero Intel ELA
and EIO wrappers, plus the Intel EJTAG-AXI wrapper, using `sld_virtual_jtag`.

## Files

| File | Purpose |
| --- | --- |
| `de25_nano_top.v` | Top-level reference design (RTL traffic generator) |
| `de25_nano.qsf` | Quartus device, top-level, and pin assignments |
| `de25_nano.sdc` | Timing constraints |
| `build_de25_nano.tcl` | Quartus batch build script |
| `build.py` | Preferred build launcher |
| `axi4_traffic_gen.v` | Self-stimulating AXI master for the AXI monitor |
| `de25_nano_vex_top.v` | Top-level VexRiscv variant — same cores, open-source CPU |
| `vex/vex_cpu.v` | VexRiscv core + Wishbone arbiter/decode + 64 KB BRAM + WB→AXI4 bridge |
| `vex/get_deps.py` | Fetches the SHA-pinned `VexRiscv_Lite.v` core (first build only) |
| `vex/fw/` | Free-running bus pattern firmware (`boot.S`, `main.c`, `link.ld`, `build_fw.py`) |
| `build_de25_nano_vex.py` | Fetch core + build firmware + Quartus build launcher (VexRiscv top) |
| `build_de25_nano_vex.tcl` | Quartus batch build script used by `build_de25_nano_vex.py` |
| `run_hw_tests.py` | Build, program, probe, and optional capture runner |
| `test_hw_integration.py` | Pytest hardware integration regression tests (both tops; `FPGACAP_BITSTREAM_VARIANT=vex` targets the VexRiscv one) |

## JTAG Instances

| Instance | Core |
| --- | --- |
| 1 | ELA control/register path |
| 2 | ELA burst readout |
| 3 | EIO |
| 4 | EJTAG-AXI bridge |
| 5 | AXI monitor (taps the muxed bus) |

## VexRiscv variant (open-source CPU)

A second top-level, `de25_nano_vex_top`, is a **drop-in** for the default design
— same debug cores, same monitor mux — except the self-stimulating master on the
monitored AXI bus is an **open-source VexRiscv** (RV32I) instead of the RTL
`axi4_traffic_gen`, so the AXI monitor captures **real CPU bus traffic**. The
CPU drives its own dedicated `axi4_test_slave`, independent of the EJTAG-AXI
bridge's slave, so the bridge read/write tests are unaffected.

Its firmware (`vex/fw/main.c`) is free-running (the CPU's slave is not reachable
from the host, so there is no host go flag): it continuously issues clean
write/write/read bursts to `0x4000_0000`, giving the monitor live traffic to
trigger on (`aw_hs`) with no host present, while never touching an error/hang
address (so it cannot forge an `any_err` event). Because the observable bus
contract matches the RTL generator, **the full `test_hw_integration.py` suite
runs unchanged against the vex bitstream**. The `vex/` subsystem is pure RTL
(`vex_cpu.v` wraps the fetched `VexRiscv_Lite.v` with a Wishbone→AXI bridge and
a 64 KB `$readmemh` BRAM); `get_deps.py` fetches the pinned core on the first
build.

## Board I/O

- `CLOCK1_50` drives the 50 MHz sample domain.
- `KEY[1:0]`, `SW[3:0]`, and counter bits are visible through EIO input probes.
- `LEDR[7:0]` are active-low and driven from EIO outputs, with `LEDR[0]`
  also showing a heartbeat.
- EIO output bits 4-6 feed the ELA external-trigger test hooks.

Pin assignments come from the Terasic DE25-Nano user manual:
`CLOCK1_50` is `PIN_V16`, `KEY[0]`/`KEY[1]` are `PIN_C8`/`PIN_C11`,
switches are `PIN_DK24`, `PIN_DD24`, `PIN_DD27`, `PIN_DF27`, and user LEDs
are `PIN_DF35`, `PIN_DJ32`, `PIN_DN22`, `PIN_DP23`, `PIN_DN25`, `PIN_DP25`,
`PIN_DJ27`, `PIN_DP30`.

## Build

```sh
python examples/de25_nano/build.py
```

The generated bitstream is:

```text
examples/de25_nano/output_files/de25_nano_fcapz.sof
```

### VexRiscv variant

The open-source variant needs a RISC-V GCC toolchain (for the firmware) and, on
the first build only, network access (to fetch the pinned VexRiscv core):

```sh
RISCV_PREFIX=riscv64-unknown-elf- python examples/de25_nano/build_de25_nano_vex.py
```

Set `RISCV_PREFIX` to your toolchain prefix. The build fetches
`vex/VexRiscv_Lite.v`, compiles the firmware into `vex/fw/fw.mem`, then runs
Quartus and writes `examples/de25_nano/output_files/de25_nano_vex_fcapz.sof`.

Program the board and run the hardware suite against it. The pytest suite does
not program the FPGA, so use the runner (it builds, programs, and pytests the
selected variant in one go):

```sh
python examples/de25_nano/run_hw_tests.py \
  --hardware "DE25-Nano [USB-1]" --variant vex --pytest
```

Or program it yourself and run pytest directly (it applies unchanged, so every
test runs):

```sh
quartus_pgm -c "DE25-Nano [USB-1]" -m jtag \
  -o "p;examples/de25_nano/output_files/de25_nano_vex_fcapz.sof@1"
FPGACAP_BITSTREAM_VARIANT=vex python -m pytest examples/de25_nano/test_hw_integration.py -v
```

## Build, Program, And Test

```sh
python examples/de25_nano/run_hw_tests.py \
  --hardware "DE25-Nano [USB-1]" \
  --jtagconfig \
  --capture
```

The runner programs the generated `.sof`, probes the ELA on instance 1,
smoke-tests EIO on instance 3, and optionally captures a short waveform.

To reuse an already-built and programmed bitstream:

```sh
python examples/de25_nano/run_hw_tests.py \
  --hardware "DE25-Nano [USB-1]" \
  --no-build \
  --no-program \
  --capture
```

## Hardware Regression Tests

To run the pytest suite after building and programming:

```sh
python examples/de25_nano/run_hw_tests.py \
  --hardware "DE25-Nano [USB-1]" \
  --pytest
```

The pytest suite mirrors the Arty A7 hardware regression coverage where the
DE25-Nano design has equivalent Intel/Altera plumbing: ELA identity/registers,
captures, trigger delay, decimation, timestamps, segmented capture, EIO
read/write, and EJTAG-AXI read/write/burst/error paths.

## Soak Test

For a 10-minute board soak, reuse the programmed bitstream and run repeated
ELA/EIO/AXI checks in one Quartus session:

```sh
python examples/de25_nano/run_hw_tests.py \
  --hardware "DE25-Nano [USB-1]" \
  --no-build \
  --no-program \
  --soak-seconds 600
```
