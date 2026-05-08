// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Mixed debug wrapper: multiple ELAs plus optional EIOs behind one USER chain.
// Slot order is ELA[0..NUM_ELAS-1], then EIO[0..NUM_EIOS-1].

module fcapz_debug_multi_xilinx7 #(
    parameter NUM_ELAS = 2,
    parameter EIO_EN = 1,
    parameter NUM_EIOS = EIO_EN,
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
    parameter USER1_DATA_EN = 1,
    parameter EIO_IN_W = 1,
    parameter EIO_OUT_W = 1
) (
    input  wire [NUM_ELAS-1:0] ela_sample_clk,
    input  wire [NUM_ELAS-1:0] ela_sample_rst,
    input  wire [NUM_ELAS*(PROBE_MUX_W > 0 ? PROBE_MUX_W : SAMPLE_W*NUM_CHANNELS)-1:0] ela_probe_in,
    input  wire [NUM_ELAS-1:0] ela_trigger_in,
    output wire [NUM_ELAS-1:0] ela_trigger_out,
    output wire [NUM_ELAS-1:0] ela_armed_out,
    input  wire [((NUM_EIOS > 0) ? NUM_EIOS : 1)*EIO_IN_W-1:0] eio_probe_in,
    output wire [((NUM_EIOS > 0) ? NUM_EIOS : 1)*EIO_OUT_W-1:0] eio_probe_out
);

    localparam EIO_COUNT = (NUM_EIOS > 0) ? NUM_EIOS : 0;
    localparam EIO_PORT_COUNT = (NUM_EIOS > 0) ? NUM_EIOS : 1;
    localparam NUM_SLOTS = NUM_ELAS + EIO_COUNT;
    localparam PTR_W = $clog2(DEPTH);
    localparam TS_W_SAFE = (TIMESTAMP_W > 0) ? TIMESTAMP_W : 1;
    localparam PROBE_W = (PROBE_MUX_W > 0) ? PROBE_MUX_W : SAMPLE_W*NUM_CHANNELS;
    localparam BURST_SEG_DEPTH = DEPTH / NUM_SEGMENTS;
    localparam EIO_SLOT_BASE = NUM_ELAS;
    localparam [NUM_SLOTS*16-1:0] SLOT_CORE_IDS =
        ({NUM_SLOTS{16'h494F}} << (NUM_ELAS*16)) | {NUM_ELAS{16'h4C41}};
    localparam [NUM_SLOTS-1:0] SLOT_HAS_BURST =
        {NUM_SLOTS{1'b1}} >> EIO_COUNT;
    wire debug_arst = |ela_sample_rst;

    wire tap_tck, tap_tdi, tap_tdo;
    wire tap_capture, tap_shift, tap_update, tap_sel;
    wire jtag_rst_ctrl;
    wire jtag_clk, jtag_rst;
    wire jtag_wr_en, jtag_rd_en;
    wire [15:0] jtag_addr;
    wire [31:0] jtag_wdata, jtag_rdata;

    wire [PTR_W-1:0] burst_rd_addr;
    wire [SAMPLE_W-1:0] burst_rd_data;
    wire [TS_W_SAFE-1:0] burst_rd_ts_data;
    wire burst_start;
    wire burst_timestamp;
    wire [PTR_W-1:0] burst_start_ptr;

    wire [NUM_SLOTS-1:0] slot_wr_en;
    wire [NUM_SLOTS-1:0] slot_rd_en;
    wire [NUM_SLOTS*16-1:0] slot_addr;
    wire [NUM_SLOTS*32-1:0] slot_wdata;
    wire [NUM_SLOTS*32-1:0] slot_rdata;
    wire [NUM_SLOTS*PTR_W-1:0] slot_burst_rd_addr;
    wire [NUM_SLOTS*SAMPLE_W-1:0] slot_burst_rd_data;
    wire [NUM_SLOTS*TS_W_SAFE-1:0] slot_burst_rd_ts_data;
    wire [NUM_SLOTS-1:0] slot_burst_start;
    wire [NUM_SLOTS-1:0] slot_burst_timestamp;
    wire [NUM_SLOTS*PTR_W-1:0] slot_burst_start_ptr;

    jtag_tap_xilinx7 #(.CHAIN(CTRL_CHAIN)) u_tap_ctrl (
        .tck(tap_tck), .tdi(tap_tdi), .tdo(tap_tdo),
        .capture(tap_capture), .shift(tap_shift),
        .update(tap_update), .sel(tap_sel)
    );

    reset_sync u_rst_sync_ctrl (
        .clk(tap_tck),
        .arst(debug_arst),
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
        .NUM_SLOTS(NUM_SLOTS),
        .SAMPLE_W(SAMPLE_W),
        .TIMESTAMP_W(TIMESTAMP_W),
        .DEPTH(DEPTH),
        .SLOT_CORE_IDS(SLOT_CORE_IDS),
        .SLOT_HAS_BURST(SLOT_HAS_BURST)
    ) u_manager (
        .jtag_clk(jtag_clk),
        .jtag_rst(jtag_rst),
        .jtag_wr_en(jtag_wr_en),
        .jtag_rd_en(jtag_rd_en),
        .jtag_addr(jtag_addr),
        .jtag_wdata(jtag_wdata),
        .jtag_rdata(jtag_rdata),
        .slot_wr_en(slot_wr_en),
        .slot_rd_en(slot_rd_en),
        .slot_addr(slot_addr),
        .slot_wdata(slot_wdata),
        .slot_rdata(slot_rdata),
        .burst_rd_addr(burst_rd_addr),
        .slot_burst_rd_addr(slot_burst_rd_addr),
        .slot_burst_rd_data(slot_burst_rd_data),
        .slot_burst_rd_ts_data(slot_burst_rd_ts_data),
        .slot_burst_start(slot_burst_start),
        .slot_burst_timestamp(slot_burst_timestamp),
        .slot_burst_start_ptr(slot_burst_start_ptr),
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
                .sample_clk(ela_sample_clk[i]),
                .sample_rst(ela_sample_rst[i]),
                .probe_in(ela_probe_in[i*PROBE_W +: PROBE_W]),
                .trigger_in(ela_trigger_in[i]),
                .trigger_out(ela_trigger_out[i]),
                .armed_out(ela_armed_out[i]),
                .jtag_clk(jtag_clk),
                .jtag_rst(jtag_rst),
                .jtag_wr_en(slot_wr_en[i]),
                .jtag_rd_en(slot_rd_en[i]),
                .jtag_addr(slot_addr[i*16 +: 16]),
                .jtag_wdata(slot_wdata[i*32 +: 32]),
                .jtag_rdata(slot_rdata[i*32 +: 32]),
                .burst_rd_addr(slot_burst_rd_addr[i*PTR_W +: PTR_W]),
                .burst_rd_data(slot_burst_rd_data[i*SAMPLE_W +: SAMPLE_W]),
                .burst_rd_ts_data(slot_burst_rd_ts_data[i*TS_W_SAFE +: TS_W_SAFE]),
                .burst_start(slot_burst_start[i]),
                .burst_timestamp(slot_burst_timestamp[i]),
                .burst_start_ptr(slot_burst_start_ptr[i*PTR_W +: PTR_W])
            );
        end

        for (i = 0; i < EIO_COUNT; i = i + 1) begin : g_eios
            fcapz_eio #(
                .IN_W(EIO_IN_W),
                .OUT_W(EIO_OUT_W)
            ) u_eio (
                .probe_in(eio_probe_in[i*EIO_IN_W +: EIO_IN_W]),
                .probe_out(eio_probe_out[i*EIO_OUT_W +: EIO_OUT_W]),
                .jtag_clk(jtag_clk),
                .jtag_rst(jtag_rst),
                .jtag_wr_en(slot_wr_en[EIO_SLOT_BASE+i]),
                .jtag_addr(slot_addr[(EIO_SLOT_BASE+i)*16 +: 16]),
                .jtag_wdata(slot_wdata[(EIO_SLOT_BASE+i)*32 +: 32]),
                .jtag_rdata(slot_rdata[(EIO_SLOT_BASE+i)*32 +: 32])
            );

            assign slot_burst_rd_data[(EIO_SLOT_BASE+i)*SAMPLE_W +: SAMPLE_W] = {SAMPLE_W{1'b0}};
            assign slot_burst_rd_ts_data[(EIO_SLOT_BASE+i)*TS_W_SAFE +: TS_W_SAFE] = {TS_W_SAFE{1'b0}};
            assign slot_burst_start[EIO_SLOT_BASE+i] = 1'b0;
            assign slot_burst_timestamp[EIO_SLOT_BASE+i] = 1'b0;
            assign slot_burst_start_ptr[(EIO_SLOT_BASE+i)*PTR_W +: PTR_W] = {PTR_W{1'b0}};
        end

        if (EIO_COUNT == 0) begin : g_no_eio
            assign eio_probe_out = {EIO_PORT_COUNT*EIO_OUT_W{1'b0}};
        end
    endgenerate

endmodule
