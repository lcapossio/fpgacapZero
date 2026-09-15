// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Xilinx 7-series BSCANE2 -> VexRiscv EmbeddedRiscvJtag tunnel adapter.
//
// The VexRiscv CPU-debug core (third_party/vexriscv/VexRiscv_EmbeddedJtag.v)
// exposes a standard RISC-V JTAG DTM in *no-TAP tunnel* mode: instead of its
// own JTAG pins it takes a JtagTapInstructionCtrl bundle
// (jtagInstruction_{tdi,enable,capture,shift,update,reset,tdo}) clocked by a
// separate jtag_clk. This wrapper drives that bundle from a Xilinx BSCANE2 on
// a USER chain, so the DTM rides the FPGA's dedicated JTAG alongside the fcapz
// debug cores (which own the other USER chains) -- one physical cable, one
// OpenOCD BSCAN tunnel (riscv use_bscan_tunnel / set_bscan_tunnel_ir).
//
// Default CHAIN=3 => USER3 (IR 0x22 on xc7a100t), the chain fcapz leaves free
// in the VexRiscv reference design (USER1=debug-multi, USER2=axi-mon,
// USER4=ejtag-axi). OpenOCD's tunnel defaults to USER4, so the host cfg must
// set_bscan_tunnel_ir 0x22 to match.
//
// Unlike rtl/jtag_tap/jtag_tap_xilinx7.v this wrapper WIRES BSCANE2.RESET
// through to the tunnel: Spinal's tunnelled instruction control needs a
// defined reset (test-logic-reset) state, and dropping it leaves the DTM shift
// register unresettable.
//
// This is CPU-neutral JTAG plumbing that happens to target the Spinal tunnel
// port shape, so it lives in examples/ next to the CPU, not in fcapz rtl/.

module vex_jtag_bscan_xilinx7 #(
    parameter CHAIN = 3            // USER3
) (
    // jtag_clk for the DTM tunnel clock domain (BSCANE2 TCK).
    output wire jtag_clk,

    // JtagTapInstructionCtrl, as exposed by VexRiscv_EmbeddedJtag.
    output wire ji_tdi,
    output wire ji_enable,
    output wire ji_capture,
    output wire ji_shift,
    output wire ji_update,
    output wire ji_reset,
    input  wire ji_tdo
);

    // BSCANE2.TDI is data from the JTAG host into the fabric (-> core tdi);
    // BSCANE2.TDO is data from the fabric back to the host (<- core tdo).
    // SEL/CAPTURE/SHIFT/UPDATE/RESET map straight onto the tunnel controls.
    BSCANE2 #(.JTAG_CHAIN(CHAIN)) u_bscan (
        .TCK     (jtag_clk),
        .TDI     (ji_tdi),
        .TDO     (ji_tdo),
        .CAPTURE (ji_capture),
        .SHIFT   (ji_shift),
        .UPDATE  (ji_update),
        .SEL     (ji_enable),
        .RESET   (ji_reset),
        .DRCK    (),
        .RUNTEST ()
    );

endmodule
