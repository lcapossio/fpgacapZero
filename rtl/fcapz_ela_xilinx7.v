// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero ELA wrapper for Xilinx 7-series / UltraScale.
//
// Single-instantiation wrapper: bundles the ELA core, register interface,
// burst read engine, and two BSCANE2 TAP primitives (USER1 + USER2).
//
// Optional EIO: set EIO_EN=1 to include an Embedded I/O core on the
// same CTRL_CHAIN register bus via address mux.  EIO registers appear
// at host offset 0x8000 (the mux strips bit 15 before presenting to
// the EIO core, which sees its own 0x0000-based address space).  Use
// this on chains where the host toolchain only reliably reaches
// USER1 (e.g. Zynq UltraScale+ MPSoC with default xsdb/hw_server
// chain dispatch), or any design with tight BSCAN-primitive budget.
//
// Usage:
//   // ELA only (default)
//   fcapz_ela_xilinx7 #(.SAMPLE_W(8), .DEPTH(1024)) u_ela (
//       .sample_clk(clk), .sample_rst(rst), .probe_in(signals),
//       .trigger_in(1'b0), .trigger_out()
//   );
//
//   // ELA + EIO combined on USER1
//   fcapz_ela_xilinx7 #(
//       .SAMPLE_W(8), .DEPTH(1024),
//       .EIO_EN(1), .EIO_IN_W(32), .EIO_OUT_W(32)
//   ) u_ela (
//       .sample_clk(clk), .sample_rst(rst), .probe_in(signals),
//       .trigger_in(1'b0), .trigger_out(),
//       .eio_probe_in(observe), .eio_probe_out(drive)
//   );

module fcapz_ela_xilinx7 #(
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
    parameter CTRL_CHAIN  = 1,   // BSCANE2 USER chain for control
    parameter DATA_CHAIN  = 2,   // BSCANE2 USER chain for burst data
    // Optional EIO (shares CTRL_CHAIN via address mux; host talks to EIO at 0x8000+)
    parameter EIO_EN      = 0,
    parameter EIO_IN_W    = 1,
    parameter EIO_OUT_W   = 1,
    parameter REL_COMPARE = 0
) (
    input  wire                          sample_clk,
    input  wire                          sample_rst,
    input  wire [(PROBE_MUX_W > 0 ? PROBE_MUX_W : SAMPLE_W*NUM_CHANNELS)-1:0] probe_in,
    // External trigger I/O
    input  wire                          trigger_in,
    output wire                          trigger_out,
    output wire                          armed_out,
    // EIO ports (active when EIO_EN=1; ignored / tied-off otherwise)
    input  wire [EIO_IN_W-1:0]           eio_probe_in,
    output wire [EIO_OUT_W-1:0]          eio_probe_out
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
    wire [SAMPLE_W-1:0] burst_rd_data;
    wire [((TIMESTAMP_W > 0) ? TIMESTAMP_W : 1)-1:0] burst_rd_ts_data;
    wire                burst_start;
    wire                burst_timestamp;
    wire [PTR_W-1:0]    burst_start_ptr;
    wire                jtag_rst_ctrl;
    wire                jtag_rst_data;

    // ---- TAP wrappers ----
    jtag_tap_xilinx7 #(.CHAIN(CTRL_CHAIN)) u_tap_ctrl (
        .tck(tap1_tck), .tdi(tap1_tdi), .tdo(tap1_tdo),
        .capture(tap1_capture), .shift(tap1_shift),
        .update(tap1_update), .sel(tap1_sel)
    );

    jtag_tap_xilinx7 #(.CHAIN(DATA_CHAIN)) u_tap_data (
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

    // ---- ELA + optional EIO via address mux ----
    generate
        if (EIO_EN != 0) begin : g_shared
            wire        ela_wr_en, ela_rd_en;
            wire [15:0] ela_addr;
            wire [31:0] ela_wdata, ela_rdata;
            wire        eio_wr_en_i;
            wire [15:0] eio_addr_i;
            wire [31:0] eio_wdata_i, eio_rdata_i;

            fcapz_regbus_mux u_mux (
                .addr(jtag_addr), .wr_en(jtag_wr_en), .rd_en(jtag_rd_en),
                .wdata(jtag_wdata), .rdata(jtag_rdata),
                .a_wr_en(ela_wr_en), .a_rd_en(ela_rd_en),
                .a_addr(ela_addr), .a_wdata(ela_wdata), .a_rdata(ela_rdata),
                .b_wr_en(eio_wr_en_i), .b_rd_en(),
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
                .REL_COMPARE(REL_COMPARE)
            ) u_ela (
                .sample_clk(sample_clk), .sample_rst(sample_rst),
                .probe_in(probe_in),
                .trigger_in(trigger_in), .trigger_out(trigger_out), .armed_out(armed_out),
                .jtag_clk(jtag_clk), .jtag_rst(jtag_rst),
                .jtag_wr_en(ela_wr_en), .jtag_rd_en(ela_rd_en),
                .jtag_addr(ela_addr), .jtag_wdata(ela_wdata),
                .jtag_rdata(ela_rdata),
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
                .REL_COMPARE(REL_COMPARE)
            ) u_ela (
                .sample_clk(sample_clk), .sample_rst(sample_rst),
                .probe_in(probe_in),
                .trigger_in(trigger_in), .trigger_out(trigger_out), .armed_out(armed_out),
                .jtag_clk(jtag_clk), .jtag_rst(jtag_rst),
                .jtag_wr_en(jtag_wr_en), .jtag_rd_en(jtag_rd_en),
                .jtag_addr(jtag_addr), .jtag_wdata(jtag_wdata),
                .jtag_rdata(jtag_rdata),
                .burst_rd_addr(burst_rd_addr), .burst_rd_data(burst_rd_data),
                .burst_rd_ts_data(burst_rd_ts_data),
                .burst_start(burst_start), .burst_timestamp(burst_timestamp),
                .burst_start_ptr(burst_start_ptr)
            );

            assign eio_probe_out = {EIO_OUT_W{1'b0}};
        end
    endgenerate

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
        .sample_data(burst_rd_data), .timestamp_data(burst_rd_ts_data),
        .burst_start(burst_start), .burst_timestamp(burst_timestamp),
        .burst_ptr_in(burst_start_ptr)
    );

endmodule
