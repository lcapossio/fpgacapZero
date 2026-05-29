# DE25-Nano Reference Design

This example targets the Terasic DE25-Nano Agilex 5 board connected through
the onboard USB-Blaster III cable. It instantiates the fpgacapZero Intel ELA
and EIO wrappers using `sld_virtual_jtag`.

## Files

| File | Purpose |
| --- | --- |
| `de25_nano_top.v` | Top-level reference design |
| `de25_nano.qsf` | Quartus device, top-level, and pin assignments |
| `de25_nano.sdc` | Timing constraints |
| `build_de25_nano.tcl` | Quartus batch build script |
| `build.py` | Preferred build launcher |
| `run_hw_tests.py` | Build, program, probe, and optional capture runner |

## JTAG Instances

| Instance | Core |
| --- | --- |
| 1 | ELA control/register path |
| 2 | ELA burst readout |
| 3 | EIO |

## Board I/O

- `CLOCK1_50` drives the 50 MHz sample domain.
- `KEY[1:0]`, `SW[3:0]`, and counter bits are visible through EIO input probes.
- `LEDR[7:0]` are active-low and driven from EIO outputs, with `LEDR[0]`
  also showing a heartbeat.

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
