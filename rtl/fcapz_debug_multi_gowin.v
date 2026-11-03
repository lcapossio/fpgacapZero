// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - www.bard0.com - <hello@bard0.com>

`timescale 1ns/1ps

// Mixed debug wrapper: multiple ELAs plus optional EIOs behind one USER chain.
// Slot order is ELA[0..NUM_ELAS-1], then EIO[0..NUM_EIOS-1].
//
// Gowin: GW_JTAG user chain CTRL_CHAIN (1 = ER1, 2 = ER2).  GW_JTAG is
// oversampled on clk (jtag_tap_gowin), so clk must run well above TCK, as for
// fcapz_ela_gowin, and the JTAG pads must reach top-level ports.
//
// Register access only: the Gowin register adapter (jtag_reg_iface_gowin) has
// no burst path, so every slot reports no burst and the host reads captures
// through the register window (keep USER1_DATA_EN=1; the core rejects a slot
// that could not be read).  GW_JTAG's Test-Logic-Reset is not used, so
// TLR_RESET_EN is not offered.  Only one GW_JTAG is allowed per design, so
// this hub cannot coexist with fcapz_ela_gowin or fcapz_eio_gowin.

module fcapz_debug_multi_gowin #(
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
    parameter CTRL_CHAIN = 1,  // 1 = ER1, 2 = ER2
    parameter REL_COMPARE = 0,
    parameter DUAL_COMPARE = 1,
    parameter USER1_DATA_EN = 1,
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
    // Oversampling clock for GW_JTAG; also the register-bus clock.
    input  wire clk,
    // High while the GW_JTAG TAP is active (from jtag_tap_gowin).
    output wire jtag_activity,

    input  wire [ELA_PORT_COUNT-1:0] ela_sample_clk,
    input  wire [ELA_PORT_COUNT-1:0] ela_sample_rst,
    input  wire [ELA_PORT_COUNT*(PROBE_MUX_W > 0 ? PROBE_MUX_W : SAMPLE_W*NUM_CHANNELS)-1:0] ela_probe_in,
    input  wire [ELA_PORT_COUNT-1:0] ela_trigger_in,
    output wire [ELA_PORT_COUNT-1:0] ela_trigger_out,
    output wire [ELA_PORT_COUNT-1:0] ela_armed_out,
    input  wire [((NUM_EIOS > 0) ? NUM_EIOS : 1)*EIO_IN_W-1:0] eio_probe_in,
    output wire [((NUM_EIOS > 0) ? NUM_EIOS : 1)*EIO_OUT_W-1:0] eio_probe_out,

    // GW_JTAG pads: wire straight to top-level ports.
    input  wire tms_pad_i,
    input  wire tck_pad_i,
    input  wire tdi_pad_i,
    output wire tdo_pad_o
);

    localparam PTR_W = $clog2(DEPTH);
    localparam TS_W_SAFE = (TIMESTAMP_W > 0) ? TIMESTAMP_W : 1;
    localparam CHAIN_IDX = CTRL_CHAIN - 1;

    initial begin
        if (CTRL_CHAIN < 1 || CTRL_CHAIN > 2) begin
            $error("fcapz_debug_multi_gowin: CTRL_CHAIN %0d must be 1 (ER1) or 2 (ER2)",
                   CTRL_CHAIN);
        end
    end

    wire tap_tdi;
    wire [1:0] tap_tdo, tap_capture, tap_update, tap_sel;
    wire [1:0] tap_shift_in, tap_shift_out;

    wire por_rst, proto_rst, tlr_sync;
    wire jtag_clk, reg_rst_unused;
    wire jtag_wr_en, jtag_rd_en;
    wire [15:0] jtag_addr;
    wire [31:0] jtag_wdata, jtag_rdata;

    // No burst path: the core's burst bus is tied off.
    wire [SAMPLE_W-1:0] burst_rd_data_unused;
    wire [TS_W_SAFE-1:0] burst_rd_ts_data_unused;
    wire burst_start_unused;
    wire burst_timestamp_unused;
    wire [PTR_W-1:0] burst_start_ptr_unused;
    wire [159:0] burst_header_unused;

    // The other user chain has no register interface; drive its TDO low.
    assign tap_tdo[1 - CHAIN_IDX] = 1'b0;

    jtag_tap_gowin u_tap_ctrl (
        .sysclk(clk),
        .activity(jtag_activity),
        .tdi(tap_tdi), .tdo(tap_tdo),
        .capture(tap_capture),
        .shift_in(tap_shift_in), .shift_out(tap_shift_out),
        .update(tap_update), .sel(tap_sel),
        .tms_pad_i(tms_pad_i), .tck_pad_i(tck_pad_i),
        .tdi_pad_i(tdi_pad_i), .tdo_pad_o(tdo_pad_o)
    );

    // The TAP's events are oversampled onto clk, so the hub resets run there.
    fcapz_hub_reset #(
        .TLR_RESET_EN(0)
    ) u_hub_reset (
        .tck(clk),
        .any_sample_rst(|ela_sample_rst),
        .hub_por(1'b0),
        .tlr(1'b0),
        .por_rst(por_rst),
        .proto_rst(proto_rst),
        .tlr_sync(tlr_sync)
    );

    jtag_reg_iface_gowin u_reg (
        .arst(proto_rst),
        .tck(clk),
        .tdi(tap_tdi),
        .tdo(tap_tdo[CHAIN_IDX]),
        .capture(tap_capture[CHAIN_IDX]),
        .shift_in_en(tap_shift_in[CHAIN_IDX]),
        .shift_out_en(tap_shift_out[CHAIN_IDX]),
        .update(tap_update[CHAIN_IDX]),
        .sel(tap_sel[CHAIN_IDX]),
        .reg_clk(jtag_clk),
        .reg_rst(reg_rst_unused),
        .reg_wr_en(jtag_wr_en),
        .reg_rd_en(jtag_rd_en),
        .reg_addr(jtag_addr),
        .reg_wdata(jtag_wdata),
        .reg_rdata(jtag_rdata)
    );

    fcapz_debug_multi_core #(
        .NUM_ELAS(NUM_ELAS), .EIO_EN(EIO_EN), .NUM_EIOS(NUM_EIOS),
        .SAMPLE_W(SAMPLE_W), .DEPTH(DEPTH),
        .TRIG_STAGES(TRIG_STAGES), .STOR_QUAL(STOR_QUAL),
        .INPUT_PIPE(INPUT_PIPE), .NUM_CHANNELS(NUM_CHANNELS),
        .DECIM_EN(DECIM_EN), .EXT_TRIG_EN(EXT_TRIG_EN),
        .TIMESTAMP_W(TIMESTAMP_W), .NUM_SEGMENTS(NUM_SEGMENTS),
        .PROBE_MUX_W(PROBE_MUX_W), .STARTUP_ARM(STARTUP_ARM),
        .DEFAULT_TRIG_EXT(DEFAULT_TRIG_EXT), .BURST_EN(0),
        .REL_COMPARE(REL_COMPARE), .DUAL_COMPARE(DUAL_COMPARE),
        .USER1_DATA_EN(USER1_DATA_EN),
        .HEADER_EN(0), .TLR_RESET_EN(0),
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
        .jtag_rst(por_rst),
        .proto_rst(proto_rst),
        .tlr(tlr_sync),
        .jtag_wr_en(jtag_wr_en),
        .jtag_rd_en(jtag_rd_en),
        .jtag_addr(jtag_addr),
        .jtag_wdata(jtag_wdata),
        .jtag_rdata(jtag_rdata),
        .burst_rd_addr({PTR_W{1'b0}}),
        .burst_rd_active(1'b0),
        .burst_rd_data(burst_rd_data_unused),
        .burst_rd_ts_data(burst_rd_ts_data_unused),
        .burst_start(burst_start_unused),
        .burst_timestamp(burst_timestamp_unused),
        .burst_start_ptr(burst_start_ptr_unused),
        .burst_header(burst_header_unused)
    );

endmodule
