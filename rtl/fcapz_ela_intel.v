// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero ELA wrapper for Intel / Altera.
//
// Single-instantiation wrapper: bundles the ELA core, register interface,
// burst read engine, and two sld_virtual_jtag instances.
//
// Usage:
//   fcapz_ela_intel #(.SAMPLE_W(8), .DEPTH(1024)) u_ela (
//       .sample_clk(clk), .sample_rst(rst), .probe_in(signals)
//   );

module fcapz_ela_intel #(
    parameter SAMPLE_W    = 8,
    parameter DEPTH       = 1024,
    parameter TRIG_STAGES = 1,
    parameter STOR_QUAL   = 0,
    parameter INPUT_PIPE  = 0,
    parameter NUM_CHANNELS = 1,
    parameter BURST_W     = 256,
    parameter CTRL_CHAIN  = 1,   // BSCANE2 USER chain for control
    parameter DATA_CHAIN  = 2    // BSCANE2 USER chain for burst data
) (
    input  wire                          sample_clk,
    input  wire                          sample_rst,
    input  wire [SAMPLE_W*NUM_CHANNELS-1:0] probe_in
);

    localparam PTR_W = $clog2(DEPTH);

    // TAP signals — control (USER1)
    wire tap1_tck, tap1_tdi, tap1_tdo;
    wire tap1_capture, tap1_shift, tap1_update, tap1_sel;

    // TAP signals — burst data (USER2)
    wire tap2_tck, tap2_tdi, tap2_tdo;
    wire tap2_capture, tap2_shift, tap2_update, tap2_sel;

    // Register bus
    wire        jtag_clk, jtag_rst;
    wire        jtag_wr_en, jtag_rd_en;
    wire [15:0] jtag_addr;
    wire [31:0] jtag_wdata, jtag_rdata;

    // Burst interface
    wire [PTR_W-1:0]    burst_rd_addr;
    wire [SAMPLE_W-1:0] burst_rd_data;
    wire                burst_start;
    wire [PTR_W-1:0]    burst_start_ptr;

    // ---- TAP wrappers ----
    jtag_tap_intel #(.CHAIN(CTRL_CHAIN)) u_tap_ctrl (
        .tck(tap1_tck), .tdi(tap1_tdi), .tdo(tap1_tdo),
        .capture(tap1_capture), .shift(tap1_shift),
        .update(tap1_update), .sel(tap1_sel)
    );

    jtag_tap_intel #(.CHAIN(DATA_CHAIN)) u_tap_data (
        .tck(tap2_tck), .tdi(tap2_tdi), .tdo(tap2_tdo),
        .capture(tap2_capture), .shift(tap2_shift),
        .update(tap2_update), .sel(tap2_sel)
    );

    // ---- Register interface ----
    jtag_reg_iface u_reg (
        .arst(sample_rst),
        .tck(tap1_tck), .tdi(tap1_tdi), .tdo(tap1_tdo),
        .capture(tap1_capture), .shift_en(tap1_shift),
        .update(tap1_update), .sel(tap1_sel),
        .reg_clk(jtag_clk), .reg_rst(jtag_rst),
        .reg_wr_en(jtag_wr_en), .reg_rd_en(jtag_rd_en),
        .reg_addr(jtag_addr), .reg_wdata(jtag_wdata),
        .reg_rdata(jtag_rdata)
    );

    // ---- ELA core ----
    fcapz_ela #(
        .SAMPLE_W(SAMPLE_W), .DEPTH(DEPTH),
        .TRIG_STAGES(TRIG_STAGES), .STOR_QUAL(STOR_QUAL),
        .INPUT_PIPE(INPUT_PIPE), .NUM_CHANNELS(NUM_CHANNELS)
    ) u_ela (
        .sample_clk(sample_clk), .sample_rst(sample_rst),
        .probe_in(probe_in),
        .jtag_clk(jtag_clk), .jtag_rst(jtag_rst),
        .jtag_wr_en(jtag_wr_en), .jtag_rd_en(jtag_rd_en),
        .jtag_addr(jtag_addr), .jtag_wdata(jtag_wdata),
        .jtag_rdata(jtag_rdata),
        .burst_rd_addr(burst_rd_addr), .burst_rd_data(burst_rd_data),
        .burst_start(burst_start), .burst_start_ptr(burst_start_ptr)
    );

    // ---- Burst read engine ----
    jtag_burst_read #(
        .SAMPLE_W(SAMPLE_W), .DEPTH(DEPTH), .BURST_W(BURST_W)
    ) u_burst (
        .arst(sample_rst),
        .tck(tap2_tck), .tdi(tap2_tdi), .tdo(tap2_tdo),
        .capture(tap2_capture), .shift_en(tap2_shift),
        .update(tap2_update), .sel(tap2_sel),
        .mem_addr(burst_rd_addr), .mem_data(burst_rd_data),
        .burst_start(burst_start), .burst_ptr_in(burst_start_ptr)
    );

endmodule
