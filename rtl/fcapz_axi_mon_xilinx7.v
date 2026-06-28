// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero AXI Monitor wrapper for Xilinx 7-series / UltraScale.
//
// Single-instantiation wrapper: bundles fcapz_axi_mon (AXI4-Lite passive tap +
// embedded ELA), the single-chain register/burst pipe interface, and the
// BSCANE2 TAP primitive. Drop it onto an AXI4-Lite interface to capture and
// trigger on bus traffic over JTAG -- a portable, vendor-agnostic AXI bus
// monitor. See docs/specs/axi_monitor.md.
//
// Usage:
//   fcapz_axi_mon_xilinx7 #(.ADDR_W(32), .DATA_W(32), .DEPTH(1024)) u_mon (
//       .ACLK(aclk), .ARESETN(aresetn),
//       .AWADDR(s_awaddr), .AWPROT(s_awprot), .AWVALID(s_awvalid), .AWREADY(s_awready),
//       .WDATA(s_wdata), .WSTRB(s_wstrb), .WVALID(s_wvalid), .WREADY(s_wready),
//       .BRESP(s_bresp), .BVALID(s_bvalid), .BREADY(s_bready),
//       .ARADDR(s_araddr), .ARPROT(s_arprot), .ARVALID(s_arvalid), .ARREADY(s_arready),
//       .RDATA(s_rdata), .RRESP(s_rresp), .RVALID(s_rvalid), .RREADY(s_rready)
//   );

module fcapz_axi_mon_xilinx7 #(
    parameter PROTO        = "AXI4LITE",
    parameter ADDR_W       = 32,
    parameter DATA_W       = 32,
    parameter DEPTH        = 1024,
    parameter TRIG_STAGES  = 4,
    parameter STOR_QUAL    = 1,
    parameter NUM_SEGMENTS = 1,
    parameter TIMESTAMP_W  = 32,
    parameter INPUT_PIPE   = 1,
    parameter DECIM_EN     = 0,
    parameter EXT_TRIG_EN  = 0,
    parameter STARTUP_ARM  = 0,
    parameter REL_COMPARE  = 1,
    parameter DUAL_COMPARE = 1,
    parameter USER1_DATA_EN = 1,
    parameter BURST_W      = 256,
    parameter CTRL_CHAIN   = 1,    // BSCANE2 USER chain for control + burst
    // derived (must match fcapz_axi_mon)
    localparam STRB_W      = DATA_W / 8,
    localparam SAMPLE_W    = 2*ADDR_W + 2*DATA_W + STRB_W + 20,
    localparam PTR_W       = $clog2(DEPTH),
    localparam TS_W        = (TIMESTAMP_W > 0) ? TIMESTAMP_W : 1,
    localparam BURST_SEG_DEPTH = DEPTH / NUM_SEGMENTS
) (
    // ---- Passive AXI4-Lite monitor tap (inputs only) ----
    input  wire                 ACLK,
    input  wire                 ARESETN,
    input  wire [ADDR_W-1:0]    AWADDR,
    input  wire [2:0]           AWPROT,
    input  wire                 AWVALID,
    input  wire                 AWREADY,
    input  wire [DATA_W-1:0]    WDATA,
    input  wire [STRB_W-1:0]    WSTRB,
    input  wire                 WVALID,
    input  wire                 WREADY,
    input  wire [1:0]           BRESP,
    input  wire                 BVALID,
    input  wire                 BREADY,
    input  wire [ADDR_W-1:0]    ARADDR,
    input  wire [2:0]           ARPROT,
    input  wire                 ARVALID,
    input  wire                 ARREADY,
    input  wire [DATA_W-1:0]    RDATA,
    input  wire [1:0]           RRESP,
    input  wire                 RVALID,
    input  wire                 RREADY,
    // External trigger I/O
    input  wire                 trigger_in,
    output wire                 trigger_out,
    output wire                 armed_out
);

    // ---- TAP (USER chain) ----
    wire tap_tck, tap_tdi, tap_tdo;
    wire tap_capture, tap_shift, tap_update, tap_sel;

    // Register / burst bus
    wire        jtag_clk, jtag_rst;
    wire        jtag_wr_en, jtag_rd_en;
    wire [15:0] jtag_addr;
    wire [31:0] jtag_wdata, jtag_rdata;

    wire [PTR_W-1:0]    burst_rd_addr;
    wire [SAMPLE_W-1:0] burst_rd_data;
    wire [TS_W-1:0]     burst_rd_ts_data;
    wire                burst_start;
    wire                burst_timestamp;
    wire [PTR_W-1:0]    burst_start_ptr;
    wire                jtag_rst_ctrl;

    jtag_tap_xilinx7 #(.CHAIN(CTRL_CHAIN)) u_tap_ctrl (
        .tck(tap_tck), .tdi(tap_tdi), .tdo(tap_tdo),
        .capture(tap_capture), .shift(tap_shift),
        .update(tap_update), .sel(tap_sel)
    );

    reset_sync u_rst_sync_ctrl (
        .clk(tap_tck),
        .arst(~ARESETN),
        .srst(jtag_rst_ctrl)
    );

    jtag_pipe_iface #(
        .SAMPLE_W(SAMPLE_W), .TIMESTAMP_W(TIMESTAMP_W),
        .DEPTH(DEPTH), .BURST_W(BURST_W), .SEG_DEPTH(BURST_SEG_DEPTH),
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
        .sample_data(burst_rd_data), .timestamp_data(burst_rd_ts_data),
        .burst_start(burst_start), .burst_timestamp(burst_timestamp),
        .burst_ptr_in(burst_start_ptr)
    );

    fcapz_axi_mon #(
        .PROTO(PROTO), .ADDR_W(ADDR_W), .DATA_W(DATA_W),
        .DEPTH(DEPTH), .TRIG_STAGES(TRIG_STAGES), .STOR_QUAL(STOR_QUAL),
        .NUM_SEGMENTS(NUM_SEGMENTS), .TIMESTAMP_W(TIMESTAMP_W),
        .INPUT_PIPE(INPUT_PIPE), .DECIM_EN(DECIM_EN), .EXT_TRIG_EN(EXT_TRIG_EN),
        .STARTUP_ARM(STARTUP_ARM), .REL_COMPARE(REL_COMPARE),
        .DUAL_COMPARE(DUAL_COMPARE), .USER1_DATA_EN(USER1_DATA_EN)
    ) u_mon (
        .ACLK(ACLK), .ARESETN(ARESETN),
        .AWADDR(AWADDR), .AWPROT(AWPROT), .AWVALID(AWVALID), .AWREADY(AWREADY),
        .WDATA(WDATA), .WSTRB(WSTRB), .WVALID(WVALID), .WREADY(WREADY),
        .BRESP(BRESP), .BVALID(BVALID), .BREADY(BREADY),
        .ARADDR(ARADDR), .ARPROT(ARPROT), .ARVALID(ARVALID), .ARREADY(ARREADY),
        .RDATA(RDATA), .RRESP(RRESP), .RVALID(RVALID), .RREADY(RREADY),
        .trigger_in(trigger_in), .trigger_out(trigger_out), .armed_out(armed_out),
        .jtag_clk(jtag_clk), .jtag_rst(jtag_rst),
        .jtag_wr_en(jtag_wr_en), .jtag_rd_en(jtag_rd_en),
        .jtag_addr(jtag_addr), .jtag_wdata(jtag_wdata), .jtag_rdata(jtag_rdata),
        .burst_rd_addr(burst_rd_addr), .burst_rd_data(burst_rd_data),
        .burst_rd_ts_data(burst_rd_ts_data),
        .burst_start(burst_start), .burst_timestamp(burst_timestamp),
        .burst_start_ptr(burst_start_ptr)
    );

endmodule
