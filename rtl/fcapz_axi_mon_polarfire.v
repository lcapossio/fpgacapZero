// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero AXI Monitor wrapper for Microchip PolarFire and PolarFire SoC.
//
// Single-instantiation wrapper: bundles fcapz_axi_mon (AXI4-Lite passive tap +
// embedded ELA), the single-chain register/burst pipe interface, and the UJTAG
// TAP. Identical to fcapz_axi_mon_xilinx7 except the vendor TAP
// (jtag_tap_polarfire, selected by the UJTAG user instruction IR_USER1); the
// core, register pipe and burst path are shared. See docs/19_axi_monitor.md.
//
// IR_USER2 is unused (the monitor needs one chain) but kept so the parameters
// match fcapz_ela_polarfire and fcapz_debug_multi_polarfire.
//
// UJTAG's JTAG pins must reach top-level ports: connect tck_pad_i, tms_pad_i,
// tdi_pad_i, trstb_pad_i and tdo_pad_o straight to ports of the same direction
// on your top level. Libero binds them to the dedicated JTAG pins; they need no
// PDC constraint.
//
// Libero ignores register initial values on PolarFire: hold ARESETN low until
// the fabric is up (for example from FABRIC_POR_N) so the monitor and its JTAG
// pipe start from reset.
//
// PolarFire allows one UJTAG per device, so this wrapper cannot coexist with
// fcapz_ela_polarfire, fcapz_eio_polarfire or fcapz_debug_multi_polarfire: it
// is the only fcapz core on the device.
//
// Usage:
//   fcapz_axi_mon_polarfire #(.ADDR_W(32), .DATA_W(32), .DEPTH(1024)) u_mon (
//       .ACLK(aclk), .ARESETN(aresetn),
//       .AWADDR(s_awaddr), .AWPROT(s_awprot), .AWVALID(s_awvalid), .AWREADY(s_awready),
//       .WDATA(s_wdata), .WSTRB(s_wstrb), .WVALID(s_wvalid), .WREADY(s_wready),
//       .BRESP(s_bresp), .BVALID(s_bvalid), .BREADY(s_bready),
//       .ARADDR(s_araddr), .ARPROT(s_arprot), .ARVALID(s_arvalid), .ARREADY(s_arready),
//       .RDATA(s_rdata), .RRESP(s_rresp), .RVALID(s_rvalid), .RREADY(s_rready),
//       .trigger_in(1'b0), .trigger_out(), .armed_out(),
//       .tck_pad_i(TCK), .tms_pad_i(TMS), .tdi_pad_i(TDI),
//       .trstb_pad_i(TRSTB), .tdo_pad_o(TDO)
//   );

module fcapz_axi_mon_polarfire #(
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
    parameter WIDE_TRIG    = 1,    // full-width comparator A (trigger on any field)
    parameter DECODE_EN    = 0,    // P2 transaction-events word at the LSB
    parameter BURST_W      = 256,
    // UJTAG user IR opcodes (16..127 are free; 0x10/0x11 belong to the
    // PolarFire SoC MSS debug module, see jtag_tap_polarfire.v).
    parameter [7:0] IR_USER1 = 8'h20,
    parameter [7:0] IR_USER2 = 8'h21,
    // derived (must match fcapz_axi_mon)
    localparam STRB_W      = DATA_W / 8,
    localparam SAMPLE_W    = 2*ADDR_W + 2*DATA_W + STRB_W + 20 + ((DECODE_EN != 0) ? 8 : 0),
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
    output wire                 armed_out,
    // UJTAG JTAG pins: wire straight to top-level ports.
    input  wire                 tck_pad_i,
    input  wire                 tms_pad_i,
    input  wire                 tdi_pad_i,
    input  wire                 trstb_pad_i,
    output wire                 tdo_pad_o
);

    // ---- TAP (UJTAG, user instruction IR_USER1) ----
    wire tap_tck, tap_tdi, tap_tdo;
    wire tap_capture, tap_shift, tap_update, tap_sel;
    wire ch2_tck_unused, ch2_tdi_unused, ch2_capture_unused;
    wire ch2_shift_unused, ch2_update_unused, ch2_sel_unused;

    // Register / burst bus
    wire        jtag_clk, jtag_rst;
    wire        jtag_wr_en, jtag_rd_en;
    wire [15:0] jtag_addr;
    wire [31:0] jtag_wdata, jtag_rdata;

    wire [PTR_W-1:0]    burst_rd_addr;
    wire                burst_rd_active;
    wire [SAMPLE_W-1:0] burst_rd_data;
    wire [TS_W-1:0]     burst_rd_ts_data;
    wire                burst_start;
    wire                burst_timestamp;
    wire [PTR_W-1:0]    burst_start_ptr;
    wire                jtag_rst_ctrl;

    jtag_tap_polarfire #(
        .IR_USER1(IR_USER1), .IR_USER2(IR_USER2)
    ) u_tap_ctrl (
        .tck_pad_i(tck_pad_i), .tms_pad_i(tms_pad_i), .tdi_pad_i(tdi_pad_i),
        .trstb_pad_i(trstb_pad_i), .tdo_pad_o(tdo_pad_o),
        .ch1_tck(tap_tck), .ch1_tdi(tap_tdi), .ch1_tdo(tap_tdo),
        .ch1_capture(tap_capture), .ch1_shift(tap_shift),
        .ch1_update(tap_update), .ch1_sel(tap_sel),
        .ch2_tck(ch2_tck_unused), .ch2_tdi(ch2_tdi_unused), .ch2_tdo(1'b0),
        .ch2_capture(ch2_capture_unused), .ch2_shift(ch2_shift_unused),
        .ch2_update(ch2_update_unused), .ch2_sel(ch2_sel_unused)
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
        .tck(tap_tck), .tdi(tap_tdi), .tdo(tap_tdo), .tdo_next(),
        .capture(tap_capture), .shift_en(tap_shift),
        .update(tap_update), .sel(tap_sel),
        .reg_clk(jtag_clk), .reg_rst(jtag_rst),
        .reg_wr_en(jtag_wr_en), .reg_rd_en(jtag_rd_en),
        .reg_addr(jtag_addr), .reg_wdata(jtag_wdata),
        .reg_rdata(jtag_rdata),
        .mem_addr(burst_rd_addr),
        .mem_active(burst_rd_active),
        .sample_data(burst_rd_data), .timestamp_data(burst_rd_ts_data),
        .burst_start(burst_start), .burst_timestamp(burst_timestamp),
        .burst_ptr_in(burst_start_ptr),
        .burst_header({BURST_W{1'b0}})
    );

    fcapz_axi_mon #(
        .PROTO(PROTO), .ADDR_W(ADDR_W), .DATA_W(DATA_W),
        .DEPTH(DEPTH), .TRIG_STAGES(TRIG_STAGES), .STOR_QUAL(STOR_QUAL),
        .NUM_SEGMENTS(NUM_SEGMENTS), .TIMESTAMP_W(TIMESTAMP_W),
        .INPUT_PIPE(INPUT_PIPE), .DECIM_EN(DECIM_EN), .EXT_TRIG_EN(EXT_TRIG_EN),
        .STARTUP_ARM(STARTUP_ARM), .REL_COMPARE(REL_COMPARE),
        .DUAL_COMPARE(DUAL_COMPARE), .USER1_DATA_EN(USER1_DATA_EN),
        .WIDE_TRIG(WIDE_TRIG), .DECODE_EN(DECODE_EN)
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
        .burst_rd_active(burst_rd_active),
        .burst_rd_addr(burst_rd_addr), .burst_rd_data(burst_rd_data),
        .burst_rd_ts_data(burst_rd_ts_data),
        .burst_start(burst_start), .burst_timestamp(burst_timestamp),
        .burst_start_ptr(burst_start_ptr)
    );

endmodule
