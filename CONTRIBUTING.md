# Contributing to fpgacapZero

Thank you for your interest in contributing! This document covers the expected
workflow, code conventions, and — most importantly — how to run and extend the
test suite, including the OpenOCD backend which needs more real-hardware
coverage.

## Contents

- [Getting started](#getting-started)
- [Branch and commit rules](#branch-and-commit-rules)
- [Code style](#code-style)
- [Testing](#testing)
  - [Unit and integration tests (pytest)](#unit-and-integration-tests-pytest)
  - [RTL simulation](#rtl-simulation)
  - [Hardware tests — hw_server backend](#hardware-tests--hw_server-backend)
  - [Hardware tests — OpenOCD backend](#hardware-tests--openocd-backend)
- [Adding new tests](#adding-new-tests)
  - [Where OpenOCD coverage is most needed](#where-openocd-coverage-is-most-needed)
- [Testing on other vendors and boards](#testing-on-other-vendors-and-boards)
  - [Validation status](#validation-status)
  - [Adding a new board example](#adding-a-new-board-example)
  - [Lattice ECP5](#lattice-ecp5)
  - [Intel / Altera](#intel--altera)
  - [Gowin](#gowin)
  - [Reporting a new board result](#reporting-a-new-board-result)
- [Pre-push checklist](#pre-push-checklist)
- [Reporting bugs](#reporting-bugs)
- [License](#license)

---

## Getting started

```bash
git clone https://github.com/lcapossio/fpgacapZero.git
cd fpgacapZero
pip install -e ".[dev]"
```

Python 3.10 or later is required. No other mandatory dependencies — OpenOCD and
Vivado/XSDB are optional and only needed for hardware tests.

---

## Branch and commit rules

- All work targets the `main` branch directly. Feature branches are fine for
  development but PRs must merge into `main`.
- Commits must not include build artifacts (`.bit`, `.xpr`, Vivado log files,
  compiled simulation files).
- Commit messages must not reference AI tooling or agent names.
- The repository must remain runnable from a clean checkout at all times.
- Update `README.md` (and any relevant section) before your PR is ready for
  review. Do not merge documentation-free feature commits.

---

## Code style

### File headers

Every source file must carry an SPDX header on the first two lines:

**Python / TCL / XDC / CFG:**
```
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
```

**Verilog / SystemVerilog:**
```
// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
```

### Python

- Lint with `ruff check .` (config is in `pyproject.toml`).
- Line length target: 100 characters.
- No absolute paths anywhere — use `Path(__file__).resolve().parent` anchoring.
- Python is the only scripting language for host-side code.

### RTL

- All tools must be found on `PATH`; no hardcoded install paths.
- Vendor-specific primitives (BSCANE2, JTAG_USER_CODE, …) belong in the
  wrapper files under `rtl/`, not in the portable core.
- New RTL features must have a corresponding testbench under `tb/` and a
  simulation entry added to `sim/run_sim.py`.

---

## Testing

### Unit and integration tests (pytest)

```bash
pytest tests/ -v
```

These tests run against a `FakeTransport` (no hardware required) and cover the
CLI, RPC server, event-extraction helpers, EJTAG-AXI, and EJTAG-UART layers.
They must pass before any push.

Install **GUI test dependencies** for the full suite (CI uses `pip install -e ".[dev,gui]"`):

```bash
pip install -e ".[dev,gui]"
```

**Markers:** default pytest excludes `@pytest.mark.hw` (see `pyproject.toml`). GUI-related tests under `tests/` are marked `@pytest.mark.gui` so you can run `pytest -m gui` or `pytest -m "not gui"` as needed. GUI tests use `pytest-qt` (`qtbot`); they do not require a visible display when CI uses an offscreen platform plugin. Pure helpers (e.g. `tests/test_connect_errors.py` for connect error text) run with the default suite and are not GUI-marked. `tests/test_surfer_integration_smoke.py` is skipped unless `surfer` is on `PATH` (checks `surfer --help` for CLI stability / embed feasibility).

Window state for `fcapz-gui` is persisted in `fcapz-gui-window.ini` beside `gui.toml` (same config directory as in the README). When adding UI that must survive restarts, extend that INI via `QSettings` rather than inventing a new path.

### RTL simulation

```bash
python sim/run_sim.py            # run all testbenches
python sim/run_sim.py fcapz_ela  # single testbench
```

Requires [Icarus Verilog](https://steveicarus.github.io/iverilog/) (`iverilog`
and `vvp`) on PATH. All testbenches must pass before push.

### Hardware tests — hw_server backend

Requires an Arty A7-100T connected via USB and Vivado 2022.2+ on PATH.

```bash
# programs the FPGA automatically, then runs all hw integration tests
pytest examples/arty_a7/test_hw_integration.py -v

# skip if no hardware attached
FPGACAP_SKIP_HW=1 pytest examples/arty_a7/test_hw_integration.py -v
```

Set `FPGACAP_SKIP_HW=1` in CI or when no board is available; the suite will
skip gracefully.

### Hardware tests — OpenOCD backend

> **This area needs the most help.** The OpenOCD transport is implemented but
> has limited real-hardware validation. Contributions of test reports, bug
> fixes, and new test cases for the OpenOCD path are especially welcome.

**Setup**

1. Install [OpenOCD](https://openocd.org/) with FTDI support and ensure the
   `openocd` binary is on PATH.
2. Connect your JTAG adapter. The Arty A7 onboard FT2232H is supported
   out of the box:

```bash
openocd -f examples/arty_a7/arty_a7.cfg
# OpenOCD now listens on port 6666
```

For other adapters, copy `examples/arty_a7/arty_a7.cfg` and adjust `ftdi
vid_pid`, `ftdi channel`, and the IDCODE to match your device.

**Manual smoke test**

```bash
# In a second terminal (OpenOCD must already be running):
fcapz --backend openocd --port 6666 probe
fcapz --backend openocd --port 6666 capture --samples 64 --export /tmp/out.json
```

**Running the hardware suite against the OpenOCD backend**

The integration test file accepts a `FPGACAP_BACKEND` environment variable:

```bash
FPGACAP_BACKEND=openocd FPGACAP_OPENOCD_PORT=6666 \
    pytest examples/arty_a7/test_hw_integration.py -v
```

> If `FPGACAP_BACKEND` is not yet wired into `test_hw_integration.py`, that
> is itself a good first contribution — see
> [Where OpenOCD coverage is most needed](#where-openocd-coverage-is-most-needed).

**Reporting an OpenOCD result**

When you run a test (pass or fail) against a real board, please open an issue
or PR with:

- OpenOCD version (`openocd --version`)
- Adapter and board (vendor, model, JTAG speed used)
- FPGA device and IDCODE
- Which test(s) passed or failed
- Full OpenOCD log if a test failed

---

## Adding new tests

### Where OpenOCD coverage is most needed

The following areas currently have no or minimal OpenOCD-specific test
coverage. Patches in any of these are warmly welcomed:

| Area | File to look at | What to add |
|------|-----------------|-------------|
| `probe` / identity registers | `examples/arty_a7/test_hw_integration.py` | Parametrize existing `TestProbe` to run with `OpenOcdTransport` |
| Register round-trip | same | Same parametrization for `TestRegisterRoundTrip` |
| Capture end-to-end | same | Arm + trigger + readback through OpenOCD |
| EIO read/write | `tests/test_host_stack.py` → extend to hw | `EioController` over `OpenOcdTransport` |
| EJTAG-AXI single + burst | `tests/test_ejtagaxi.py` → extend to hw | `EjtagAxiController` over `OpenOcdTransport` |
| EJTAG-UART TX/RX | `tests/test_ejtaguart.py` → extend to hw | `EjtagUartController` over `OpenOcdTransport` |
| Non-Xilinx adapters | new file | A `.cfg` + test for any supported adapter |

When adding hardware tests that can work with either backend, parametrize on
the transport rather than duplicating test logic:

```python
import pytest

@pytest.fixture(params=["hw_server", "openocd"])
def transport(request):
    if request.param == "hw_server":
        ...
    else:
        ...
```

### General test guidelines

- Unit tests go in `tests/`. They must use `FakeTransport` or mocks and must
  not require any hardware or network connectivity.
- Hardware tests go alongside the example they exercise
  (e.g. `examples/arty_a7/test_hw_integration.py`).
- New RTL modules must have a testbench in `tb/` and a sim entry in
  `sim/run_sim.py`.
- New Python modules must have at least basic unit test coverage in `tests/`.
- All new test files must carry the SPDX header described above.

---

## Testing on other vendors and boards

RTL wrappers exist for four vendor families. Only the Xilinx 7-series path has
been fully hardware-validated. Every other vendor is **implemented but
unvalidated** — which means a contributor with the right hardware can make a
meaningful impact without writing a single line of host Python.

### Validation status

| Vendor | RTL wrapper | JTAG TAP | Verilog top | VHDL top | HW validated |
|--------|-------------|----------|-------------|----------|--------------|
| Xilinx 7-series / UltraScale | `fcapz_ela_xilinx7.v` | `jtag_tap_xilinx7.v` | yes | yes | **yes** (Arty A7-100T) |
| Lattice ECP5 | `fcapz_ela_ecp5.v` | `jtag_tap_ecp5.v` | — | yes | **needed** |
| Intel / Altera | `fcapz_ela_intel.v` | `jtag_tap_intel.v` | — | yes | **needed** |
| Gowin | `fcapz_ela_gowin.v` | `jtag_tap_gowin.v` | — | yes | **needed** |

The same gap applies to EIO (`fcapz_eio_<vendor>.v`) and the EJTAG-AXI /
EJTAG-UART bridges (`fcapz_ejtagaxi_intel.v`, `fcapz_ejtaguart_intel.v`).

### Adding a new board example

Use the Arty A7 example as a template. A minimal contribution consists of:

```
examples/<board_name>/
    <board_name>_top.v       # top-level: instantiate fcapz_ela_<vendor>
    <board_name>.xdc/.lpf/.qsf/.cst  # pin constraints
    build_<board_name>.tcl   # (or .py / Makefile) — vendor build script
    <board_name>.cfg         # OpenOCD config (if OpenOCD supports the adapter)
    test_hw_integration.py   # copy from examples/arty_a7, adapt transport
    README.md                # prerequisites, build command, tested toolchain version
```

Key rules when writing the top-level:

- Instantiate only `fcapz_ela_<vendor>` (or the matching EIO / EJTAG variant)
  — do not instantiate vendor primitives directly in the top file.
- Probe a free-running counter so the testbench can verify incrementing data
  without any external stimulus.
- Keep parameters in `localparam` at the top so reviewers can see the
  configuration at a glance.
- All files must carry the SPDX header (see [Code style](#code-style)).

### Lattice ECP5

Relevant RTL files: `rtl/fcapz_ela_ecp5.v`, `rtl/jtag_tap/jtag_tap_ecp5.v`,
`rtl/vhdl/fcapz_ela_ecp5.vhd`.

The ECP5 JTAG primitive is `JTAGG`. OpenOCD has built-in ECP5 support via the
`jlink` or `ftdi` adapter drivers. A typical OpenOCD config skeleton:

```tcl
# examples/ulx3s/ulx3s.cfg  (adjust VID/PID and IDCODE for your board)
adapter driver ftdi
ftdi vid_pid 0x0403 0x6015    # FT231X on ULX3S
ftdi channel 0
transport select jtag
adapter speed 6000

set _CHIPNAME LFE5U-85F
set _IDCODE   0x41113043

jtag newtap $_CHIPNAME tap -irlen 8 -expected-id $_IDCODE
init
```

Boards known to carry an ECP5: **ULX3S** (various densities), **OrangeCrab**,
**ECP5 Evaluation Board**, **Colorlight i5/i9**.

Suggested toolchain: [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build)
(`yosys` + `nextpnr-ecp5` + `ecppack`). The build script can be a simple
Python script using `subprocess` to call these tools — model it after
`sim/run_sim.py` for consistency.

### Intel / Altera

Relevant RTL files: `rtl/fcapz_ela_intel.v`, `rtl/jtag_tap/jtag_tap_intel.v`,
`rtl/fcapz_ejtagaxi_intel.v`, `rtl/fcapz_ejtaguart_intel.v`,
`rtl/vhdl/fcapz_ela_intel.vhd`.

The Intel JTAG primitive is `sld_virtual_jtag`. OpenOCD supports Intel FPGAs
via the `intel_fpga` target or through an FTDI-based USB Blaster clone. A
typical config skeleton:

```tcl
# examples/de10nano/de10nano.cfg
adapter driver ftdi
ftdi vid_pid 0x09fb 0x6010    # USB Blaster II
transport select jtag
adapter speed 6000

set _CHIPNAME 5cseba6u23i7
set _IDCODE   0x02d020dd

jtag newtap $_CHIPNAME tap -irlen 10 -expected-id $_IDCODE
init
```

Boards known to work: **DE10-Nano** (Cyclone V), **DE0-Nano** (Cyclone IV),
**Terasic DE1-SoC**, **Arrow Deca** (MAX 10). Quartus Prime (free Lite edition)
can be used to build Cyclone IV/V and MAX 10 designs.

> Intel does not officially support OpenOCD for Quartus-based JTAG, so the
> `jtag_tap_intel.v` USER opcode mechanism may need adjustment depending on
> the USB Blaster firmware version. Hardware reports are especially useful here.

### Gowin

Relevant RTL files: `rtl/fcapz_ela_gowin.v`, `rtl/jtag_tap/jtag_tap_gowin.v`,
`rtl/vhdl/fcapz_ela_gowin.vhd`.

The Gowin JTAG primitive is `JTAGG` (same name as ECP5 but different interface).
OpenOCD supports Gowin devices via the `ftdi` driver or the Gowin USB cable.

Boards known to carry Gowin FPGAs: **Tang Nano 9K / 20K**, **Tang Primer 25K**.
The free **Gowin EDA** toolchain can be used for synthesis and place-and-route.

A minimal OpenOCD config skeleton for Tang Nano 9K:

```tcl
# examples/tang_nano_9k/tang_nano_9k.cfg
adapter driver ftdi
ftdi vid_pid 0x0403 0x6010
ftdi channel 0
transport select jtag
adapter speed 5000

set _CHIPNAME GW1NR-9C
set _IDCODE   0x0900281b

jtag newtap $_CHIPNAME tap -irlen 8 -expected-id $_IDCODE
init
```

### Reporting a new board result

Whether the test passes or fails, open an issue or PR with:

- Board name, FPGA part number, and IDCODE
- Toolchain used (Vivado / Quartus / nextpnr / Gowin EDA) and version
- OpenOCD version and adapter (onboard FT2232 / USB Blaster / J-Link / …)
- `fcapz probe` output (or error)
- FPGA resource usage from the synthesis report (LUTs, FFs, BRAM)
- `test_hw_integration.py` results (pass/fail per test)

If the test passes and you include the above, the README support table will be
updated and your board added to the validated list.

---

## Pre-push checklist

Before pushing to a remote or opening a PR, confirm all of the following:

- [ ] `pytest tests/ -v` passes with zero failures
- [ ] `python sim/run_sim.py` passes all testbenches
- [ ] `ruff check .` reports no errors
- [ ] Hardware tests pass (or `FPGACAP_SKIP_HW=1` set with a justification in
      the PR description)
- [ ] All new / modified source files have the SPDX header
- [ ] No build artifacts or absolute paths introduced
- [ ] `README.md` updated if behaviour, CLI flags, or resource usage changed
- [ ] CHANGELOG.md entry added for user-visible changes

---

## Reporting bugs

Known issues and the active bug list live in `no_commit/BUGS.md` (not tracked
by git). For public bug reports, open a GitHub issue with:

- A minimal reproduction (board / adapter / command / output)
- OpenOCD or Vivado version, Python version
- Whether the issue is backend-specific (OpenOCD vs hw_server)

---

## License

By contributing you agree that your changes will be released under the
[Apache-2.0](LICENSE) license that covers this project.
