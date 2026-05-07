// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Multi-ELA Xilinx wrapper: one BSCAN USER chain, N homogeneous ELA slots.
//
// Slot selection lives in fcapz_core_manager at 0xF000..0xF0FF.  Normal ELA
// registers stay at 0x0000 and target the active slot.  Reset selects slot 0,
// preserving legacy host behavior.

module fcapz_ela_multi_xilinx7 #(
    parameter NUM_ELAS = 2,
    parameter SAMPLE_W = 8,
    parameter DEPTH = 1024,
    parameter TRIG_STAGES = 1,
    parameter STOR_QUAL = 0,
    parameter INPUT_PIPE = 0,
    parameter NUM_CHANNELS = 1,
    parameter DECIM_EN = 0,
    parameter EXT_TRIG_EN = 0,
    parameter TIMESTAMP_W = 0,
    parameter NUM_SEGMENTS = 1,
    parameter PROBE_MUX_W = 0,
    parameter STARTUP_ARM = 0,
    parameter DEFAULT_TRIG_EXT = 0,
    parameter BURST_W = 256,
    parameter CTRL_CHAIN = 1,
    parameter REL_COMPARE = 0,
    parameter DUAL_COMPARE = 1,
    parameter USER1_DATA_EN = 1
) (
    input  wire sample_clk,
    input  wire sample_rst,
    input  wire [NUM_ELAS*(PROBE_MUX_W > 0 ? PROBE_MUX_W : SAMPLE_W*NUM_CHANNELS)-1:0] probe_in,
    input  wire [NUM_ELAS-1:0] trigger_in,
    output wire [NUM_ELAS-1:0] trigger_out,
    output wire [NUM_ELAS-1:0] armed_out
);

    localparam PTR_W = $clog2(DEPTH);
    localparam TS_W_SAFE = (TIMESTAMP_W > 0) ? TIMESTAMP_W : 1;
    localparam PROBE_W = (PROBE_MUX_W > 0) ? PROBE_MUX_W : SAMPLE_W*NUM_CHANNELS;
    localparam BURST_SEG_DEPTH = DEPTH / NUM_SEGMENTS;

    // TAP signals -- shared control / single-chain burst.
    wire tap_tck, tap_tdi, tap_tdo;
    wire tap_capture, tap_shift, tap_update, tap_sel;
    wire jtag_rst_ctrl;

    // Shared JTAG register / pipe interface.
    wire jtag_clk, jtag_rst;
    wire jtag_wr_en, jtag_rd_en;
    wire [15:0] jtag_addr;
    wire [31:0] jtag_wdata, jtag_rdata;

    // Shared burst interface after manager selection.
    wire [PTR_W-1:0] burst_rd_addr;
    wire [SAMPLE_W-1:0] burst_rd_data;
    wire [TS_W_SAFE-1:0] burst_rd_ts_data;
    wire burst_start;
    wire burst_timestamp;
    wire [PTR_W-1:0] burst_start_ptr;

    // Per-slot manager <-> ELA buses.
    wire [NUM_ELAS-1:0] ela_wr_en;
    wire [NUM_ELAS-1:0] ela_rd_en;
    wire [NUM_ELAS*16-1:0] ela_addr;
    wire [NUM_ELAS*32-1:0] ela_wdata;
    wire [NUM_ELAS*32-1:0] ela_rdata;
    wire [NUM_ELAS*PTR_W-1:0] ela_burst_rd_addr;
    wire [NUM_ELAS*SAMPLE_W-1:0] ela_burst_rd_data;
    wire [NUM_ELAS*TS_W_SAFE-1:0] ela_burst_rd_ts_data;
    wire [NUM_ELAS-1:0] ela_burst_start;
    wire [NUM_ELAS-1:0] ela_burst_timestamp;
    wire [NUM_ELAS*PTR_W-1:0] ela_burst_start_ptr;

    jtag_tap_xilinx7 #(.CHAIN(CTRL_CHAIN)) u_tap_ctrl (
        .tck(tap_tck), .tdi(tap_tdi), .tdo(tap_tdo),
        .capture(tap_capture), .shift(tap_shift),
        .update(tap_update), .sel(tap_sel)
    );

    reset_sync u_rst_sync_ctrl (
        .clk(tap_tck),
        .arst(sample_rst),
        .srst(jtag_rst_ctrl)
    );

    jtag_pipe_iface #(
        .SAMPLE_W(SAMPLE_W),
        .TIMESTAMP_W(TIMESTAMP_W),
        .DEPTH(DEPTH),
        .BURST_W(BURST_W),
        .SEG_DEPTH(BURST_SEG_DEPTH),
        .BURST_PTR_ADDR(16'h002C)
    ) u_pipe (
        .arst(jtag_rst_ctrl),
        .tck(tap_tck), .tdi(tap_tdi), .tdo(tap_tdo),
        .capture(tap_capture), .shift_en(tap_shift),
        .update(tap_update), .sel(tap_sel),
        .reg_clk(jtag_clk), .reg_rst(jtag_rst),
        .reg_wr_en(jtag_wr_en), .reg_rd_en(jtag_rd_en),
        .reg_addr(jtag_addr), .reg_wdata(jtag_wdata),
        .reg_rdata(jtag_rdata),
        .mem_addr(burst_rd_addr),
        .sample_data(burst_rd_data),
        .timestamp_data(burst_rd_ts_data),
        .burst_start(burst_start),
        .burst_timestamp(burst_timestamp),
        .burst_ptr_in(burst_start_ptr)
    );

    fcapz_core_manager #(
        .NUM_SLOTS(NUM_ELAS),
        .SAMPLE_W(SAMPLE_W),
        .TIMESTAMP_W(TIMESTAMP_W),
        .DEPTH(DEPTH),
        .SLOT_CORE_IDS({NUM_ELAS{16'h4C41}}),
        .SLOT_HAS_BURST({NUM_ELAS{1'b1}})
    ) u_manager (
        .jtag_clk(jtag_clk),
        .jtag_rst(jtag_rst),
        .jtag_wr_en(jtag_wr_en),
        .jtag_rd_en(jtag_rd_en),
        .jtag_addr(jtag_addr),
        .jtag_wdata(jtag_wdata),
        .jtag_rdata(jtag_rdata),
        .slot_wr_en(ela_wr_en),
        .slot_rd_en(ela_rd_en),
        .slot_addr(ela_addr),
        .slot_wdata(ela_wdata),
        .slot_rdata(ela_rdata),
        .burst_rd_addr(burst_rd_addr),
        .slot_burst_rd_addr(ela_burst_rd_addr),
        .slot_burst_rd_data(ela_burst_rd_data),
        .slot_burst_rd_ts_data(ela_burst_rd_ts_data),
        .slot_burst_start(ela_burst_start),
        .slot_burst_timestamp(ela_burst_timestamp),
        .slot_burst_start_ptr(ela_burst_start_ptr),
        .burst_rd_data(burst_rd_data),
        .burst_rd_ts_data(burst_rd_ts_data),
        .burst_start(burst_start),
        .burst_timestamp(burst_timestamp),
        .burst_start_ptr(burst_start_ptr)
    );

    genvar i;
    generate
        for (i = 0; i < NUM_ELAS; i = i + 1) begin : g_elas
            fcapz_ela #(
                .SAMPLE_W(SAMPLE_W),
                .DEPTH(DEPTH),
                .TRIG_STAGES(TRIG_STAGES),
                .STOR_QUAL(STOR_QUAL),
                .INPUT_PIPE(INPUT_PIPE),
                .NUM_CHANNELS(NUM_CHANNELS),
                .DECIM_EN(DECIM_EN),
                .EXT_TRIG_EN(EXT_TRIG_EN),
                .TIMESTAMP_W(TIMESTAMP_W),
                .NUM_SEGMENTS(NUM_SEGMENTS),
                .PROBE_MUX_W(PROBE_MUX_W),
                .STARTUP_ARM(STARTUP_ARM),
                .DEFAULT_TRIG_EXT(DEFAULT_TRIG_EXT),
                .REL_COMPARE(REL_COMPARE),
                .DUAL_COMPARE(DUAL_COMPARE),
                .USER1_DATA_EN(USER1_DATA_EN)
            ) u_ela (
                .sample_clk(sample_clk),
                .sample_rst(sample_rst),
                .probe_in(probe_in[i*PROBE_W +: PROBE_W]),
                .trigger_in(trigger_in[i]),
                .trigger_out(trigger_out[i]),
                .armed_out(armed_out[i]),
                .jtag_clk(jtag_clk),
                .jtag_rst(jtag_rst),
                .jtag_wr_en(ela_wr_en[i]),
                .jtag_rd_en(ela_rd_en[i]),
                .jtag_addr(ela_addr[i*16 +: 16]),
                .jtag_wdata(ela_wdata[i*32 +: 32]),
                .jtag_rdata(ela_rdata[i*32 +: 32]),
                .burst_rd_addr(ela_burst_rd_addr[i*PTR_W +: PTR_W]),
                .burst_rd_data(ela_burst_rd_data[i*SAMPLE_W +: SAMPLE_W]),
                .burst_rd_ts_data(ela_burst_rd_ts_data[i*TS_W_SAFE +: TS_W_SAFE]),
                .burst_start(ela_burst_start[i]),
                .burst_timestamp(ela_burst_timestamp[i]),
                .burst_start_ptr(ela_burst_start_ptr[i*PTR_W +: PTR_W])
            );
        end
    endgenerate

endmodule
