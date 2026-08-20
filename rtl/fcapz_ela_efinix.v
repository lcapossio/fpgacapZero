// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero ELA wrapper for Efinix Trion / Titanium.
//
// Bundles the ELA core, register interface, and burst read engine, and maps
// two Efinix JTAG User TAP blocks onto the two fcapz chains (control + burst).
//
// Efinix specifics: the JTAG User TAP is configured in the Efinity Interface
// Designer, not instantiated as an RTL primitive, so its signals reach the
// fabric as top-level ports. This wrapper therefore *exposes* the two User TAP
// port groups (jtag1_* control, jtag2_* burst) instead of hiding a primitive
// the way the Xilinx/Intel wrappers do. Wire each group to one Interface
// Designer JTAG User TAP block at your design top; a Trion device has two hard
// User TAP blocks (USER1, USER2). See jtag_tap_efinix.v for the signal mapping.
//
// Usage (top level):
//   fcapz_ela_efinix #(.SAMPLE_W(8), .DEPTH(1024)) u_ela (
//       .sample_clk(clk), .sample_rst(rst), .probe_in(signals),
//       .trigger_in(1'b0), .trigger_out(), .armed_out(),
//       // USER1 block -> control chain
//       .jtag1_tck(u1_tck), .jtag1_drck(u1_drck), .jtag1_tdi(u1_tdi),
//       .jtag1_tdo(u1_tdo), .jtag1_capture(u1_cap), .jtag1_shift(u1_sh),
//       .jtag1_update(u1_up), .jtag1_sel(u1_sel),
//       // USER2 block -> burst-data chain
//       .jtag2_tck(u2_tck), .jtag2_drck(u2_drck), .jtag2_tdi(u2_tdi),
//       .jtag2_tdo(u2_tdo), .jtag2_capture(u2_cap), .jtag2_shift(u2_sh),
//       .jtag2_update(u2_up), .jtag2_sel(u2_sel)
//   );

module fcapz_ela_efinix #(
    parameter SAMPLE_W    = 8,
    parameter DEPTH       = 1024,
    parameter TRIG_STAGES = 1,
    parameter STOR_QUAL   = 0,
    parameter INPUT_PIPE  = 0,
    parameter NUM_CHANNELS = 1,
    parameter DECIM_EN    = 0,
    parameter EXT_TRIG_EN = 0,
    parameter TIMESTAMP_W = 0,
    parameter NUM_SEGMENTS = 1,
    parameter PROBE_MUX_W = 0,
    parameter STARTUP_ARM = 0,
    parameter DEFAULT_TRIG_EXT = 0,
    parameter BURST_W     = 256,
    parameter REL_COMPARE = 0,
    parameter DUAL_COMPARE = 1,
    parameter USER1_DATA_EN = 1
) (
    input  wire                          sample_clk,
    input  wire                          sample_rst,
    input  wire [SAMPLE_W*NUM_CHANNELS-1:0] probe_in,
    input  wire                          trigger_in,
    output wire                          trigger_out,
    output wire                          armed_out,

    // Efinix JTAG User TAP #1 (control chain) -- wire to an Interface Designer
    // JTAG User TAP block (e.g. USER1).
    input  wire                          jtag1_tck,
    input  wire                          jtag1_drck,
    input  wire                          jtag1_tdi,
    output wire                          jtag1_tdo,
    input  wire                          jtag1_capture,
    input  wire                          jtag1_shift,
    input  wire                          jtag1_update,
    input  wire                          jtag1_sel,

    // Efinix JTAG User TAP #2 (burst-data chain) -- wire to a second Interface
    // Designer JTAG User TAP block (e.g. USER2).
    input  wire                          jtag2_tck,
    input  wire                          jtag2_drck,
    input  wire                          jtag2_tdi,
    output wire                          jtag2_tdo,
    input  wire                          jtag2_capture,
    input  wire                          jtag2_shift,
    input  wire                          jtag2_update,
    input  wire                          jtag2_sel
);

    localparam PTR_W = $clog2(DEPTH);
    // Segment depth for burst read ring-wrap (equals DEPTH when unsegmented).
    localparam BURST_SEG_DEPTH = DEPTH / NUM_SEGMENTS;

    // TAP signals -- control (USER1)
    wire tap1_tck, tap1_tdi, tap1_tdo;
    wire tap1_capture, tap1_shift, tap1_update, tap1_sel;

    // TAP signals -- burst data (USER2)
    wire tap2_tck, tap2_tdi, tap2_tdo;
    wire tap2_capture, tap2_shift, tap2_update, tap2_sel;

    // Register bus
    wire        jtag_clk, jtag_rst;
    wire        jtag_wr_en, jtag_rd_en;
    wire [15:0] jtag_addr;
    wire [31:0] jtag_wdata, jtag_rdata;

    // Burst interface
    wire [PTR_W-1:0]    burst_rd_addr;
    wire                burst_rd_active;
    wire [SAMPLE_W-1:0] burst_rd_data;
    wire [((TIMESTAMP_W > 0) ? TIMESTAMP_W : 1)-1:0] burst_rd_ts_data;
    wire                burst_start;
    wire                burst_timestamp;
    wire [PTR_W-1:0]    burst_start_ptr;
    wire                jtag_rst_ctrl;
    wire                jtag_rst_data;

    // ---- TAP adapters (map the exposed User TAP ports onto the fcapz TAP) ----
    jtag_tap_efinix u_tap_ctrl (
        .user_tck(jtag1_tck), .user_drck(jtag1_drck),
        .user_tdi(jtag1_tdi), .user_tdo(jtag1_tdo),
        .user_capture(jtag1_capture), .user_shift(jtag1_shift),
        .user_update(jtag1_update), .user_sel(jtag1_sel),
        .tck(tap1_tck), .tdi(tap1_tdi), .tdo(tap1_tdo),
        .capture(tap1_capture), .shift(tap1_shift),
        .update(tap1_update), .sel(tap1_sel)
    );

    jtag_tap_efinix u_tap_data (
        .user_tck(jtag2_tck), .user_drck(jtag2_drck),
        .user_tdi(jtag2_tdi), .user_tdo(jtag2_tdo),
        .user_capture(jtag2_capture), .user_shift(jtag2_shift),
        .user_update(jtag2_update), .user_sel(jtag2_sel),
        .tck(tap2_tck), .tdi(tap2_tdi), .tdo(tap2_tdo),
        .capture(tap2_capture), .shift(tap2_shift),
        .update(tap2_update), .sel(tap2_sel)
    );

    reset_sync u_rst_sync_ctrl (
        .clk(tap1_tck),
        .arst(sample_rst),
        .srst(jtag_rst_ctrl)
    );

    reset_sync u_rst_sync_data (
        .clk(tap2_tck),
        .arst(sample_rst),
        .srst(jtag_rst_data)
    );

    // ---- Register interface ----
    jtag_reg_iface u_reg (
        .arst(jtag_rst_ctrl),
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
        .INPUT_PIPE(INPUT_PIPE), .NUM_CHANNELS(NUM_CHANNELS),
        .DECIM_EN(DECIM_EN), .EXT_TRIG_EN(EXT_TRIG_EN),
        .TIMESTAMP_W(TIMESTAMP_W), .NUM_SEGMENTS(NUM_SEGMENTS),
        .PROBE_MUX_W(PROBE_MUX_W), .STARTUP_ARM(STARTUP_ARM),
        .DEFAULT_TRIG_EXT(DEFAULT_TRIG_EXT), .REL_COMPARE(REL_COMPARE),
        .DUAL_COMPARE(DUAL_COMPARE), .USER1_DATA_EN(USER1_DATA_EN)
    ) u_ela (
        .sample_clk(sample_clk), .sample_rst(sample_rst),
        .probe_in(probe_in),
        .trigger_in(trigger_in),
        .trigger_out(trigger_out),
        .armed_out(armed_out),
        .jtag_clk(jtag_clk), .jtag_rst(jtag_rst),
        .jtag_wr_en(jtag_wr_en), .jtag_rd_en(jtag_rd_en),
        .jtag_addr(jtag_addr), .jtag_wdata(jtag_wdata),
        .jtag_rdata(jtag_rdata),
        .burst_rd_active(burst_rd_active),
        .burst_rd_addr(burst_rd_addr), .burst_rd_data(burst_rd_data),
        .burst_rd_ts_data(burst_rd_ts_data),
        .burst_start(burst_start), .burst_timestamp(burst_timestamp),
        .burst_start_ptr(burst_start_ptr)
    );

    // ---- Burst read engine ----
    jtag_burst_read #(
        .SAMPLE_W(SAMPLE_W), .TIMESTAMP_W(TIMESTAMP_W),
        .DEPTH(DEPTH), .BURST_W(BURST_W), .SEG_DEPTH(BURST_SEG_DEPTH)
    ) u_burst (
        .arst(jtag_rst_data),
        .tck(tap2_tck), .tdi(tap2_tdi), .tdo(tap2_tdo),
        .capture(tap2_capture), .shift_en(tap2_shift),
        .update(tap2_update), .sel(tap2_sel),
        .mem_addr(burst_rd_addr),
        .mem_active(burst_rd_active),
        .sample_data(burst_rd_data), .timestamp_data(burst_rd_ts_data),
        .burst_start(burst_start), .burst_timestamp(burst_timestamp),
        .burst_ptr_in(burst_start_ptr)
    );

endmodule
