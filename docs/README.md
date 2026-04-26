# fpgacapZero User Manual

This is the canonical user manual for **fpgacapZero**, the open-source,
vendor-agnostic FPGA debug suite.  It assumes you are a junior FPGA
developer who is comfortable with Vivado, basic SystemVerilog, and the
JTAG / AXI4 concepts you have already met in any introductory FPGA
course — but does **not** assume you have used fpgacapZero before.

The manual is split into focused chapters so each topic stays
reviewable on its own.  Read them in order the first time, then come
back to individual chapters as you need them.

> **Tip**: this manual is in addition to the project README, which is
> the elevator pitch and the quick-reference card.  When in doubt the
> manual is more accurate; it is updated with every release.

---

## Chapters

| # | Chapter | When to read |
|---|---------|--------------|
| 01 | [Overview](01_overview.md) | Start here. What fpgacapZero is, the four cores, the vendor matrix, and how the pieces fit together. |
| 02 | [Installation](02_install.md) | Install the Python package, the optional GUI extras, and the JTAG transport prerequisites (OpenOCD or Vivado hw_server). |
| 03 | [First capture in 10 minutes](03_first_capture.md) | A guided end-to-end walkthrough on the Arty A7-100T reference design: build the bitstream, program the FPGA, capture a waveform, view it in GTKWave. |
| 04 | [RTL integration](04_rtl_integration.md) | How to instantiate fcapz cores in your own design. The vendor wrappers, every parameter explained, and the role of `fcapz_version.vh`. |
| 05 | [ELA core](05_ela_core.md) | The Embedded Logic Analyzer in depth: trigger sequencer, comparator modes, storage qualification, decimation, external trigger, timestamps, segmented memory, runtime probe mux, and the new `trigger_delay`. |
| 06 | [EIO core](06_eio_core.md) | The Embedded I/O core: read fabric signals, drive fabric signals, clock domains, host API. |
| 07 | [EJTAG-AXI bridge](07_ejtag_axi_bridge.md) | The JTAG-to-AXI4 master bridge: architecture, FIFO_DEPTH guard rails, single vs auto-increment vs burst transfers, and the AXI4 subset supported. |
| 08 | [EJTAG-UART bridge](08_ejtag_uart_bridge.md) | The JTAG-to-UART bridge: TX/RX async FIFOs, baud rate selection, host stream API, and the known internal-loopback caveat (BUG-002). |
| 09 | [Python API](09_python_api.md) | Complete reference for the `fcapz` Python package: `Analyzer`, `EioController`, `EjtagAxiController`, `EjtagUartController`, transports, events module, with worked examples. |
| 10 | [CLI reference](10_cli_reference.md) | Every `fcapz` subcommand, every flag, with copy-pasteable examples. |
| 11 | [JSON-RPC server](11_rpc_server.md) | Driving fpgacapZero from another language or process: the line-delimited JSON-RPC protocol, full schema, and all commands. |
| 12 | [Desktop GUI (`fcapz-gui`)](12_gui.md) | The PySide6 GUI: panels, settings, the embedded `pyqtgraph` preview, viewer integration with GTKWave / Surfer / WaveTrace, the auto-generated `.gtkw` layout, and the headless install path. |
| 13 | [Register map](13_register_map.md) | The full register map for all four cores. Stub chapter that links straight to the canonical reference at [`specs/register_map.md`](specs/register_map.md). |
| 14 | [Transports](14_transports.md) | OpenOCD vs Xilinx hw_server, the named `IR_TABLE_*` presets for 7-series and UltraScale, the readiness wait, and how to add a new transport backend. |
| 15 | [Export formats](15_export_formats.md) | JSON, CSV, VCD; what each format contains; the auto-generated `.gtkw` waveform-viewer layout file; integration with GTKWave / Surfer / WaveTrace. |
| 16 | [Versioning and release](16_versioning_and_release.md) | How the project version flows from the `VERSION` file through `tools/sync_version.py` into the RTL `fcapz_version.vh`, the per-core `core_id` magic registers, and the procedure for cutting a new release. |
| 17 | [Troubleshooting](17_troubleshooting.md) | Common errors, what they mean, and how to fix them. |

## Reference specs

The chapters above link into a small set of canonical reference
documents in [`specs/`](specs/).  These are the ground truth — when a
chapter and a spec disagree, the spec wins, and the chapter is wrong
and should be corrected.

| Spec | Purpose |
|------|---------|
| [`specs/architecture.md`](specs/architecture.md) | Block diagram, parameter list, resource usage, clock domains. |
| [`specs/register_map.md`](specs/register_map.md) | Full register map for ELA, EIO, EJTAG-AXI, EJTAG-UART. Opens with an **Index** (anchor links); each major section ends with **↑ Top**. |
| [`specs/transport_api.md`](specs/transport_api.md) | The `Transport` ABC contract — required to implement when adding a new backend. |
| [`specs/waveform_schema.md`](specs/waveform_schema.md) | JSON / CSV / VCD export formats, field-by-field. |

## Conventions used in this manual

- **`fcapz`** (lowercase) is the command-line tool, the importable
  Python package, and the prefix on every RTL identifier.
- **`fpgacapZero`** (mixed case) is the project name and the GitHub
  repository name.
- Code blocks tagged ```bash``` are shell commands; ```python``` are
  Python snippets; ```verilog``` are RTL.
- File paths in the running text use `code formatting`. When a file
  path appears as a clickable link it always points at the file in
  this repository (relative path).
- "**HIGH / MEDIUM / LOW**" priority labels reflect maintainer triage
  and may evolve between releases.
- "**BREAKING**" is used to flag a change that requires user action
  on upgrade. Every BREAKING change has a migration recipe in
  [`../CHANGELOG.md`](../CHANGELOG.md).

## What's not in this manual

- Hardware bring-up for vendor wrappers other than Xilinx 7-series.
  The shared core RTL is covered by simulation, and the vendor wrappers
  are lint-elaborated, but ECP5, Intel, Gowin, PolarFire, and UltraScale
  board-level smoke tests are still future work. See chapter 04 for the
  support matrix and validation levels.
- Internal design discussions for features that have shipped. Those
  live in git history and the merged PRs; this manual describes the
  *current* behavior, not the design rationale.

## Project resources

- **README**: [`../README.md`](../README.md) — top-level pitch and
  quick reference.
- **CHANGELOG**: [`../CHANGELOG.md`](../CHANGELOG.md) — every release
  with breaking changes called out.
- **CONTRIBUTING**: [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — how
  to contribute, especially around testing and OpenOCD validation
  for new vendor boards.
- **License**: Apache-2.0, see [`../LICENSE`](../LICENSE).
