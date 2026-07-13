# 19 — AXI monitor

> **Goal**: capture and trigger on an AXI4-Lite interface over JTAG —
> a portable, vendor-agnostic AXI bus monitor. By the end
> of this chapter you will know how to instantiate the monitor, what it
> captures, how the host shows named AXI fields, and how the optional
> decode layer lets you trigger on transaction events such as error
> responses.

## What it is

The **AXI monitor** (`fcapz_axi_mon`) is a **passive tap** on an AXI4-Lite
interface. Every AXI port on the core is an *input* wired in parallel with the
real bus — it never drives a `*VALID`/`*READY`, so it cannot perturb the
transaction it is watching. It flattens the five AXI channels into one capture
vector and feeds that to an embedded [ELA](05_ela_core.md) capture/trigger
engine. Everything downstream — arming, triggering, segmented memory, burst
readback, the host `Analyzer`, the waveform viewer — is the ELA's, reused
unchanged.

Because the capture/trigger engine *is* the ELA, the monitor is driven over the
same JTAG register protocol and appears to the host as an ELA whose `0x0000`
`VERSION` register reports `"LA"`. An extra **identity register** distinguishes
it (see [Detecting it](#detecting-it)).

The whole thing is vendor-agnostic, the source is yours
([`../rtl/fcapz_axi_mon.v`](../rtl/fcapz_axi_mon.v)), and the design rationale
lives in [`specs/axi_monitor.md`](specs/axi_monitor.md).

## Instantiate it

Drop the wrapper onto the AXI4-Lite interface you want to watch:

```verilog
fcapz_axi_mon_xilinx7 #(
    .ADDR_W(32), .DATA_W(32),
    .DEPTH(1024),        // capture depth (ELA)
    .TRIG_STAGES(4),     // trigger sequencer stages (ELA)
    .DECODE_EN(1)        // P2: add the transaction-events word (see below)
) u_mon (
    .ACLK(aclk), .ARESETN(aresetn),
    .AWADDR(s_awaddr), .AWPROT(s_awprot), .AWVALID(s_awvalid), .AWREADY(s_awready),
    .WDATA(s_wdata), .WSTRB(s_wstrb), .WVALID(s_wvalid), .WREADY(s_wready),
    .BRESP(s_bresp), .BVALID(s_bvalid), .BREADY(s_bready),
    .ARADDR(s_araddr), .ARPROT(s_arprot), .ARVALID(s_arvalid), .ARREADY(s_arready),
    .RDATA(s_rdata), .RRESP(s_rresp), .RVALID(s_rvalid), .RREADY(s_rready)
);
```

Wire the same signals the slave sees. The wrapper bundles the BSCANE2 TAP, the
register/burst pipe, and the monitor core. Most ELA parameters
(`STOR_QUAL`, `NUM_SEGMENTS`, `TIMESTAMP_W`, `INPUT_PIPE`, …) pass straight
through — see [chapter 05](05_ela_core.md).

## What gets captured

The five channels are flattened **LSB-first** into the capture vector. For
`ADDR_W=DATA_W=32` the width is **152 bits** (`DECODE_EN=0`):

| Field | Width | LSB |
|-------|------:|----:|
| `awaddr` | 32 | 0 |
| `awprot` | 3 | 32 |
| `awvalid` / `awready` | 1 / 1 | 35 / 36 |
| `wdata` | 32 | 37 |
| `wstrb` | 4 | 69 |
| `wvalid` / `wready` | 1 / 1 | 73 / 74 |
| `bresp` | 2 | 75 |
| `bvalid` / `bready` | 1 / 1 | 77 / 78 |
| `araddr` | 32 | 79 |
| `arprot` / `arvalid` / `arready` | 3 / 1 / 1 | 111 / 114 / 115 |
| `rdata` | 32 | 116 |
| `rresp` / `rvalid` / `rready` | 2 / 1 / 1 | 148 / 150 / 151 |

A bundled **probe map** (`fcapz/probes/axi4lite_32.prob`) names every field at
these offsets, so captures and VCD show `awaddr`, `wdata`, `bresp`, … instead of
one opaque `sample` word. The host loads it for you (next section).

## Detecting it

The monitor answers two read-only registers in the free config gap (the ELA owns
`0x0000–0x00FF` for config and exposes captured samples at `0x0100+`):

| Address | Reg | Contents |
|---------|-----|----------|
| `0x00E8` | `AXI_MON_ID` | `[31:16]` = `"AM"` (`0x414D`), `[15:8]` = `PROTO` (1 = AXI4-Lite), `[7:0]` = capability flags (bit0 = `DECODE_EN`). |
| `0x00EC` | `AXI_GEOM` | `[7:0]` `ADDR_W`, `[15:8]` `DATA_W`, `[19:16]` `ID_W`, `[24:20]` `CAP_CHANNELS`. |

The host checks the `"AM"` magic to recognise a monitor and pick the right probe
map.

## From Python

```python
from fcapz import Analyzer, AxiMonitor

an = Analyzer(transport, chain=1)
an.connect()
mon = AxiMonitor(an)

if mon.present:
    geo = mon.geometry()                       # AxiGeometry(addr_w=32, data_w=32, decode=…)
    cfg = mon.write_addr_capture_config(0x4000_0000)   # trigger on a write address
    an.configure(cfg)
    an.arm()
    result = an.capture()
    print(mon.decode_sample(result.samples[0]))        # {'awaddr': …, 'awvalid': …, …}
```

`write_addr_capture_config` works because `awaddr` is in the capture vector's
low 32 bits, which is what the ELA's value-match comparator sees (the 32-bit
`TRIG_VALUE`/`TRIG_MASK` are zero-extended for wider samples). To trigger on
*other* fields, enable the decode layer.

## The decode layer (`DECODE_EN=1`)

Because the trigger comparator only reaches the **low 32 bits** of the sample,
the decode layer prepends an **8-bit transaction-events word** at bit 0 so the
most useful triggers become expressible. The events (each one combinational, one
sample wide) are:

| Bit | Event | Asserted when |
|----:|-------|---------------|
| 0 | `aw_hs` | `AWVALID & AWREADY` |
| 1 | `w_hs` | `WVALID & WREADY` |
| 2 | `b_hs` | `BVALID & BREADY` |
| 3 | `ar_hs` | `ARVALID & ARREADY` |
| 4 | `r_hs` | `RVALID & RREADY` |
| 5 | `b_err` | `BVALID & BRESP[1]` (SLVERR/DECERR) |
| 6 | `r_err` | `RVALID & RRESP[1]` |
| 7 | `any_err` | `b_err \| r_err` |

With `DECODE_EN=1` the capture width grows to **160 bits** (events + the 152-bit
channel block shifted up by 8), `CAP_FLAGS` bit0 reads back `1`, and the host
loads `axi4lite_32_decode.prob` automatically. Trigger on an error response:

```python
cfg = mon.event_capture_config("any_err")   # value=mask=0x80 over the events byte
an.configure(cfg); an.arm()
```

Trade-off: with the decode layer, `awaddr` is no longer in the low 32 bits, so
`write_addr_capture_config` raises — pick the build (`DECODE_EN`) for the
triggers you need. Runtime address-range filters that restore address triggering
on decode builds are future work (see the spec).

## From the CLI

```bash
fcapz axi-mon                              # print identity, geometry, probe map
fcapz axi-mon --write-probe-file axi.prob  # dump the matching probe map
fcapz capture --probe-file axi.prob ...    # capture with named AXI fields
```

## From the web UI

Just **Connect** — chains are invisible plumbing. The server autodetects
which BSCAN chain hosts a debug core and scans the others, so `axi_mon_probe`
returns the monitor's full identity no matter which core the session landed
on. If a monitor exists anywhere on the target:

- the **Connection** panel's cores list shows an **AXI Monitor** card
  (protocol, address/data widths, decode layer, sample width) with a
  **Use this core** button when it isn't the session's core;
- the **AXI Mon** tab is fully functional immediately. On `DECODE_EN=1`
  builds, tick the transaction events to trigger on (`any_err`, `b_hs`, …)
  and **Apply event trigger** — the trigger fires when all selected events
  assert in the same cycle. On `DECODE_EN=0` builds it offers a
  **write-address trigger** (`awaddr` match) instead. Applying anything
  **switches the session to the monitor automatically** if it wasn't there
  already — each core remembers its own trigger/probe setup, so hopping
  between the monitor and a plain ELA doesn't clobber either;
- once the monitor is the session's core, its probe map is **auto-applied**
  to the ELA tab's named signals, so captures render `awaddr`, `wdata`,
  `bresp`, … in the embedded Surfer viewer. The builder just fills the shared
  ELA trigger value/mask — field positions come from the probe map the server
  returned, and arming stays in the **Run** tab.

Captures behave like any wide ELA capture: above 53 bits the UI automatically
uses the lossless VCD/CSV paths (JSON download is disabled to avoid rounding).

## Limitations and roadmap

- **AXI4-Lite only** so far. AXI4 (full) — IDs, bursts, `*LAST` — and AXI4-Stream
  are planned; the flatten and probe map are structured to extend.
- **Trigger reach.** One 32-bit window (`awaddr`, *or* the events byte) is
  directly triggerable per build. Runtime address-range/ID match filters and a
  protocol checker are the next phases.
- **Bundled probe maps** ship for `ADDR_W=DATA_W=32` only; other geometries need
  a matching `.prob` (the layout is in [What gets captured](#what-gets-captured)).

The design rationale, register-map plans, and phasing are in
[`specs/axi_monitor.md`](specs/axi_monitor.md).
