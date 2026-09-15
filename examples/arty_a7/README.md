# Arty A7-100T Reference Design

This example is the hardware-validation design for fpgacapZero on the
Digilent Arty A7-100T (`xc7a100tcsg324-1`). It instantiates the Xilinx
7-series wrappers for:

- two managed ELA slots on USER1
- two EIO slots on USER1
- an AXI monitor on USER2, tapping the shared AXI bus
- an open-source VexRiscv soft CPU on the shared bus (USER3 free — the legacy
  MicroBlaze variant instead puts its debug module there)
- one EJTAG-AXI bridge on USER4

The design is intentionally self-stimulating, so you can build it, program the
board, and exercise the debug cores without adding any external user logic.

### VexRiscv shared AXI bus (default)

The default top-level, `arty_a7_vex_top`, puts an **open-source VexRiscv**
(RV32I) CPU on the same AXI bus as the EJTAG-AXI bridge. The two masters are
merged by the vendor-neutral `fcapz_axi_interconnect` (a generated 2×1 AXI4
crossbar shared with the DE25-Nano example) onto one 32-word `axi4_test_slave`
that the AXI monitor passively taps, so the monitor captures **real CPU bus
traffic** as well as host traffic — with no proprietary CPU, licence, `mb-gcc`,
or vendor block design:

```
VexRiscv (M_CPU) ─┐
                  ├─ fcapz_axi_interconnect ─ shared bus ─┬─ axi4_test_slave
EJTAG-AXI (USER4) ┘   (USER3 free, no MDM)                └─ AXI monitor (USER2)
```

The whole AXI fabric runs on a dedicated 100 MHz clock (the counter-capture
ELAs stay at 150/130 MHz). The CPU subsystem is shared, vendor-neutral RTL:
`examples/common/vexriscv/vex_cpu.v` wraps the vendored `VexRiscv_Lite.v`
(`third_party/vexriscv/`) with a Wishbone→AXI bridge and a 64 KB `$readmemh`
BRAM; `vex/vex_sys.v` is the board's bus adapter. Its firmware
(`vex/fw/main.c`) is host-gated on the go flag (word 31): it writes a known
pattern (`0xCAFEF00D`/`0x1234ABCD`) to slave words 16/17 while the host raises
the flag, and otherwise just polls — so the CPU stays write-quiet during the
other hardware tests, which use slave words 0..15.

### VexRiscv CPU debug (`--debug`)

The `--debug` build (`build_arty_vex.py --debug` → `arty_a7_vex_debug_top.bit`)
adds **real processor debug** — halt/step, GPR/CSR/PC, halted memory, hardware
breakpoints — on top of the same design, coexisting with the fcapz cores on one
JTAG cable. It swaps `VexRiscv_Lite` for `VexRiscv_EmbeddedJtag`
(`third_party/vexriscv/`), a core built with the **official RISC-V Debug Module
+ JTAG DTM** (`EmbeddedRiscvJtag` plugin, no-TAP tunnel), and puts a `BSCANE2`
on the free **USER3** chain so upstream OpenOCD + `riscv-gdb` reach it while
USER1/2/4 keep serving debug-multi / axi-mon / ejtag-axi. The `DEBUG_EN=0`
default netlist is unchanged.

```bash
# build + program the debug bitstream, then:
openocd -f examples/arty_a7/arty_a7_vex_debug.cfg
riscv64-unknown-elf-gdb -x examples/arty_a7/arty_a7_vex_debug.gdb
```

One OpenOCD process serves both GDB (`:3333`) and fcapz's raw scans (Tcl
`:6666`) over the shared TAP — serialize with `poll off`/`poll on` around fcapz
ops. Needs a recent **upstream** OpenOCD (for `riscv set_bscan_tunnel_ir`). The
debug core is regenerated, not downloaded — see
`third_party/vexriscv/PROVENANCE.toml` (`[core.debug]`) and `GenFcapzVexDebug.scala`.

### Legacy MicroBlaze variant

The original top-level, `arty_a7_top.v`, keeps a small **MicroBlaze** subsystem
(block design under `legacy-microblaze/`, MDM on USER3, SmartConnect merge) as a
deprecated variant — it proves the fcapz cores drop into a proprietary-CPU
design. Build it with `--variant microblaze` (needs a MicroBlaze licence and
`mb-gcc`). Its firmware is behaviourally identical to the VexRiscv one, so it
presents the same observable bus contract.

## Files

Shared, vendor-neutral VexRiscv sources live outside this directory:
`third_party/vexriscv/` (the vendored core + MIT licence + provenance) and
`examples/common/vexriscv/` (the shared `vex_cpu.v`, `get_deps.py`, and firmware
`boot.S`/`link.ld`/`build_fw.py`). Only the board's `main.c` and `vex_sys.v`
stay here.

| File | Purpose |
| --- | --- |
| `arty_a7_vex_top.v` | **Default** top-level (open-source VexRiscv CPU) |
| `vex/vex_sys.v` | Board bus adapter: merges the CPU and EJTAG-AXI masters with `fcapz_axi_interconnect`, presenting the same `M_EJTAG`/`M_BUS` interface the legacy `mb_sys` did |
| `vex/fw/main.c` | Host-gated bus pattern-generator firmware (board-local workload) |
| `arty_a7_top.v` | Legacy top-level (proprietary MicroBlaze CPU) |
| `arty_a7_top.vhd` | Mixed-language VHDL top: VHDL cores + the Verilog VexRiscv subsystem |
| `legacy-microblaze/create_mb_bd.tcl` | Generates the legacy MicroBlaze block design (CPU + LMB + MDM@USER3 + SmartConnect) |
| `legacy-microblaze/build_fw.tcl` | Compiles the MicroBlaze firmware with the GCC shipped with Vivado |
| `legacy-microblaze/fw/` | MicroBlaze firmware source baked into the LMB BRAM |
| `arty_a7.xdc` | Arty A7-100T pin and clock constraints |
| `build.py` | Vivado build launcher / variant dispatcher (default `vex`; `--variant microblaze`/`vhdl`) |
| `build_arty_vex.py` / `build_arty_vex.tcl` | VexRiscv build (verify core + build firmware + Vivado) |
| `build_arty.tcl` | Vivado script for the legacy MicroBlaze top |
| `build_vhdl.py` / `build_arty_vhdl.tcl` | Mixed-language VHDL (VexRiscv) build |
| `arty_a7.cfg` | OpenOCD config for the onboard USB-JTAG adapter |
| `arty_a7_hs3.cfg` | OpenOCD config for an external Digilent HS3 cable |
| `test_hw_integration.py` | Hardware integration regression tests (default `vex`; `FPGACAP_BITSTREAM_VARIANT=verilog`/`vhdl` for the other tops) |
| `arty_a7_vex_top.bit` | Generated/reference bitstream (default variant) |

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

From the repository root, the default build is the open-source VexRiscv design.
It needs a RISC-V GCC toolchain (for the firmware); the VexRiscv core itself is
vendored (no network needed):

```sh
RISCV_PREFIX=riscv64-unknown-elf- python examples/arty_a7/build.py
```

Set `RISCV_PREFIX` to your toolchain prefix (the launcher also probes common
prefixes on `PATH`). The build verifies the vendored core, compiles the firmware
into `vex/fw/fw.mem`, runs Vivado (outputs under `vivado/fpgacapZero_arty_vex/`),
and copies the bitstream to:

```text
examples/arty_a7/arty_a7_vex_top.bit
```

If `vivado` is not on `PATH`, pass it explicitly with `--vivado /path/to/vivado`.

### Other variants

`build.py` is a variant dispatcher:

```sh
python examples/arty_a7/build.py --variant microblaze   # legacy MicroBlaze top
python examples/arty_a7/build.py --variant vhdl         # mixed-language VHDL top
```

The `microblaze` variant needs a MicroBlaze licence and `mb-gcc` and writes
`arty_a7_top.bit`. The `vhdl` variant is the VHDL top with the same VexRiscv
subsystem (needs the RISC-V toolchain) and writes `arty_a7_top_vhdl.bit`.

## Connect With hw_server

For Xilinx boards, `hw_server` is the most tested path:

```sh
hw_server -d
```

Program the bitstream and probe the debug cores:

```sh
fcapz --backend hw_server --port 3121 --tap xc7a100t \
  --program examples/arty_a7/arty_a7_vex_top.bit probe
```

Run a simple ELA capture:

```sh
fcapz --backend hw_server --port 3121 --tap xc7a100t \
  --program examples/arty_a7/arty_a7_vex_top.bit \
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
`arty_a7_vex_top.bit` separately before running host commands.

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

The suite defaults to the **VexRiscv** bitstream (`arty_a7_vex_top.bit`). To run
it against the legacy **MicroBlaze** top or the **VHDL** top instead, set the
variant (it selects the matching default bitfile and freshness sources):

```sh
FPGACAP_BITSTREAM_VARIANT=verilog python -m pytest examples/arty_a7/test_hw_integration.py -v
FPGACAP_BITSTREAM_VARIANT=vhdl python -m pytest examples/arty_a7/test_hw_integration.py -v
```

To skip hardware tests in an environment without the board:

```sh
FPGACAP_SKIP_HW=1 python -m pytest examples/arty_a7/test_hw_integration.py -v
```

## More Detail

- Main README quick start: [`../../README.md`](../../README.md)
- First capture walkthrough: [`../../docs/03_first_capture.md`](../../docs/03_first_capture.md)
- Transport notes: [`../../docs/14_transports.md`](../../docs/14_transports.md)
