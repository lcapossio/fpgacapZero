# Arty S7-25 Reference Design

This example targets the Digilent Arty S7-25 (Spartan-7 **XC7S25-1CSGA324**)
through its onboard USB-JTAG. It instantiates the fpgacapZero Xilinx 7-series
ELA and EIO wrappers (`BSCANE2`).

## Files

| File | Purpose |
| --- | --- |
| `arty_s7_top.v` | Top level: ELA on a free-running 8-bit counter and btn[3:0], EIO on led/sw/btn |
| `arty_s7.xdc` | Pins (from Digilent's Arty-S7-25 master XDC) and the 12 MHz clock |
| `build_arty_s7.tcl` | Vivado non-project batch build |
| `test_hw_integration.py` | Hardware tests: probe, counter capture with trigger, EIO |

`sw[3]` (M5) sits on the 1.35 V bank 34 and is not used: a 3.3 V standard
there fails DRC, and M5 is also that bank's external VREF pin.  The XDC still
sets the bank's internal VREF (0.675 V), as Digilent's master XDC does.

## JTAG chains

| USER chain | Core |
| --- | --- |
| 1 | ELA control/register path and burst readout (single-chain burst, the default) |
| 2 | free |
| 3 | EIO (in: `{btn[3:0], 1'b0, sw[2:0]}`, out: `led[3:0]` in bits 3:0) |

## Build, program, test

Tested with Vivado 2025.2.1 (Linux).

```bash
cd examples/arty_s7
vivado -mode batch -source build_arty_s7.tcl       # arty_s7_fcapz.bit, reports in out/
hw_server &                                        # Vivado hardware server
fcapz --backend hw_server --tap xc7s25 --program arty_s7_fcapz.bit probe
python -m pytest test_hw_integration.py -v         # programs the board first
```

The build stops before the bitstream if routed timing fails, the JTAG clock
(TCK, constrained at 30 MHz) included.  The tests program the board through
the same hw_server target they then use (`FPGACAP_HW_TARGET`), so on a bench
with several boards no other board is reprogrammed.

The direct FTDI backend (`--backend ftdi`) also fits this board's FT2232H,
through FTDI's D2XX library or libusb (`--hardware usb:<serial>`); the results
below used `hw_server`.

## Results

| | |
| --- | --- |
| Board / part / IDCODE | Digilent Arty S7-25, XC7S25-1CSGA324, `0x037C4093` |
| Toolchain | Vivado 2025.2.1 |
| Transport | `hw_server`, onboard Digilent USB-JTAG |
| Resources | 1,195 LUTs, 1,558 registers, 0.5 BRAM tile (RAMB18) |
| `test_hw_integration.py` | 3 passed (probe, capture: trigger at counter 0x40 lands on sample 8 and the counter increments by 1 per sample, EIO write/read) |
