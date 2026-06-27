<p align="center">
  <img src="docs/assets/fcapz-logo.png" alt="fpgacapZero logo" width="180">
</p>

# fpgacapZero (fcapz)

[![CI](https://github.com/lcapossio/fpgacapZero/actions/workflows/ci.yml/badge.svg)](https://github.com/lcapossio/fpgacapZero/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Sponsor](https://img.shields.io/github/sponsors/lcapossio?logo=githubsponsors&label=Sponsor)](https://github.com/sponsors/lcapossio)

Open-source FPGA debug cores — in **native Verilog and VHDL** — that you drop
into any design to **see and control what's happening inside your FPGA over
JTAG**: no extra board pins, no soft CPU, no vendor lock-in.

Think of it as an open, vendor-neutral alternative to ChipScope / SignalTap /
Reveal that works the same way across **Xilinx, Intel/Altera, Lattice, Gowin,
and Microchip** parts, with a Python / CLI / GUI host stack on top.

> 📖 **New here? Start with the [User Manual](docs/README.md)** — especially
> **[First capture in 10 minutes](docs/03_first_capture.md)**. This page is just
> the quick tour.

## What's in the box

Four small RTL cores, all driven over JTAG:

- **ELA — Embedded Logic Analyzer** — capture internal signals into a waveform
  with flexible triggers, and export to **VCD / CSV / JSON**.
- **EIO — Embedded I/O** — read and drive fabric signals live at runtime.
- **EJTAG-AXI** — a JTAG-to-AXI4 master bridge for memory-mapped bus access.
- **EJTAG-UART** — a JTAG-to-UART console bridge.

Plus a host stack: a **Python API**, the **`fcapz` command-line tool**, a
**JSON-RPC server**, an optional **PySide6 desktop GUI** (`fcapz-gui`) with a
built-in waveform preview, and a **browser-based web interface** (`fcapz-web`)
you can reach from the local machine or across the network.

## Why fpgacapZero

- **Vendor-agnostic** — one portable core with thin TAP wrappers for Xilinx
  7-series, Xilinx UltraScale / UltraScale+, Lattice ECP5, Intel / Altera,
  Gowin, and Microchip PolarFire-family devices.
- **Small, and only as big as you need** — a usable 8-bit / 1024-sample ELA
  fits in about **600 LUTs + 0.5 BRAM**. Extra triggers, timestamps,
  decimation, segmenting, and more are compile-time options you enable only
  when a design needs them.
- **Verilog *and* VHDL** — the portable core ships as native Verilog and native
  VHDL, with shared regression coverage for both.
- **Apache-2.0** — usable in proprietary designs.

## Will it work on my board?

Any board with JTAG access works. You drive it through **OpenOCD** (any FTDI
adapter) or the **Xilinx hw_server** (Vivado). The full per-vendor matrix and
JTAG-chain rules are in the manual's
[RTL integration chapter](docs/04_rtl_integration.md); see also
[Support status](#support-status) below.

## Quick start

You need Python 3.10+, a JTAG-capable FPGA board, and either OpenOCD or Vivado
hw_server. Full setup is in [Installation](docs/02_install.md).

```bash
git clone https://github.com/lcapossio/fpgacapZero.git
cd fpgacapZero
pip install -e ".[gui]"     # core host stack + desktop GUI
fcapz-gui                   # the easiest way to take your first capture
```

<p align="center">
  <img src="docs/assets/fcapz-gui-demo.png" alt="fcapz-gui desktop application showing connection, ELA capture controls, and log output" width="900">
</p>

Prefer a browser — or need to reach the board from another machine? Install the
web extra and open the UI instead:

```bash
pip install -e ".[web]"     # core host stack + web interface
fcapz-web                   # serves on http://127.0.0.1:8000
```

It mirrors the GUI — connect, ELA capture with run controls, EIO, JTAG-AXI, and
an embedded **Surfer** waveform viewer — over the same JSON-RPC API, and can be
exposed on the network with a bearer token. See
**[Web interface](docs/18_web_interface.md)**.

Prefer the command line? Build the Arty A7 reference bitstream (see
[Build from source](#build-from-source) — or use your own), then capture:

```bash
fcapz --backend hw_server --port 3121 \
  --program examples/arty_a7/arty_a7_top.bit \
  capture --trigger-value 0 --trigger-mask 0xFF --out capture.vcd --format vcd
```

The end-to-end walkthrough lives in
**[First capture in 10 minutes](docs/03_first_capture.md)**. For every command
and flag, see the [CLI reference](docs/10_cli_reference.md); for scripting, the
[Python API](docs/09_python_api.md) and [JSON-RPC server](docs/11_rpc_server.md).

## Add it to your design

One instantiation per core — swap the wrapper suffix to match your FPGA vendor:

```verilog
wire [127:0] my_signals;

// Embedded Logic Analyzer (all JTAG plumbing bundled inside the wrapper)
fcapz_ela_xilinx7 #(.SAMPLE_W(128), .DEPTH(4096)) u_ela (
    .sample_clk (sys_clk),
    .sample_rst (reset),
    .probe_in   (my_signals)
);
```

That's the minimal ELA. Wrapper names follow `fcapz_<core>_<vendor>` (e.g.
`fcapz_ela_ecp5`, `fcapz_eio_intel`). Every parameter, the EIO / AXI / UART
cores, LiteX integration, VHDL sources under `rtl/vhdl/`, and the per-vendor
JTAG-chain rules are covered in **[RTL integration](docs/04_rtl_integration.md)**.
The canonical register / shift maps live in
[`docs/specs/register_map.md`](docs/specs/register_map.md).

## Support status

| Area | Status |
|------|--------|
| Xilinx `hw_server` backend | ✅ Hardware-validated on Arty A7 |
| OpenOCD backend | Implemented; needs more hardware validation |
| Xilinx 7-series wrappers | ✅ Hardware-validated on Arty A7-100T |
| UltraScale / ECP5 / Intel / Gowin / PolarFire wrappers | RTL complete; host / hardware validation still limited |
| ELA / EIO / EJTAG-AXI / EJTAG-UART | ✅ Validated on Arty A7 (details in the manual) |

The full, always-current matrix is in [Overview](docs/01_overview.md) and
[RTL integration](docs/04_rtl_integration.md).

## Build from source

```bash
# Build the Arty A7 reference bitstream (Vivado)
python examples/arty_a7/build.py

# Run the host test suite — no hardware needed
pip install -e ".[dev,hdl]"
pytest tests/ -v
```

RTL simulation (Icarus / Verilator / cocotb / GHDL), the VHDL parity gates, the
CI jobs, and the hardware-in-the-loop tests are all documented in
**[CONTRIBUTING.md](CONTRIBUTING.md)**. Live CI status is the badge at the top.

## Project layout

```
rtl/        Portable Verilog cores + vendor TAP wrappers (VHDL in rtl/vhdl/)
host/fcapz/ Python host stack: Analyzer, transports, CLI, RPC, GUI
examples/   Reference designs (Arty A7, Gowin BRS-100, and more)
docs/       User manual (start at docs/README.md) + canonical specs
tb/, sim/   Testbenches and simulation runners
```

## Project links

- 📖 **[User Manual](docs/README.md)** — the complete guide
- 📝 **[CHANGELOG](CHANGELOG.md)** — releases, with breaking changes called out
- 🤝 **[CONTRIBUTING](CONTRIBUTING.md)** — dev setup, testing, adding a board
- 🐛 **[Troubleshooting](docs/17_troubleshooting.md)** — common errors and fixes

## Author

Leonardo Capossio — [bard0 design](https://www.bard0.com) — <hello@bard0.com>

## Contributors

- [Brisbane Silicon](https://github.com/BrisbaneSilicon)

## Sponsoring

If fpgacapZero helps your FPGA debug flow, you can support continued
development through [GitHub Sponsors](https://github.com/sponsors/lcapossio).

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.
