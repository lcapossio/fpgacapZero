// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// ELA wrapper driven over a UART instead of JTAG (vendor-agnostic).
//
// Structurally identical to the vendor wrappers (fcapz_ela_xilinx7,
// fcapz_ela_efinix, ...): the same fcapz_ela core, the same jtag_reg_iface on
// the control chain and jtag_burst_read on the burst chain.  The only
// difference is where the DR scans come from -- fcapz_uart_tap synthesises the
// TAP contract from a serial byte stream instead of a hard TAP block.
//
// Use this on boards whose fabric has no JTAG at all.  The reference target is
// the Forgix board (Efinix Trion T8F49 + RP2354), where the FPGA's JTAG pins
// are bonded out nowhere and the only host link is a UART; see
// examples/forgix/.  Nothing here is vendor-specific.
//
// Chain map (the sel[] index of fcapz_uart_tap):
//   chain 1 -> control registers (jtag_reg_iface)
//   chain 2 -> burst sample readout (jtag_burst_read)
//
// Host side: fcapz.transport.SerialTapTransport.

module fcapz_ela_uart #(
    // UART front-end
    parameter CLK_HZ      = 50_000_000,
    parameter BAUD_RATE   = 1_000_000,
    // ELA core -- mirrors the vendor wrappers
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
    parameter REL_COMPARE = 0,
    parameter DUAL_COMPARE = 1,
    parameter USER1_DATA_EN = 1
) (
    input  wire                          sample_clk,
    input  wire                          sample_rst,
    input  wire [SAMPLE_W*NUM_CHANNELS-1:0] probe_in,
    input  wire                          trigger_in,
    output wire                          trigger_out,
    output wire                          armed_out,

    // Host link.  On Forgix these are two header pins jumpered to the
    // RP2354's UART0 (see examples/forgix/README.md); on any other board they
    // can go straight to a USB-serial cable.
    input  wire                          uart_rxd,
    output wire                          uart_txd
);

    localparam PTR_W = $clog2(DEPTH);
    localparam BURST_SEG_DEPTH = DEPTH / NUM_SEGMENTS;

    localparam NUM_CHAINS = 2;

    // TAP signals -- shared strobes, per-chain select, exactly as a real TAP
    // presents them.
    wire tap_tck, tap_tdi;
    wire tap_capture, tap_shift, tap_update;
    wire [NUM_CHAINS-1:0] tap_sel;
    wire [NUM_CHAINS-1:0] tap_tdo;

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
    wire                jtag_rst_sync;

    // ---- UART virtual TAP ----
    // BURST_W sets the widest DR the burst chain will ever scan, so it is also
    // the bridge's MAX_DR_BITS; the control chain's 49 bits fit inside it.
    fcapz_uart_tap #(
        .CLK_HZ(CLK_HZ), .BAUD_RATE(BAUD_RATE),
        .NUM_CHAINS(NUM_CHAINS), .MAX_DR_BITS(BURST_W)
    ) u_tap (
        .clk(sample_clk), .arst(sample_rst),
        .uart_rxd(uart_rxd), .uart_txd(uart_txd),
        .tck(tap_tck), .tdi(tap_tdi), .tdo(tap_tdo),
        .capture(tap_capture), .shift(tap_shift),
        .update(tap_update), .sel(tap_sel)
    );

    // Both chains share one tck, so one synchroniser serves both.
    reset_sync u_rst_sync (
        .clk(tap_tck),
        .arst(sample_rst),
        .srst(jtag_rst_sync)
    );

    // ---- Chain 1: control registers ----
    jtag_reg_iface u_reg (
        .arst(jtag_rst_sync),
        .tck(tap_tck), .tdi(tap_tdi), .tdo(tap_tdo[0]),
        .capture(tap_capture), .shift_en(tap_shift),
        .update(tap_update), .sel(tap_sel[0]),
        .reg_clk(jtag_clk), .reg_rst(jtag_rst),
        .reg_wr_en(jtag_wr_en), .reg_rd_en(jtag_rd_en),
        .reg_addr(jtag_addr), .reg_wdata(jtag_wdata),
        .reg_rdata(jtag_rdata)
    );

    // ---- ELA core ----
    fcapz_ela #(
        .SAMPLE_W(SAMPLE_W), .DEPTH(DEPTH),
        .TRIG_STAGES(TRIG_STAGES), .STOR_QUAL(STOR_QUAL),
        .INPUT_PIPE(INPUT_PIPE), .NUM_CHANNELS(NUM_CHANNELS),
        .DECIM_EN(DECIM_EN), .EXT_TRIG_EN(EXT_TRIG_EN),
        .TIMESTAMP_W(TIMESTAMP_W), .NUM_SEGMENTS(NUM_SEGMENTS),
        .PROBE_MUX_W(PROBE_MUX_W), .STARTUP_ARM(STARTUP_ARM),
        .DEFAULT_TRIG_EXT(DEFAULT_TRIG_EXT), .REL_COMPARE(REL_COMPARE),
        .DUAL_COMPARE(DUAL_COMPARE), .USER1_DATA_EN(USER1_DATA_EN)
    ) u_ela (
        .sample_clk(sample_clk), .sample_rst(sample_rst),
        .probe_in(probe_in),
        .trigger_in(trigger_in),
        .trigger_out(trigger_out),
        .armed_out(armed_out),
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

    // ---- Chain 2: burst read engine ----
    jtag_burst_read #(
        .SAMPLE_W(SAMPLE_W), .TIMESTAMP_W(TIMESTAMP_W),
        .DEPTH(DEPTH), .BURST_W(BURST_W), .SEG_DEPTH(BURST_SEG_DEPTH)
    ) u_burst (
        .arst(jtag_rst_sync),
        .tck(tap_tck), .tdi(tap_tdi), .tdo(tap_tdo[1]),
        .capture(tap_capture), .shift_en(tap_shift),
        .update(tap_update), .sel(tap_sel[1]),
        .mem_addr(burst_rd_addr),
        .mem_active(burst_rd_active),
        .sample_data(burst_rd_data), .timestamp_data(burst_rd_ts_data),
        .burst_start(burst_start), .burst_timestamp(burst_timestamp),
        .burst_ptr_in(burst_start_ptr)
    );

endmodule
