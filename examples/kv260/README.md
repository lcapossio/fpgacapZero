# Kria KV260 Reference Design

This example targets the AMD Kria KV260 Vision AI Starter Kit (K26 SOM,
Zynq UltraScale+ MPSoC `xck26`) through the kit's on-board USB-JTAG. It is
the hardware check for fpgacapZero on UltraScale+ silicon: every BSCANE2
USER chain carries a core, and the host reaches them through `hw_server`
in xsdb's `-register userN` mode, the MPSoC chain shape (PL TAP plus the
ARM DAP).

## Files

| File | Purpose |
| --- | --- |
| `kv260_top.v` | Top-level reference design (self-stimulating, no PL I/O) |
| `create_ps_bd.tcl` | Minimal PS block design: exports `pl_clk0` only |
| `kv260.xdc` | BSCAN TCK clock, clock groups, bitstream compression |
| `build_kv260.tcl` | Vivado batch build; fails if timing is not met |
| `build.py` | Preferred build launcher |
| `test_hw_integration.py` | Pytest hardware integration tests |

## JTAG chains

| Chain | Core |
| --- | --- |
| USER1 | `fcapz_debug_multi_xilinx7`: ELA slots 0-1, EIO slots 2-3 |
| USER2 | `fcapz_axi_mon_xilinx7` (`DECODE_EN=1`) on the bridge's AXI bus |
| USER3 | `fcapz_ejtaguart_xilinxus`, TX looped back to RX |
| USER4 | `fcapz_ejtagaxi_xilinxus` driving `tb/axi4_test_slave.v` |

| USER1 slot | Core | Probe |
| --- | --- | --- |
| 0 | ELA, 8-bit x 1024, decimation, external trigger, 32-bit timestamps, 4 segments | free-running 8-bit counter |
| 1 | ELA, two 8-bit channels, 4-stage trigger sequencer, storage qualification, relational compares | ch0 `counter[7:0] ^ 0xA5`, ch1 `counter[15:8]` |
| 2 | EIO, 8 in / 8 out | in: slow counter and ELA armed flags; out[4] is ELA slot 0 `trigger_in` |
| 3 | EIO, 32 in / 8 out | in: free-running `pl_clk0` counter |

## Clock and reset

The KV260 has no PL oscillator. `pl_clk0` comes from the PS, and when the
bitstream is loaded over JTAG it runs at whatever rate the board's boot
firmware programmed. The block design only sets the timing constraint
(200 MHz), and the tests measure the real rate from EIO slot 3 and fail if
the clock is stopped or faster than the constraint.

`pl_resetn0` is not used. Unless Linux brings up the PL, that EMIO GPIO is
never output-enabled and would hold the design in reset. The PL resets
itself from a power-on shift register instead.

## Build

Needs Vivado with the KV260 SOM board files (`kv260_som`, from the Vivado
board store).

```bash
python examples/kv260/build.py
```

The project is created under `vivado/fpgacapZero_kv260/` and the bitstream
is copied to `examples/kv260/kv260_top.bit`.

## Test

Power the kit, connect its USB-JTAG, and leave `hw_server` reachable on
the default port. The tests program the bitstream once, through the same
RPC `connect` the web UI and MCP server use:

```bash
python -m pytest examples/kv260/test_hw_integration.py -v
```

Program or connect by hand with the CLI. The tap name `xck26` selects the
MPSoC chain shape, and `--program` loads the PL through the PS TAP:

```bash
fcapz --backend hw_server --tap xck26 --program examples/kv260/kv260_top.bit probe
```

## Known limits

One test is marked `expectedFailure` and reports as such: an AXI bridge
burst read of `FIFO_DEPTH` beats (16 here) fails with SLVERR, because the
beat delivered in the cycle the burst FIFO fills is dropped. Bursts of up
to 15 beats pass.
