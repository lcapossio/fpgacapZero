// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero EIO wrapper for Gowin GW1N / GW2A (standalone).
//
// WARNING: Gowin has only 1 user JTAG chain.  This standalone EIO
// wrapper uses that chain and CANNOT coexist with fcapz_ela_gowin.
// To use ELA + EIO together on Gowin, set EIO_EN=1 on the
// fcapz_ela_gowin wrapper instead.
//
// This wrapper is suitable for EIO-only designs (no ELA).
//
// Usage:
//   fcapz_eio_gowin #(.IN_W(32), .OUT_W(32)) u_eio (
//       .probe_in(fabric_signals), .probe_out(driven_signals)
//   );

module fcapz_eio_gowin #(
    parameter IN_W  = 32,
    parameter OUT_W = 32,
    parameter CHAIN = 3    // BSCANE2 USER chain (default USER3)
) (
    input  wire [IN_W-1:0]  probe_in,
    output wire [OUT_W-1:0] probe_out
);

    // TAP signals
    wire tap_tck, tap_tdi, tap_tdo;
    wire tap_capture, tap_shift, tap_update, tap_sel;

    // Register bus
    wire        jtag_clk, jtag_rst;
    wire        jtag_wr_en, jtag_rd_en;
    wire [15:0] jtag_addr;
    wire [31:0] jtag_wdata, jtag_rdata;

    // ---- TAP wrapper ----
    jtag_tap_gowin #(.CHAIN(CHAIN)) u_tap (
        .tck(tap_tck), .tdi(tap_tdi), .tdo(tap_tdo),
        .capture(tap_capture), .shift(tap_shift),
        .update(tap_update), .sel(tap_sel)
    );

    // ---- Register interface ----
    jtag_reg_iface u_reg (
        .arst(1'b0),
        .tck(tap_tck), .tdi(tap_tdi), .tdo(tap_tdo),
        .capture(tap_capture), .shift_en(tap_shift),
        .update(tap_update), .sel(tap_sel),
        .reg_clk(jtag_clk), .reg_rst(jtag_rst),
        .reg_wr_en(jtag_wr_en), .reg_rd_en(jtag_rd_en),
        .reg_addr(jtag_addr), .reg_wdata(jtag_wdata),
        .reg_rdata(jtag_rdata)
    );

    // ---- EIO core ----
    fcapz_eio #(.IN_W(IN_W), .OUT_W(OUT_W)) u_eio (
        .probe_in(probe_in), .probe_out(probe_out),
        .jtag_clk(jtag_clk), .jtag_rst(jtag_rst),
        .jtag_wr_en(jtag_wr_en),
        .jtag_addr(jtag_addr), .jtag_wdata(jtag_wdata),
        .jtag_rdata(jtag_rdata)
    );

endmodule
