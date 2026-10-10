// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - www.bard0.com - <hello@bard0.com>

`timescale 1ns/1ps

// Vendor-free mixed debug wrapper: multiple ELAs plus optional EIOs behind
// one JTAG chain, driven by any TAP wrapper with the standard
// tck/tdi/tdo/capture/shift/update/sel interface (jtag_tap_<vendor>).
// Slot order is ELA[0..NUM_ELAS-1], then EIO[0..NUM_EIOS-1].
//
// Registers and burst readout share the one chain (jtag_pipe_iface). The
// per-vendor fcapz_debug_multi_<vendor> wrappers only add the TAP instance.

module fcapz_debug_multi #(
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
    parameter REL_COMPARE = 0,
    parameter DUAL_COMPARE = 1,
    parameter USER1_DATA_EN = 1,
    parameter EIO_IN_W = 1,
    parameter EIO_OUT_W = 1,
    parameter ELA_PORT_COUNT = (NUM_ELAS > 0) ? NUM_ELAS : 1,
    // Per-slot overrides. The scalar parameters above remain the max/default
    // shape so existing instantiations can keep using one shared setting.
    parameter [ELA_PORT_COUNT*32-1:0] ELA_SAMPLE_WS = {ELA_PORT_COUNT{SAMPLE_W}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_DEPTHS = {ELA_PORT_COUNT{DEPTH}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_TRIG_STAGES = {ELA_PORT_COUNT{TRIG_STAGES}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_STOR_QUALS = {ELA_PORT_COUNT{STOR_QUAL}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_INPUT_PIPES = {ELA_PORT_COUNT{INPUT_PIPE}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_NUM_CHANNELS = {ELA_PORT_COUNT{NUM_CHANNELS}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_DECIM_ENS = {ELA_PORT_COUNT{DECIM_EN}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_EXT_TRIG_ENS = {ELA_PORT_COUNT{EXT_TRIG_EN}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_TIMESTAMP_WS = {ELA_PORT_COUNT{TIMESTAMP_W}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_NUM_SEGMENTS = {ELA_PORT_COUNT{NUM_SEGMENTS}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_PROBE_MUX_WS = {ELA_PORT_COUNT{PROBE_MUX_W}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_STARTUP_ARMS = {ELA_PORT_COUNT{STARTUP_ARM}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_DEFAULT_TRIG_EXTS = {ELA_PORT_COUNT{DEFAULT_TRIG_EXT}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_REL_COMPARES = {ELA_PORT_COUNT{REL_COMPARE}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_DUAL_COMPARES = {ELA_PORT_COUNT{DUAL_COMPARE}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_USER1_DATA_ENS = {ELA_PORT_COUNT{USER1_DATA_EN}},
    parameter [((NUM_EIOS > 0) ? NUM_EIOS : 1)*32-1:0] EIO_IN_WS =
        {((NUM_EIOS > 0) ? NUM_EIOS : 1){EIO_IN_W}},
    parameter [((NUM_EIOS > 0) ? NUM_EIOS : 1)*32-1:0] EIO_OUT_WS =
        {((NUM_EIOS > 0) ? NUM_EIOS : 1){EIO_OUT_W}}
) (
    // TAP signals (from the vendor's jtag_tap_<vendor>)
    input  wire tck,
    input  wire tdi,
    output wire tdo,
    input  wire capture,
    input  wire shift,
    input  wire update,
    input  wire sel,

    input  wire [ELA_PORT_COUNT-1:0] ela_sample_clk,
    input  wire [ELA_PORT_COUNT-1:0] ela_sample_rst,
    input  wire [ELA_PORT_COUNT*(PROBE_MUX_W > 0 ? PROBE_MUX_W : SAMPLE_W*NUM_CHANNELS)-1:0] ela_probe_in,
    input  wire [ELA_PORT_COUNT-1:0] ela_trigger_in,
    output wire [ELA_PORT_COUNT-1:0] ela_trigger_out,
    output wire [ELA_PORT_COUNT-1:0] ela_armed_out,
    input  wire [((NUM_EIOS > 0) ? NUM_EIOS : 1)*EIO_IN_W-1:0] eio_probe_in,
    output wire [((NUM_EIOS > 0) ? NUM_EIOS : 1)*EIO_OUT_W-1:0] eio_probe_out
);

    localparam PTR_W = $clog2(DEPTH);
    localparam TS_W_SAFE = (TIMESTAMP_W > 0) ? TIMESTAMP_W : 1;
    localparam BURST_SEG_DEPTH = DEPTH / NUM_SEGMENTS;
    wire debug_arst = |ela_sample_rst;

    wire jtag_rst_ctrl;
    wire jtag_clk, jtag_rst;
    wire jtag_wr_en, jtag_rd_en;
    wire [15:0] jtag_addr;
    wire [31:0] jtag_wdata, jtag_rdata;

    wire [PTR_W-1:0] burst_rd_addr;
    wire burst_rd_active;
    wire [SAMPLE_W-1:0] burst_rd_data;
    wire [TS_W_SAFE-1:0] burst_rd_ts_data;
    wire burst_start;
    wire burst_timestamp;
    wire [PTR_W-1:0] burst_start_ptr;

    reset_sync u_rst_sync_ctrl (
        .clk(tck),
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
        .tck(tck), .tdi(tdi), .tdo(tdo),
        .capture(capture), .shift_en(shift),
        .update(update), .sel(sel),
        .reg_clk(jtag_clk), .reg_rst(jtag_rst),
        .reg_wr_en(jtag_wr_en), .reg_rd_en(jtag_rd_en),
        .reg_addr(jtag_addr), .reg_wdata(jtag_wdata),
        .reg_rdata(jtag_rdata),
        .mem_addr(burst_rd_addr),
        .mem_active(burst_rd_active),
        .sample_data(burst_rd_data),
        .timestamp_data(burst_rd_ts_data),
        .burst_start(burst_start),
        .burst_timestamp(burst_timestamp),
        .burst_ptr_in(burst_start_ptr)
    );

    fcapz_debug_multi_core #(
        .NUM_ELAS(NUM_ELAS), .EIO_EN(EIO_EN), .NUM_EIOS(NUM_EIOS),
        .SAMPLE_W(SAMPLE_W), .DEPTH(DEPTH),
        .TRIG_STAGES(TRIG_STAGES), .STOR_QUAL(STOR_QUAL),
        .INPUT_PIPE(INPUT_PIPE), .NUM_CHANNELS(NUM_CHANNELS),
        .DECIM_EN(DECIM_EN), .EXT_TRIG_EN(EXT_TRIG_EN),
        .TIMESTAMP_W(TIMESTAMP_W), .NUM_SEGMENTS(NUM_SEGMENTS),
        .PROBE_MUX_W(PROBE_MUX_W), .STARTUP_ARM(STARTUP_ARM),
        .DEFAULT_TRIG_EXT(DEFAULT_TRIG_EXT), .BURST_EN(1),
        .REL_COMPARE(REL_COMPARE), .DUAL_COMPARE(DUAL_COMPARE),
        .USER1_DATA_EN(USER1_DATA_EN),
        .EIO_IN_W(EIO_IN_W), .EIO_OUT_W(EIO_OUT_W),
        .ELA_PORT_COUNT(ELA_PORT_COUNT),
        .ELA_SAMPLE_WS(ELA_SAMPLE_WS), .ELA_DEPTHS(ELA_DEPTHS),
        .ELA_TRIG_STAGES(ELA_TRIG_STAGES), .ELA_STOR_QUALS(ELA_STOR_QUALS),
        .ELA_INPUT_PIPES(ELA_INPUT_PIPES), .ELA_NUM_CHANNELS(ELA_NUM_CHANNELS),
        .ELA_DECIM_ENS(ELA_DECIM_ENS), .ELA_EXT_TRIG_ENS(ELA_EXT_TRIG_ENS),
        .ELA_TIMESTAMP_WS(ELA_TIMESTAMP_WS), .ELA_NUM_SEGMENTS(ELA_NUM_SEGMENTS),
        .ELA_PROBE_MUX_WS(ELA_PROBE_MUX_WS), .ELA_STARTUP_ARMS(ELA_STARTUP_ARMS),
        .ELA_DEFAULT_TRIG_EXTS(ELA_DEFAULT_TRIG_EXTS),
        .ELA_REL_COMPARES(ELA_REL_COMPARES), .ELA_DUAL_COMPARES(ELA_DUAL_COMPARES),
        .ELA_USER1_DATA_ENS(ELA_USER1_DATA_ENS),
        .EIO_IN_WS(EIO_IN_WS), .EIO_OUT_WS(EIO_OUT_WS)
    ) u_core (
        .ela_sample_clk(ela_sample_clk),
        .ela_sample_rst(ela_sample_rst),
        .ela_probe_in(ela_probe_in),
        .ela_trigger_in(ela_trigger_in),
        .ela_trigger_out(ela_trigger_out),
        .ela_armed_out(ela_armed_out),
        .eio_probe_in(eio_probe_in),
        .eio_probe_out(eio_probe_out),
        .jtag_clk(jtag_clk),
        .jtag_rst(jtag_rst),
        .jtag_wr_en(jtag_wr_en),
        .jtag_rd_en(jtag_rd_en),
        .jtag_addr(jtag_addr),
        .jtag_wdata(jtag_wdata),
        .jtag_rdata(jtag_rdata),
        .burst_rd_addr(burst_rd_addr),
        .burst_rd_active(burst_rd_active),
        .burst_rd_data(burst_rd_data),
        .burst_rd_ts_data(burst_rd_ts_data),
        .burst_start(burst_start),
        .burst_timestamp(burst_timestamp),
        .burst_start_ptr(burst_start_ptr)
    );

endmodule
