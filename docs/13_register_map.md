# 13 — Register map

> This chapter is a **stub**.  The canonical register map for every
> fcapz core lives at [`specs/register_map.md`](specs/register_map.md)
> and is the **ground truth** — when this chapter and the spec
> disagree, the spec wins.
>
> If you are reading the manual top-to-bottom, jump to that file
> now and come back here when you're done.

## What this document calls a “register map” (and “address map”)

In fcapz docs, the **register map** is the contract for **how you talk to
each on-chip debug core through JTAG**: which scan chain / `USERx`
instruction, which **32-bit register offsets** you read and write, and
how the fields are encoded. It is **not** your FPGA SoC’s general
memory map (DDR, peripherals, AXI crossbar) unless you are in the
**EJTAG-AXI** part of the spec, where the bridge’s shift format carries a
**separate** AXI `addr` field for bus transactions.

Inside [`specs/register_map.md`](specs/register_map.md), a heading
**Address map** (or **Address Map**) is always **scoped to the section
you are in**. The first big table is **ELA only** (logic analyzer
control via USER1, with USER2 for burst sample data). Later sections
give **EIO** (USER3) and the **EJTAG** bridges (USER4) their own layouts.
Offsets like `0x0004` start over **per core** — they are not one global
address space across the chip.

## Why this chapter is a stub

Maintaining a register map in two places (a chapter and a spec) is
how documentation rots.  The spec at
[`specs/register_map.md`](specs/register_map.md) is the **single
source of truth** and is updated whenever the RTL changes; this
chapter is a navigation aid that points you at it.

That file begins with an **Index** of sections and subsections (HTML
fragment IDs so links work reliably on GitHub) and places **↑ Top**
after each major section for quick return to the title.

## What's in `specs/register_map.md`

The canonical spec covers all four cores in one document:

- **ELA core** (USER1 control + default burst data; optional DATA_CHAIN burst data)
  - Identity / version registers (`VERSION` at `0x0000` with the
    `LA` core_id magic)
  - Control / status / trigger / pre-post-trigger registers
  - Storage qualification registers
  - Per-stage trigger sequencer registers (`SEQ_BASE = 0x0040`)
  - Channel mux / probe mux registers
  - Decimation, external trigger, segmented memory registers
  - **`TRIG_DELAY` at `0x00D4`** (new in v0.3.0)
  - Sample data window (USER1 + USER2)
- **EIO core** (USER3)
  - `VERSION` at `0x0000` with the `IO` core_id magic
  - `IN_W` / `OUT_W` parameter registers
  - Input / output register banks
- **EJTAG-AXI bridge** (USER4)
  - 72-bit pipelined DR shift format with all command codes
  - Config registers (`VERSION` with `JX` core_id, `FEATURES` with
    the `FIFO_DEPTH-1` AXI4 awlen encoding)
  - Status bits and error response codes
- **EJTAG-UART bridge** (USER4, mutually exclusive with AXI)
  - 32-bit DR per scan (commands `NOP` … `RESET`); not a word-addressed
    map like ELA/EIO
  - **CONFIG** byte addresses `0x0`–`0xF`: `VERSION` (`JU` core_id),
    `FEATURES` (parity + TX/RX FIFO depth parameters), `BAUD_DIV`
  - Shift-out status / `tx_free` / pipelined RX and CONFIG behaviour

## Quick reference: where features live

| Feature | Where to look in the spec |
|---|---|
| **ELA VERSION encoding** (major / minor / `LA` core_id) | "ELA Core Register Map" → row at `0x0000` |
| **Trigger sequencer per-stage layout** | "ELA Core Register Map" → "SEQ_STAGE_N_CFG encoding" |
| **Storage qualification mode bits** | "ELA Core Register Map" → row at `0x0030` |
| **TRIG_DELAY (v0.3.0)** | "ELA Core Register Map" → row at `0x00D4` |
| **FEATURES bitfield layout** | "ELA Core Register Map" → "FEATURES" subsection |
| **EIO VERSION encoding** (`IO` core_id) | "EIO Core Register Map" → row at `0x0000` |
| **EJTAG-AXI 72-bit DR encoding** | "EJTAG-AXI Bridge DR Format" |
| **EJTAG-AXI FIFO_DEPTH register encoding** | "EJTAG-AXI Bridge" → "Config registers (CMD_CONFIG)" → `FEATURES` row |
| **EJTAG-UART DR + CONFIG map** | "EJTAG-UART bridge — 32-bit DR" in the spec |

## When you actually need this

You need the spec when you are:

1. **Writing a non-Python host driver** (Tcl, Rust, C, ...) that
   bypasses `Analyzer` / `EioController` / `EjtagAxiController`
   / `EjtagUartController` and talks to the cores directly via
   `irscan` / `drscan`.  In this case the spec is your only
   reference for the bit-level encodings.
2. **Adding a new feature to a core** and need to find a free
   register address that doesn't collide.
3. **Debugging a wire trace** captured with a JTAG analyzer and
   trying to figure out what each scan was doing.
4. **Implementing a new transport** ([chapter 14](14_transports.md))
   that needs to issue raw `irscan` / `drscan` commands.

For everything else — using fcapz from Python, the CLI, the RPC
server, the GUI — the host stack already speaks the protocol for
you.  You should not need to read the spec to **use** fcapz.

## Where the spec lives in git

[`docs/specs/register_map.md`](specs/register_map.md) — committed,
versioned, the single source of truth.

It's part of the user-facing tree (`docs/`) so it ships with every
release and shows up cleanly on GitHub.  If you find a discrepancy
between the spec and the actual RTL behavior, **file a bug against
the spec** — the spec is the contract.

## What's next

- [`specs/register_map.md`](specs/register_map.md) — go read it
- [Chapter 14 — Transports](14_transports.md): the
  `Transport` ABC + implementing a new backend (the spec is the
  bit-level reference for what your transport needs to scan)
- [`specs/transport_api.md`](specs/transport_api.md): the
  Transport ABC contract
