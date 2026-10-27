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
//
// Resets (fcapz_hub_reset): the slots' sample resets reset the hub only until
// the first release; after that each slot resets alone.  The pipe also resets
// on the TAP's Test-Logic-Reset when TLR_RESET_EN (tie tlr to 0 if the TAP
// has no such output).  hub_por, a power-on reset for flows that drop
// register initial values, resets the hub and every slot while high (tie it
// to 0 elsewhere).  Each burst's first scan carries a header naming the
// slot, pointer and epochs it belongs to.

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
    // 1: the TAP's Test-Logic-Reset also resets the burst protocol.
    parameter TLR_RESET_EN = 0,
    parameter EIO_IN_W = 1,
    parameter EIO_OUT_W = 1,
    parameter ELA_PORT_COUNT = (NUM_ELAS > 0) ? NUM_ELAS : 1,
    // Per-slot overrides. The scalar parameters above remain the max/default
    // shape so existing instantiations can keep using one shared setting.
    parameter [ELA_PORT_COUNT*32-1:0] ELA_SAMPLE_WS = {ELA_PORT_COUNT{(SAMPLE_W + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_DEPTHS = {ELA_PORT_COUNT{(DEPTH + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_TRIG_STAGES = {ELA_PORT_COUNT{(TRIG_STAGES + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_STOR_QUALS = {ELA_PORT_COUNT{(STOR_QUAL + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_INPUT_PIPES = {ELA_PORT_COUNT{(INPUT_PIPE + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_NUM_CHANNELS = {ELA_PORT_COUNT{(NUM_CHANNELS + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_DECIM_ENS = {ELA_PORT_COUNT{(DECIM_EN + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_EXT_TRIG_ENS = {ELA_PORT_COUNT{(EXT_TRIG_EN + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_TIMESTAMP_WS = {ELA_PORT_COUNT{(TIMESTAMP_W + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_NUM_SEGMENTS = {ELA_PORT_COUNT{(NUM_SEGMENTS + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_PROBE_MUX_WS = {ELA_PORT_COUNT{(PROBE_MUX_W + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_STARTUP_ARMS = {ELA_PORT_COUNT{(STARTUP_ARM + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_DEFAULT_TRIG_EXTS = {ELA_PORT_COUNT{(DEFAULT_TRIG_EXT + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_REL_COMPARES = {ELA_PORT_COUNT{(REL_COMPARE + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_DUAL_COMPARES = {ELA_PORT_COUNT{(DUAL_COMPARE + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_USER1_DATA_ENS = {ELA_PORT_COUNT{(USER1_DATA_EN + 32'd0)}},
    parameter [((NUM_EIOS > 0) ? NUM_EIOS : 1)*32-1:0] EIO_IN_WS =
        {((NUM_EIOS > 0) ? NUM_EIOS : 1){(EIO_IN_W + 32'd0)}},
    parameter [((NUM_EIOS > 0) ? NUM_EIOS : 1)*32-1:0] EIO_OUT_WS =
        {((NUM_EIOS > 0) ? NUM_EIOS : 1){(EIO_OUT_W + 32'd0)}}
) (
    // TAP signals (from the vendor's jtag_tap_<vendor>)
    input  wire tck,
    input  wire tdi,
    output wire tdo,
    input  wire capture,
    input  wire shift,
    input  wire update,
    input  wire sel,
    input  wire tlr,
    // Power-on reset, active high; 0 where initial values are kept
    input  wire hub_por,

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
    localparam HEADER_W = 160;

    wire por_rst, proto_rst, tlr_sync;
    wire [ELA_PORT_COUNT-1:0] sample_rst = ela_sample_rst | {ELA_PORT_COUNT{hub_por}};
    wire jtag_clk, pipe_reg_rst;
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
    wire [HEADER_W-1:0] burst_header;
    // Zero-extended to the scan; BURST_W is 256 (checked below).
    wire [BURST_W-1:0] pipe_header = burst_header;

    // The host shifts 256-bit burst scans (Transport.BURST_DR_BITS).
    initial begin
        if (BURST_W != 256) begin
            $error("fcapz_debug_multi: BURST_W %0d is not 256, the host burst scan width",
                   BURST_W);
        end
    end

    fcapz_hub_reset #(
        .TLR_RESET_EN(TLR_RESET_EN)
    ) u_hub_reset (
        .tck(tck),
        .any_sample_rst(|sample_rst),
        .hub_por(hub_por),
        .tlr(tlr),
        .por_rst(por_rst),
        .proto_rst(proto_rst),
        .tlr_sync(tlr_sync)
    );

    jtag_pipe_iface #(
        .SAMPLE_W(SAMPLE_W),
        .TIMESTAMP_W(TIMESTAMP_W),
        .DEPTH(DEPTH),
        .BURST_W(BURST_W),
        .SEG_DEPTH(BURST_SEG_DEPTH),
        .BURST_PTR_ADDR(16'h002C),
        .HEADER_EN(1)
    ) u_pipe (
        .arst(proto_rst),
        .tck(tck), .tdi(tdi), .tdo(tdo),
        .capture(capture), .shift_en(shift),
        .update(update), .sel(sel),
        .reg_clk(jtag_clk), .reg_rst(pipe_reg_rst),
        .reg_wr_en(jtag_wr_en), .reg_rd_en(jtag_rd_en),
        .reg_addr(jtag_addr), .reg_wdata(jtag_wdata),
        .reg_rdata(jtag_rdata),
        .mem_addr(burst_rd_addr),
        .mem_active(burst_rd_active),
        .sample_data(burst_rd_data),
        .timestamp_data(burst_rd_ts_data),
        .burst_start(burst_start),
        .burst_timestamp(burst_timestamp),
        .burst_ptr_in(burst_start_ptr),
        .burst_header(pipe_header)
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
        .HEADER_EN(1), .TLR_RESET_EN(TLR_RESET_EN),
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
        .ela_sample_rst(sample_rst),
        .ela_probe_in(ela_probe_in),
        .ela_trigger_in(ela_trigger_in),
        .ela_trigger_out(ela_trigger_out),
        .ela_armed_out(ela_armed_out),
        .eio_probe_in(eio_probe_in),
        .eio_probe_out(eio_probe_out),
        .jtag_clk(jtag_clk),
        .jtag_rst(por_rst),
        .proto_rst(proto_rst),
        .tlr(tlr_sync),
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
        .burst_start_ptr(burst_start_ptr),
        .burst_header(burst_header)
    );

endmodule
