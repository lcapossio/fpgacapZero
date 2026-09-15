// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Intel/Altera sld_virtual_jtag -> VexRiscv EmbeddedRiscvJtag tunnel adapter.
//
// Intel analogue of vex_jtag_bscan_xilinx7: feeds the VexRiscv CPU-debug core's
// no-TAP JtagTapInstructionCtrl bundle from an sld_virtual_jtag instance, so the
// standard RISC-V JTAG DTM rides the FPGA JTAG alongside the fcapz cores (which
// take the other virtual-JTAG instance indices). Default CHAIN=6 (the first
// index free in the DE25-Nano reference design: 1/2=ELA ctrl/data, 3=EIO,
// 4=EJTAG-AXI, 5=AXI-mon).
//
// sld_virtual_jtag exposes DR-phase strobes (virtual_state_cdr/sdr/udr) instead
// of Xilinx's CAPTURE/SHIFT/UPDATE + SEL/RESET:
//   * capture/shift/update  <- virtual_state_cdr/sdr/udr;
//   * enable  = 1 -- the virtual_state_* strobes are only active while THIS
//     instance's VIR is selected, so a constant enable is correct (mirrors
//     rtl/jtag_tap/jtag_tap_intel.v, which ties sel high);
//   * reset   = 0 -- vJTAG surfaces no test-logic-reset strobe; the DTM's
//     defined state comes from the separate free-running debugReset POR in the
//     top, not from a JTAG-side reset.
//
// NOTE: driving this from stock OpenOCD needs the Altera VIR/VDR virtual-JTAG
// tunnel path (not the Xilinx SiFive-style `riscv use_bscan_tunnel`); that host
// path is a hardware bring-up item -- see examples/de25_nano notes.

module vex_jtag_bscan_intel #(
    parameter CHAIN = 6            // sld_instance_index
) (
    output wire jtag_clk,

    output wire ji_tdi,
    output wire ji_enable,
    output wire ji_capture,
    output wire ji_shift,
    output wire ji_update,
    output wire ji_reset,
    input  wire ji_tdo
);

    wire virtual_state_cdr;
    wire virtual_state_sdr;
    wire virtual_state_udr;

    sld_virtual_jtag #(
        .sld_auto_instance_index ("NO"),
        .sld_instance_index      (CHAIN),
        .sld_ir_width            (1)
    ) u_vjtag (
        .tck               (jtag_clk),
        .tdi               (ji_tdi),
        .tdo               (ji_tdo),
        .virtual_state_cdr (virtual_state_cdr),
        .virtual_state_sdr (virtual_state_sdr),
        .virtual_state_udr (virtual_state_udr),
        .ir_in             (),
        .ir_out            (1'b0)
    );

    assign ji_capture = virtual_state_cdr;
    assign ji_shift   = virtual_state_sdr;
    assign ji_update  = virtual_state_udr;
    assign ji_enable  = 1'b1;   // active whenever this VIR is selected
    assign ji_reset   = 1'b0;   // no vJTAG TLR strobe; POR handles reset

endmodule
