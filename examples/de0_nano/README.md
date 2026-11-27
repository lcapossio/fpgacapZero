# DE0-Nano Reference Design

This example targets the Terasic DE0-Nano (Cyclone IV E **EP4CE22F17C6**) through
its onboard USB-Blaster. It instantiates the fpgacapZero Intel ELA and EIO
wrappers (`sld_virtual_jtag`).

## Files

| File | Purpose |
| --- | --- |
| `de0_nano_top.v` | Top level: ELA on a free-running 8-bit counter and KEY[1:0], EIO on LED/SW/KEY |
| `de0_nano.qpf`, `de0_nano.qsf` | Quartus project, device and pin assignments |
| `de0_nano.sdc` | 50 MHz clock constraint |
| `build_de0_nano.tcl` | Quartus batch build |
| `test_hw_integration.py` | Hardware tests: probe, counter capture with trigger, EIO |

## JTAG instances

| Instance | Core |
| --- | --- |
| 1 | ELA control/register path |
| 2 | ELA burst readout |
| 3 | EIO (in: `{2'b00, KEY[1:0], SW[3:0]}`, out: `LED[7:0]`) |

## Build, program, test

Tested with Quartus II 13.1 Web Edition (Linux). Newer Quartus Prime Lite
releases with Cyclone IV E support should work the same way.

```bash
cd examples/de0_nano
quartus_sh -t build_de0_nano.tcl                       # output_files/de0_nano.sof
quartus_pgm -m jtag -o "p;output_files/de0_nano.sof"   # program over USB-Blaster
fcapz --backend usb_blaster --tap auto probe
python -m pytest test_hw_integration.py -v             # programs the board first
```

`jtagconfig` should list the board as `USB-Blaster [...]` with device
`020F30DD EP3C25/EP4CE22`.  With more than one cable attached, set
`FPGACAP_QUARTUS_HARDWARE` to the board's cable name as `jtagconfig` prints it
(and pass `-c` / `--hardware` by hand): the tests then program and test that
cable only, so no other board is reprogrammed.

## Results

| | |
| --- | --- |
| Board / part / IDCODE | Terasic DE0-Nano, EP4CE22F17C6, `0x020F30DD` |
| Toolchain | Quartus II 13.1 (Build 162) |
| Transport | `usb_blaster` (`quartus_stp`), onboard USB-Blaster |
| Resources | 2,186 / 22,320 LEs, 1,636 registers, 10,240 memory bits |
| Hardware tests (PR #85 version) | 3 passed (probe, capture: trigger at counter 0x40 lands on sample 8 and the counter increments by 1 per sample, EIO output write and input read) |
| Current `test_hw_integration.py` | Not yet run on this board: it now programs through the target under test and reads the EIO outputs back |
