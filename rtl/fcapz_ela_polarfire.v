// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero ELA wrapper for Microchip PolarFire and PolarFire SoC
// (SmartFusion2 / IGLOO2 share the same UJTAG port list).
//
// Single-instantiation wrapper: bundles the ELA core, register interface,
// burst read engine and the UJTAG TAP.  It has the same parameters and
// ports as fcapz_ela_xilinx7, except that IR_USER1 / IR_USER2 select the
// UJTAG user instructions instead of CTRL_CHAIN / DATA_CHAIN.
//
//   SINGLE_CHAIN_BURST=1 (default): register access and burst readout both
//     on USER1 (jtag_pipe_iface); USER2 is unused.
//   SINGLE_CHAIN_BURST=0, BURST_EN=1: registers on USER1, 256-bit burst
//     readout on USER2 (jtag_burst_read).
//   SINGLE_CHAIN_BURST=0, BURST_EN=0: registers on USER1 only.
//
// UJTAG's JTAG pins must reach top-level ports: connect tck_pad_i,
// tms_pad_i, tdi_pad_i, trstb_pad_i and tdo_pad_o straight to ports of
// the same direction on your top level.  Libero binds them to the
// dedicated JTAG pins; they need no PDC constraint.
//
// Only ONE UJTAG instance is allowed per device, so this wrapper
// CANNOT coexist with fcapz_eio_polarfire (standalone) — to use ELA
// and EIO together, set EIO_EN=1 on this wrapper to mux EIO onto
// USER1 alongside the ELA control bus (EIO registers appear at
// offset 0x8000 from the host's perspective).
//
// Usage:
//   // ELA only
//   fcapz_ela_polarfire #(.SAMPLE_W(8), .DEPTH(1024)) u_ela (
//       .sample_clk(clk), .sample_rst(rst), .probe_in(signals),
//       .trigger_in(1'b0), .trigger_out(), .armed_out(),
//       .eio_probe_in(1'b0), .eio_probe_out(),
//       .tck_pad_i(TCK), .tms_pad_i(TMS), .tdi_pad_i(TDI),
//       .trstb_pad_i(TRSTB), .tdo_pad_o(TDO)
//   );
//
//   // ELA + EIO combined
//   fcapz_ela_polarfire #(.SAMPLE_W(8), .DEPTH(1024),
//       .EIO_EN(1), .EIO_IN_W(32), .EIO_OUT_W(32)
//   ) u_ela (
//       .sample_clk(clk), .sample_rst(rst), .probe_in(signals),
//       .trigger_in(1'b0), .trigger_out(), .armed_out(),
//       .eio_probe_in(observe), .eio_probe_out(drive),
//       .tck_pad_i(TCK), .tms_pad_i(TMS), .tdi_pad_i(TDI),
//       .trstb_pad_i(TRSTB), .tdo_pad_o(TDO)
//   );

module fcapz_ela_polarfire #(
    parameter SAMPLE_W     = 8,
    parameter DEPTH        = 1024,
    parameter TRIG_STAGES  = 1,
    parameter STOR_QUAL    = 0,
    parameter INPUT_PIPE   = 0,
    parameter NUM_CHANNELS = 1,
    parameter DECIM_EN     = 0,
    parameter EXT_TRIG_EN  = 0,
    parameter TIMESTAMP_W  = 0,
    parameter NUM_SEGMENTS = 1,
    parameter PROBE_MUX_W  = 0,
    parameter STARTUP_ARM  = 0,
    parameter DEFAULT_TRIG_EXT = 0,
    parameter BURST_W      = 256,
    parameter BURST_EN     = 1,   // 0=omit the USER2 burst path
    parameter SINGLE_CHAIN_BURST = 1, // 1=burst readout on USER1
    // UJTAG user IR opcodes (16..127 are free; 0x10/0x11 belong to the
    // PolarFire SoC MSS debug module, see jtag_tap_polarfire.v).
    parameter [7:0] IR_USER1 = 8'h20,
    parameter [7:0] IR_USER2 = 8'h21,
    // Optional EIO (shares USER1 via address mux; host talks to EIO at 0x8000+)
    parameter EIO_EN       = 0,
    parameter EIO_IN_W     = 1,
    parameter EIO_OUT_W    = 1,
    parameter REL_COMPARE  = 0,
    parameter DUAL_COMPARE = 1,
    parameter USER1_DATA_EN = 1
) (
    input  wire                              sample_clk,
    input  wire                              sample_rst,
    input  wire [(PROBE_MUX_W > 0 ? PROBE_MUX_W : SAMPLE_W*NUM_CHANNELS)-1:0] probe_in,
    input  wire                              trigger_in,
    output wire                              trigger_out,
    output wire                              armed_out,
    // EIO ports (active when EIO_EN=1)
    input  wire [EIO_IN_W-1:0]               eio_probe_in,
    output wire [EIO_OUT_W-1:0]              eio_probe_out,
    // JTAG pads (connect straight to top-level ports)
    input  wire                              tck_pad_i,
    input  wire                              tms_pad_i,
    input  wire                              tdi_pad_i,
    input  wire                              trstb_pad_i,
    output wire                              tdo_pad_o
);

    localparam PTR_W = $clog2(DEPTH);
    // Segment depth for burst read ring-wrap (equals DEPTH when unsegmented).
    localparam BURST_SEG_DEPTH = DEPTH / NUM_SEGMENTS;

    // TAP signals — single UJTAG primitive exposing both chains
    wire tap1_tck, tap1_tdi, tap1_tdo;
    wire tap1_capture, tap1_shift, tap1_update, tap1_sel;
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

    // ---- TAP wrapper (single UJTAG, dual-chain view) ----
    jtag_tap_polarfire #(
        .IR_USER1(IR_USER1),
        .IR_USER2(IR_USER2)
    ) u_tap (
        .tck_pad_i(tck_pad_i), .tms_pad_i(tms_pad_i), .tdi_pad_i(tdi_pad_i),
        .trstb_pad_i(trstb_pad_i), .tdo_pad_o(tdo_pad_o),
        .ch1_tck(tap1_tck), .ch1_tdi(tap1_tdi), .ch1_tdo(tap1_tdo),
        .ch1_capture(tap1_capture), .ch1_shift(tap1_shift),
        .ch1_update(tap1_update), .ch1_sel(tap1_sel),
        .ch2_tck(tap2_tck), .ch2_tdi(tap2_tdi), .ch2_tdo(tap2_tdo),
        .ch2_capture(tap2_capture), .ch2_shift(tap2_shift),
        .ch2_update(tap2_update), .ch2_sel(tap2_sel)
    );

    reset_sync u_rst_sync_ctrl (
        .clk(tap1_tck),
        .arst(sample_rst),
        .srst(jtag_rst_ctrl)
    );

    // ---- Register / single-chain pipe interface (USER1) ----
    generate
        if (SINGLE_CHAIN_BURST != 0) begin : g_pipe_iface
            jtag_pipe_iface #(
                .SAMPLE_W(SAMPLE_W), .TIMESTAMP_W(TIMESTAMP_W),
                .DEPTH(DEPTH), .BURST_W(BURST_W), .SEG_DEPTH(BURST_SEG_DEPTH),
                .BURST_PTR_ADDR(16'h002C)
            ) u_pipe (
                .arst(jtag_rst_ctrl),
                .tck(tap1_tck), .tdi(tap1_tdi), .tdo(tap1_tdo),
                .capture(tap1_capture), .shift_en(tap1_shift),
                .update(tap1_update), .sel(tap1_sel),
                .reg_clk(jtag_clk), .reg_rst(jtag_rst),
                .reg_wr_en(jtag_wr_en), .reg_rd_en(jtag_rd_en),
                .reg_addr(jtag_addr), .reg_wdata(jtag_wdata),
                .reg_rdata(jtag_rdata),
                .mem_addr(burst_rd_addr),
                .mem_active(burst_rd_active),
                .sample_data(burst_rd_data), .timestamp_data(burst_rd_ts_data),
                .burst_start(burst_start), .burst_timestamp(burst_timestamp),
                .burst_ptr_in(burst_start_ptr)
            );
        end else begin : g_reg_iface
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
        end
    endgenerate

    // ---- ELA + optional EIO via address mux ----
    generate
        if (EIO_EN != 0) begin : g_shared
            wire        ela_wr_en, ela_rd_en;
            wire [15:0] ela_addr;
            wire [31:0] ela_wdata, ela_rdata;
            wire        eio_wr_en_i;
            wire        eio_rd_en_unused;
            wire [15:0] eio_addr_i;
            wire [31:0] eio_wdata_i, eio_rdata_i;

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
                .DECIM_EN(DECIM_EN), .EXT_TRIG_EN(EXT_TRIG_EN),
                .TIMESTAMP_W(TIMESTAMP_W), .NUM_SEGMENTS(NUM_SEGMENTS),
                .PROBE_MUX_W(PROBE_MUX_W), .STARTUP_ARM(STARTUP_ARM),
                .DEFAULT_TRIG_EXT(DEFAULT_TRIG_EXT),
                .REL_COMPARE(REL_COMPARE), .DUAL_COMPARE(DUAL_COMPARE),
                .USER1_DATA_EN(USER1_DATA_EN)
            ) u_ela (
                .sample_clk(sample_clk), .sample_rst(sample_rst),
                .probe_in(probe_in),
                .trigger_in(trigger_in), .trigger_out(trigger_out), .armed_out(armed_out),
                .jtag_clk(jtag_clk), .jtag_rst(jtag_rst),
                .jtag_wr_en(ela_wr_en), .jtag_rd_en(ela_rd_en),
                .jtag_addr(ela_addr), .jtag_wdata(ela_wdata),
                .jtag_rdata(ela_rdata),
                .burst_rd_active(burst_rd_active),
                .burst_rd_addr(burst_rd_addr), .burst_rd_data(burst_rd_data),
                .burst_rd_ts_data(burst_rd_ts_data),
                .burst_start(burst_start), .burst_timestamp(burst_timestamp),
                .burst_start_ptr(burst_start_ptr)
            );

            fcapz_eio #(.IN_W(EIO_IN_W), .OUT_W(EIO_OUT_W)) u_eio (
                .probe_in(eio_probe_in), .probe_out(eio_probe_out),
                .jtag_clk(jtag_clk), .jtag_rst(jtag_rst),
                .jtag_wr_en(eio_wr_en_i),
                .jtag_addr(eio_addr_i), .jtag_wdata(eio_wdata_i),
                .jtag_rdata(eio_rdata_i)
            );
        end else begin : g_ela_only
            fcapz_ela #(
                .SAMPLE_W(SAMPLE_W), .DEPTH(DEPTH),
                .TRIG_STAGES(TRIG_STAGES), .STOR_QUAL(STOR_QUAL),
                .INPUT_PIPE(INPUT_PIPE), .NUM_CHANNELS(NUM_CHANNELS),
                .DECIM_EN(DECIM_EN), .EXT_TRIG_EN(EXT_TRIG_EN),
                .TIMESTAMP_W(TIMESTAMP_W), .NUM_SEGMENTS(NUM_SEGMENTS),
                .PROBE_MUX_W(PROBE_MUX_W), .STARTUP_ARM(STARTUP_ARM),
                .DEFAULT_TRIG_EXT(DEFAULT_TRIG_EXT),
                .REL_COMPARE(REL_COMPARE), .DUAL_COMPARE(DUAL_COMPARE),
                .USER1_DATA_EN(USER1_DATA_EN)
            ) u_ela (
                .sample_clk(sample_clk), .sample_rst(sample_rst),
                .probe_in(probe_in),
                .trigger_in(trigger_in), .trigger_out(trigger_out), .armed_out(armed_out),
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

            assign eio_probe_out = {EIO_OUT_W{1'b0}};
        end
    endgenerate

    // ---- Optional USER2 burst read engine ----
    generate
        if (BURST_EN != 0 && SINGLE_CHAIN_BURST == 0) begin : g_burst
            reset_sync u_rst_sync_data (
                .clk(tap2_tck),
                .arst(sample_rst),
                .srst(jtag_rst_data)
            );

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
        end else begin : g_no_user2
            // USER2 is unused: tie its TDO off so UJTAG shifts zeros there.
            assign tap2_tdo = 1'b0;
            assign jtag_rst_data = 1'b0;
            if (SINGLE_CHAIN_BURST == 0) begin : g_no_burst
                assign burst_rd_addr = {PTR_W{1'b0}};
                assign burst_rd_active = 1'b0;
            end
            // Otherwise the single-chain pipe owns the burst memory read address.
        end
    endgenerate

endmodule
