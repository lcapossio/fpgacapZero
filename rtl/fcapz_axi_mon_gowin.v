// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero AXI Monitor wrapper for Gowin GW1N / GW2A.
//
// Single-instantiation wrapper: bundles fcapz_axi_mon (AXI4-Lite passive tap +
// embedded ELA), the register interface and the GW_JTAG TAP. See
// docs/19_axi_monitor.md.
//
// Register-only, like fcapz_ela_gowin and fcapz_debug_multi_gowin: there is no
// burst engine, and the host reads captures word by word through the register
// window. A 152-bit AXI4-Lite sample (ADDR_W = DATA_W = 32) is five register
// reads, so readback is much slower than on the burst-capable wrappers; keep
// DEPTH modest.
//
// GW_JTAG is oversampled on clk, which is also the register-bus clock: run it
// at least ~10x TCK. CTRL_CHAIN selects the user chain: 1 = ER1, 2 = ER2.
//
// Gowin allows one GW_JTAG per device, so this wrapper cannot coexist with
// fcapz_ela_gowin, fcapz_eio_gowin or fcapz_debug_multi_gowin: it is the only
// fcapz core on the device.
//
// Usage:
//   fcapz_axi_mon_gowin #(.ADDR_W(32), .DATA_W(32), .DEPTH(256)) u_mon (
//       .clk(clk), .jtag_activity(),
//       .ACLK(aclk), .ARESETN(aresetn),
//       .AWADDR(s_awaddr), .AWPROT(s_awprot), .AWVALID(s_awvalid), .AWREADY(s_awready),
//       .WDATA(s_wdata), .WSTRB(s_wstrb), .WVALID(s_wvalid), .WREADY(s_wready),
//       .BRESP(s_bresp), .BVALID(s_bvalid), .BREADY(s_bready),
//       .ARADDR(s_araddr), .ARPROT(s_arprot), .ARVALID(s_arvalid), .ARREADY(s_arready),
//       .RDATA(s_rdata), .RRESP(s_rresp), .RVALID(s_rvalid), .RREADY(s_rready),
//       .trigger_in(1'b0), .trigger_out(), .armed_out(),
//       .tms_pad_i(tms), .tck_pad_i(tck), .tdi_pad_i(tdi), .tdo_pad_o(tdo)
//   );

module fcapz_axi_mon_gowin #(
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
    parameter CTRL_CHAIN   = 1,    // GW_JTAG user chain: 1 = ER1, 2 = ER2
    // derived (must match fcapz_axi_mon)
    localparam STRB_W      = DATA_W / 8,
    localparam SAMPLE_W    = 2*ADDR_W + 2*DATA_W + STRB_W + 20 + ((DECODE_EN != 0) ? 8 : 0),
    localparam PTR_W       = $clog2(DEPTH),
    localparam TS_W        = (TIMESTAMP_W > 0) ? TIMESTAMP_W : 1
) (
    // Oversampling clock for GW_JTAG; also the register-bus clock.
    input  wire                 clk,
    // High while the GW_JTAG TAP is active (from jtag_tap_gowin).
    output wire                 jtag_activity,

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

    // GW_JTAG pads: wire straight to top-level ports.
    input  wire                 tms_pad_i,
    input  wire                 tck_pad_i,
    input  wire                 tdi_pad_i,
    output wire                 tdo_pad_o
);

    localparam CHAIN_IDX = CTRL_CHAIN - 1;

    initial begin
        if (CTRL_CHAIN < 1 || CTRL_CHAIN > 2) begin
            $error("fcapz_axi_mon_gowin: CTRL_CHAIN %0d must be 1 (ER1) or 2 (ER2)",
                   CTRL_CHAIN);
        end
    end

    // ---- TAP (GW_JTAG, both user chains) ----
    wire tap_tdi;
    wire [1:0] tap_tdo, tap_capture, tap_update, tap_sel;
    wire [1:0] tap_shift_in, tap_shift_out;

    // Register bus
    wire        jtag_clk, jtag_rst;
    wire        jtag_wr_en, jtag_rd_en;
    wire [15:0] jtag_addr;
    wire [31:0] jtag_wdata, jtag_rdata;
    wire        jtag_rst_ctrl;

    // No burst path: the monitor's burst bus is tied off.
    wire [SAMPLE_W-1:0] burst_rd_data_unused;
    wire [TS_W-1:0]     burst_rd_ts_data_unused;
    wire                burst_start_unused;
    wire                burst_timestamp_unused;
    wire [PTR_W-1:0]    burst_start_ptr_unused;

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

    // The TAP's events are oversampled onto clk, so the register interface
    // runs there.
    reset_sync u_rst_sync_ctrl (
        .clk(clk),
        .arst(~ARESETN),
        .srst(jtag_rst_ctrl)
    );

    jtag_reg_iface_gowin u_reg (
        .arst(jtag_rst_ctrl),
        .tck(clk),
        .tdi(tap_tdi),
        .tdo(tap_tdo[CHAIN_IDX]),
        .capture(tap_capture[CHAIN_IDX]),
        .shift_in_en(tap_shift_in[CHAIN_IDX]),
        .shift_out_en(tap_shift_out[CHAIN_IDX]),
        .update(tap_update[CHAIN_IDX]),
        .sel(tap_sel[CHAIN_IDX]),
        .reg_clk(jtag_clk),
        .reg_rst(jtag_rst),
        .reg_wr_en(jtag_wr_en),
        .reg_rd_en(jtag_rd_en),
        .reg_addr(jtag_addr),
        .reg_wdata(jtag_wdata),
        .reg_rdata(jtag_rdata)
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
        .burst_rd_active(1'b0),
        .burst_rd_addr({PTR_W{1'b0}}), .burst_rd_data(burst_rd_data_unused),
        .burst_rd_ts_data(burst_rd_ts_data_unused),
        .burst_start(burst_start_unused), .burst_timestamp(burst_timestamp_unused),
        .burst_start_ptr(burst_start_ptr_unused)
    );

endmodule
