// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero EIO wrapper for Microchip PolarFire (standalone).
//
// WARNING: Only ONE UJTAG primitive is allowed per PolarFire device,
// so this standalone wrapper CANNOT coexist with fcapz_ela_polarfire.
// To use ELA + EIO together on PolarFire, set EIO_EN=1 on the
// fcapz_ela_polarfire wrapper instead.  This wrapper is for
// EIO-only designs (no ELA).
//
// Usage:
//   fcapz_eio_polarfire #(.IN_W(32), .OUT_W(32)) u_eio (
//       .probe_in(fabric_signals), .probe_out(driven_signals)
//   );

module fcapz_eio_polarfire #(
    parameter IN_W      = 32,
    parameter OUT_W     = 32,
    parameter [7:0] IR_USER1 = 8'h10,
    parameter [7:0] IR_USER2 = 8'h11
) (
    input  wire [IN_W-1:0]  probe_in,
    output wire [OUT_W-1:0] probe_out
);

    // TAP signals — UJTAG primitive exposes both user chains; we only
    // use ch1 (USER1) here and tie off ch2.
    wire tap_tck, tap_tdi, tap_tdo;
    wire tap_capture, tap_shift, tap_update, tap_sel;
    wire tap2_tck_unused, tap2_tdi_unused;
    wire tap2_capture_unused, tap2_shift_unused;
    wire tap2_update_unused, tap2_sel_unused;

    // Register bus
    wire        jtag_clk, jtag_rst;
    wire        jtag_wr_en, jtag_rd_en;
    wire [15:0] jtag_addr;
    wire [31:0] jtag_wdata, jtag_rdata;

    // ---- TAP wrapper (USER1 used; USER2 tied off with ch2_tdo=0) ----
    jtag_tap_polarfire #(
        .IR_USER1(IR_USER1),
        .IR_USER2(IR_USER2)
    ) u_tap (
        .ch1_tck(tap_tck), .ch1_tdi(tap_tdi), .ch1_tdo(tap_tdo),
        .ch1_capture(tap_capture), .ch1_shift(tap_shift),
        .ch1_update(tap_update), .ch1_sel(tap_sel),
        .ch2_tck(tap2_tck_unused), .ch2_tdi(tap2_tdi_unused), .ch2_tdo(1'b0),
        .ch2_capture(tap2_capture_unused), .ch2_shift(tap2_shift_unused),
        .ch2_update(tap2_update_unused), .ch2_sel(tap2_sel_unused)
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
