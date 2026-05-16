// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero ELA wrapper for Gowin GW1N / GW2A.
//
// Gowin provides a single user JTAG chain, so this wrapper uses
// word-by-word register readback only (no burst data engine).
// Readback is slower than Xilinx/ECP5 but fully functional.
//
// Optional EIO: set EIO_EN=1 to include an Embedded I/O core on the
// same register bus via address mux.  EIO registers appear at offset
// 0x8000 from the host's perspective.
//
// Usage:
//   // ELA only
//   fcapz_ela_gowin #(.SAMPLE_W(8), .DEPTH(1024)) u_ela (
//       .sample_clk(clk), .sample_rst(rst), .probe_in(signals)
//   );
//
//   // ELA + EIO combined
//   fcapz_ela_gowin #(.SAMPLE_W(8), .DEPTH(1024),
//       .EIO_EN(1), .EIO_IN_W(32), .EIO_OUT_W(32)
//   ) u_ela (
//       .sample_clk(clk), .sample_rst(rst), .probe_in(signals),
//       .eio_probe_in(observe), .eio_probe_out(drive)
//   );

module fcapz_ela_gowin #(
    parameter SAMPLE_W     = 8,
    parameter DEPTH        = 1024,
    parameter TRIG_STAGES  = 1,
    parameter STOR_QUAL    = 0,
    parameter INPUT_PIPE   = 0,
    parameter NUM_CHANNELS = 1,
    parameter TIMESTAMP_W  = 0,
    parameter CHAIN        = 1,
    // Optional EIO (shares single chain via address mux)
    parameter EIO_EN       = 0,
    parameter EIO_IN_W     = 1,
    parameter EIO_OUT_W    = 1,
    parameter REL_COMPARE  = 0,
    parameter DUAL_COMPARE = 1,
    parameter USER1_DATA_EN = 1
) (
    input  wire                             sysclk,
        // NOTE: <TODO>

    input  wire                             sample_clk,
    input  wire                             sample_rst,
    input  wire [SAMPLE_W*NUM_CHANNELS-1:0] probe_in,
    // EIO ports (active when EIO_EN=1)
    input  wire [EIO_IN_W-1:0]              eio_probe_in,
    output wire [EIO_OUT_W-1:0]             eio_probe_out,

    input  wire                             tms_pad_i,
    input  wire                             tck_pad_i,
    input  wire                             tdi_pad_i,
    output wire                             tdo_pad_o
);

    // TAP signals
    wire tap_tdi;
    wire [1:0] tap_tdo, tap_capture, tap_update, tap_sel;
    wire [1:0] tap_shift_in, tap_shift_out;

    // Register bus
    wire        jtag_clk, jtag_rst;
    wire        jtag_wr_en, jtag_rd_en;
    wire [15:0] jtag_addr;
    wire [31:0] jtag_wdata, jtag_rdata;
    wire        jtag_rst_ctrl;
    localparam PTR_W = $clog2(DEPTH);

    // Gowin exposes only one user chain here, so USER2 burst readout is not
    // instantiated. Keep the core burst interface tied off; USER1 readback
    // remains available for samples and timestamps.
    wire [PTR_W-1:0] burst_rd_addr_dummy = {PTR_W{1'b0}};
    wire [SAMPLE_W-1:0] burst_rd_data_unused;
    wire [((TIMESTAMP_W > 0) ? TIMESTAMP_W : 1)-1:0] burst_rd_ts_data_unused;
    wire burst_start_unused;
    wire burst_timestamp_unused;
    wire [PTR_W-1:0] burst_start_ptr_unused;

    // ---- TAP wrapper ----
    jtag_tap_gowin u_tap_ctrl (
        .sysclk         (sysclk),

        .tdi            (tap_tdi),
        .tdo            (tap_tdo),
        .capture        (tap_capture),
        .shift_in       (tap_shift_in),
        .shift_out      (tap_shift_out),
        .update         (tap_update),
        .sel            (tap_sel),

        .tms_pad_i      (tms_pad_i),
        .tck_pad_i      (tck_pad_i),
        .tdi_pad_i      (tdi_pad_i),
        .tdo_pad_o      (tdo_pad_o)
    );


    reset_sync u_rst_sync_ctrl (
        .clk            (sysclk),
        .arst           (sample_rst),
        .srst           (jtag_rst_ctrl)
    );

    // ---- Register interface ----
    jtag_reg_iface u_reg (
        .arst           (jtag_rst_ctrl),

        .tck            (sysclk),
        .tdi            (tap_tdi),
        .tdo            (tap_tdo[0]),
        .capture        (tap_capture[0]),
        .shift_in_en    (tap_shift_in[0]),
        .shift_out_en   (tap_shift_out[0]),
        .update         (tap_update[0]),
        .sel            (tap_sel[0]),

        .reg_clk        (jtag_clk),
        .reg_rst        (jtag_rst),
        .reg_wr_en      (jtag_wr_en),
        .reg_rd_en      (jtag_rd_en),
        .reg_addr       (jtag_addr),
        .reg_wdata      (jtag_wdata),
        .reg_rdata      (jtag_rdata)
    );

    // ---- ELA + optional EIO via address mux ----
    // No burst engine — Gowin has only one JTAG chain.
    // Sample readback uses word-by-word DATA register reads.
    generate
        if (EIO_EN != 0) begin : g_shared
            wire        ela_wr_en, ela_rd_en;
            wire [15:0] ela_addr;
            wire [31:0] ela_wdata, ela_rdata;
            wire        eio_wr_en_i;
            wire        eio_rd_en_unused;
            wire [15:0] eio_addr_i;
            wire [31:0] eio_wdata_i, eio_rdata_i;
            wire        ela_trigger_out_unused;
            wire        ela_armed_out_unused;

            fcapz_regbus_mux u_mux (
                .addr(jtag_addr), .wr_en(jtag_wr_en), .rd_en(jtag_rd_en),
                .wdata(jtag_wdata), .rdata(jtag_rdata),
                .a_wr_en(ela_wr_en), .a_rd_en(ela_rd_en),
                .a_addr(ela_addr), .a_wdata(ela_wdata), .a_rdata(ela_rdata),
                .b_wr_en(eio_wr_en_i), .b_rd_en(eio_rd_en_unused),
                .b_addr(eio_addr_i), .b_wdata(eio_wdata_i), .b_rdata(eio_rdata_i)
            );

            fcapz_ela #(
                .SAMPLE_W(SAMPLE_W), .DEPTH(DEPTH),
                .TRIG_STAGES(TRIG_STAGES), .STOR_QUAL(STOR_QUAL),
                .INPUT_PIPE(INPUT_PIPE), .NUM_CHANNELS(NUM_CHANNELS),
                .TIMESTAMP_W(TIMESTAMP_W), .REL_COMPARE(REL_COMPARE),
                .DUAL_COMPARE(DUAL_COMPARE), .USER1_DATA_EN(USER1_DATA_EN)
            ) u_ela (
                .sample_clk(sample_clk), .sample_rst(sample_rst),
                .probe_in(probe_in), .trigger_in(1'b0),
                .trigger_out(ela_trigger_out_unused),
                .armed_out(ela_armed_out_unused),
                .jtag_clk(jtag_clk), .jtag_rst(jtag_rst),
                .jtag_wr_en(ela_wr_en), .jtag_rd_en(ela_rd_en),
                .jtag_addr(ela_addr), .jtag_wdata(ela_wdata),
                .jtag_rdata(ela_rdata),
                .burst_rd_addr(burst_rd_addr_dummy),
                .burst_rd_data(burst_rd_data_unused),
                .burst_rd_ts_data(burst_rd_ts_data_unused),
                .burst_start(burst_start_unused),
                .burst_timestamp(burst_timestamp_unused),
                .burst_start_ptr(burst_start_ptr_unused)
            );

            fcapz_eio #(.IN_W(EIO_IN_W), .OUT_W(EIO_OUT_W)) u_eio (
                .probe_in(eio_probe_in), .probe_out(eio_probe_out),
                .jtag_clk(jtag_clk), .jtag_rst(jtag_rst),
                .jtag_wr_en(eio_wr_en_i),
                .jtag_addr(eio_addr_i), .jtag_wdata(eio_wdata_i),
                .jtag_rdata(eio_rdata_i)
            );
        end else begin : g_ela_only
            wire ela_trigger_out_unused;
            wire ela_armed_out_unused;

            fcapz_ela #(
                .SAMPLE_W(SAMPLE_W), .DEPTH(DEPTH),
                .TRIG_STAGES(TRIG_STAGES), .STOR_QUAL(STOR_QUAL),
                .INPUT_PIPE(INPUT_PIPE), .NUM_CHANNELS(NUM_CHANNELS),
                .TIMESTAMP_W(TIMESTAMP_W), .REL_COMPARE(REL_COMPARE),
                .DUAL_COMPARE(DUAL_COMPARE), .USER1_DATA_EN(USER1_DATA_EN)
            ) u_ela (
                .sample_clk(sample_clk), .sample_rst(sample_rst),
                .probe_in(probe_in), .trigger_in(1'b0),
                .trigger_out(ela_trigger_out_unused),
                .armed_out(ela_armed_out_unused),
                .jtag_clk(jtag_clk), .jtag_rst(jtag_rst),
                .jtag_wr_en(jtag_wr_en), .jtag_rd_en(jtag_rd_en),
                .jtag_addr(jtag_addr), .jtag_wdata(jtag_wdata),
                .jtag_rdata(jtag_rdata),
                .burst_rd_addr(burst_rd_addr_dummy),
                .burst_rd_data(burst_rd_data_unused),
                .burst_rd_ts_data(burst_rd_ts_data_unused),
                .burst_start(burst_start_unused),
                .burst_timestamp(burst_timestamp_unused),
                .burst_start_ptr(burst_start_ptr_unused)
            );

            assign eio_probe_out = {EIO_OUT_W{1'b0}};
        end
    endgenerate

endmodule
