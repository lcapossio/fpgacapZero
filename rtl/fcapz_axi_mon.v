// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

`include "fcapz_version.vh"

// fpgacapZero AXI Monitor -- portable, vendor-agnostic passive AXI bus monitor.
//
// Passively taps an AXI4-Lite interface (it NEVER drives any *VALID/*READY --
// every AXI port here is an input wired in parallel with the real bus),
// flattens the five channels into one capture vector, and feeds that to an
// embedded fcapz_ela capture/trigger engine.  Everything downstream (registers,
// burst readback, host Analyzer, viewer) is the ELA's, reused unchanged.
//
// This is P1 of docs/specs/axi_monitor.md: AXI4-Lite, full channel set.  The
// derived transaction-event decoder (handshake/addr-range/response triggers),
// the protocol checker, and AXI4 (full) burst/ID support are later phases.
//
// Capture-vector layout (LSB-first; ADDR_W=DATA_W=32 -> SAMPLE_W=152):
//   AW : awaddr[ADDR_W] awprot[3] awvalid awready
//   W  : wdata[DATA_W]  wstrb[DATA_W/8] wvalid wready
//   B  : bresp[2] bvalid bready
//   AR : araddr[ADDR_W] arprot[3] arvalid arready
//   R  : rdata[DATA_W]  rresp[2] rvalid rready
// The shipped probe map (host/fcapz/probes/axi4lite_32.prob) names every field
// at these offsets; keep them in lockstep.

module fcapz_axi_mon #(
    parameter PROTO        = "AXI4LITE", // P1 supports "AXI4LITE" only
    parameter ADDR_W       = 32,
    parameter DATA_W       = 32,
    // pass-through fcapz_ela capture/trigger configuration
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
    // Decode layer (P2): prepend an 8-bit transaction-events word at the LSB so
    // events (handshakes, response errors) are reachable by the ELA's low-32-bit
    // trigger comparator. DECODE_EN=0 keeps the P1 layout (awaddr at [31:0]).
    parameter DECODE_EN    = 0,
    // derived
    localparam STRB_W      = DATA_W / 8,
    localparam AW_W        = ADDR_W + 5,            // awaddr + awprot[3] + awvalid + awready
    localparam W_W         = DATA_W + STRB_W + 2,   // wdata + wstrb + wvalid + wready
    localparam B_W         = 4,                     // bresp[2] + bvalid + bready
    localparam AR_W        = ADDR_W + 5,            // araddr + arprot[3] + arvalid + arready
    localparam R_W         = DATA_W + 4,            // rdata + rresp[2] + rvalid + rready
    localparam EVENTS_W    = (DECODE_EN != 0) ? 8 : 0,
    localparam CHANNELS_W  = AW_W + W_W + B_W + AR_W + R_W,
    localparam SAMPLE_W    = CHANNELS_W + EVENTS_W,
    localparam PTR_W       = $clog2(DEPTH),
    localparam TS_W        = (TIMESTAMP_W > 0) ? TIMESTAMP_W : 1
) (
    // ---- Passive AXI4-Lite monitor tap (inputs only) ----
    input  wire                 ACLK,
    input  wire                 ARESETN,
    // Write address channel
    input  wire [ADDR_W-1:0]    AWADDR,
    input  wire [2:0]           AWPROT,
    input  wire                 AWVALID,
    input  wire                 AWREADY,
    // Write data channel
    input  wire [DATA_W-1:0]    WDATA,
    input  wire [STRB_W-1:0]    WSTRB,
    input  wire                 WVALID,
    input  wire                 WREADY,
    // Write response channel
    input  wire [1:0]           BRESP,
    input  wire                 BVALID,
    input  wire                 BREADY,
    // Read address channel
    input  wire [ADDR_W-1:0]    ARADDR,
    input  wire [2:0]           ARPROT,
    input  wire                 ARVALID,
    input  wire                 ARREADY,
    // Read data channel
    input  wire [DATA_W-1:0]    RDATA,
    input  wire [1:0]           RRESP,
    input  wire                 RVALID,
    input  wire                 RREADY,

    // ---- External trigger I/O (forwarded to the ELA) ----
    input  wire                 trigger_in,
    output wire                 trigger_out,
    output wire                 armed_out,

    // ---- JTAG register bus (identical to fcapz_ela) ----
    input  wire                 jtag_clk,
    input  wire                 jtag_rst,
    input  wire                 jtag_wr_en,
    input  wire                 jtag_rd_en,
    input  wire [15:0]          jtag_addr,
    input  wire [31:0]          jtag_wdata,
    output wire [31:0]          jtag_rdata,

    // ---- Burst read port (jtag_clk domain, active when done=1) ----
    input  wire [PTR_W-1:0]     burst_rd_addr,
    output wire [SAMPLE_W-1:0]  burst_rd_data,
    output wire [TS_W-1:0]      burst_rd_ts_data,
    output wire                 burst_start,
    output wire                 burst_timestamp,
    output wire [PTR_W-1:0]     burst_start_ptr
);

    // ---- Flatten the AXI channels into the capture vector (LSB-first) -------
    wire [CHANNELS_W-1:0] channels = {
        // R channel  (MSB end)
        RREADY, RVALID, RRESP, RDATA,
        // AR channel
        ARREADY, ARVALID, ARPROT, ARADDR,
        // B channel
        BREADY, BVALID, BRESP,
        // W channel
        WREADY, WVALID, WSTRB, WDATA,
        // AW channel (awaddr occupies bits [ADDR_W-1:0] of the channel block)
        AWREADY, AWVALID, AWPROT, AWADDR
    };

    // Derived transaction events (combinational; P2 decode layer). Bit order:
    //   [0] aw_hs [1] w_hs [2] b_hs [3] ar_hs [4] r_hs [5] b_err [6] r_err [7] any_err
    wire        b_err = BVALID & BRESP[1];   // SLVERR(2)/DECERR(3) -> RESP[1]=1
    wire        r_err = RVALID & RRESP[1];
    wire [7:0]  events = {
        b_err | r_err,        // any_err
        r_err,                // r_err
        b_err,                // b_err
        RVALID & RREADY,      // r_hs
        ARVALID & ARREADY,    // ar_hs
        BVALID & BREADY,      // b_hs
        WVALID & WREADY,      // w_hs
        AWVALID & AWREADY     // aw_hs
    };

    // Events sit at the LSB (when enabled) so the low-32-bit trigger can match
    // them; otherwise the raw channels start at bit 0 (P1 layout).
    wire [SAMPLE_W-1:0] probe_vec;
    generate
        if (DECODE_EN != 0) begin : g_decode
            assign probe_vec = {channels, events};
        end else begin : g_raw
            assign probe_vec = channels;
        end
    endgenerate

    // ---- AXI-monitor identity registers ------------------------------------
    // The embedded ELA owns config space 0x0000-0x00FF and exposes captured
    // samples in a register window at 0x0100+ (jtag_addr >= ADDR_DATA_BASE), so
    // the AM identity must NOT sit at 0x0100.  It lives in the free gap above
    // the ELA's last config register (0x00E0, COMPARE_CAPS) and below the data
    // window.  Registered on jtag_clk so the read timing matches the ELA's
    // registered jtag_rdata.  (The fuller AM register block -- decoder, address
    // filters, violation -- gets its own window via a regbus split in P2.)
    localparam [15:0] ADDR_AXI_MON_ID = 16'h00E8;
    localparam [15:0] ADDR_AXI_GEOM   = 16'h00EC;
    localparam [7:0]  PROTO_CODE = 8'd1;  // 1 = AXI4-Lite
    localparam [7:0]  CAP_FLAGS  = (DECODE_EN != 0) ? 8'h01 : 8'h00;  // bit0 DECODE_EN
    wire [31:0] axi_mon_id = {`FCAPZ_AXIMON_CORE_ID, PROTO_CODE, CAP_FLAGS}; // "AM"
    wire [31:0] axi_geom   = {7'd0, 5'h1F, 4'd0, DATA_W[7:0], ADDR_W[7:0]};

    wire [31:0] ela_rdata;
    reg  [31:0] am_rdata;
    reg         am_hit;
    always @(posedge jtag_clk) begin
        if (jtag_rst) begin
            am_hit   <= 1'b0;
            am_rdata <= 32'h0;
        end else begin
            am_hit   <= (jtag_addr == ADDR_AXI_MON_ID) || (jtag_addr == ADDR_AXI_GEOM);
            am_rdata <= (jtag_addr == ADDR_AXI_GEOM) ? axi_geom : axi_mon_id;
        end
    end
    assign jtag_rdata = am_hit ? am_rdata : ela_rdata;

    // ---- Embedded ELA capture/trigger engine -------------------------------
    fcapz_ela #(
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH),
        .TRIG_STAGES(TRIG_STAGES),
        .STOR_QUAL(STOR_QUAL),
        .INPUT_PIPE(INPUT_PIPE),
        .NUM_CHANNELS(1),
        .DECIM_EN(DECIM_EN),
        .EXT_TRIG_EN(EXT_TRIG_EN),
        .TIMESTAMP_W(TIMESTAMP_W),
        .NUM_SEGMENTS(NUM_SEGMENTS),
        .PROBE_MUX_W(0),
        .STARTUP_ARM(STARTUP_ARM),
        .REL_COMPARE(REL_COMPARE),
        .DUAL_COMPARE(DUAL_COMPARE),
        .USER1_DATA_EN(USER1_DATA_EN)
    ) u_ela (
        .sample_clk(ACLK),
        .sample_rst(~ARESETN),
        .probe_in(probe_vec),
        .trigger_in(trigger_in),
        .trigger_out(trigger_out),
        .armed_out(armed_out),
        .jtag_clk(jtag_clk),
        .jtag_rst(jtag_rst),
        .jtag_wr_en(jtag_wr_en),
        .jtag_rd_en(jtag_rd_en),
        .jtag_addr(jtag_addr),
        .jtag_wdata(jtag_wdata),
        .jtag_rdata(ela_rdata),
        .burst_rd_addr(burst_rd_addr),
        .burst_rd_data(burst_rd_data),
        .burst_rd_ts_data(burst_rd_ts_data),
        .burst_start(burst_start),
        .burst_timestamp(burst_timestamp),
        .burst_start_ptr(burst_start_ptr)
    );

endmodule
