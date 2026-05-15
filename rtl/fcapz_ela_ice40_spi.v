// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero ELA wrapper for Lattice iCE40 over an external SPI register bus.
//
// iCE40 does not expose an ECP5-style user JTAG primitive to RTL, so this
// wrapper does not use native FPGA JTAG. Instead, connect spi_sck/spi_cs_n/
// spi_mosi/spi_miso to pins reachable by the host adapter and use the host
// SpiRegisterTransport. Sample readback is the normal 32-bit DATA register
// window, so it is functional and portable but not burst-accelerated.

module fcapz_ela_ice40_spi #(
    parameter SAMPLE_W      = 8,
    parameter DEPTH         = 1024,
    parameter TRIG_STAGES   = 1,
    parameter STOR_QUAL     = 0,
    parameter INPUT_PIPE    = 0,
    parameter NUM_CHANNELS  = 1,
    parameter TIMESTAMP_W   = 0,
    parameter STARTUP_ARM   = 0,
    parameter REL_COMPARE   = 0,
    parameter DUAL_COMPARE  = 1,
    parameter USER1_DATA_EN = 1
) (
    input  wire                              sample_clk,
    input  wire                              sample_rst,
    input  wire [SAMPLE_W*NUM_CHANNELS-1:0] probe_in,

    input  wire                              spi_sck,
    input  wire                              spi_cs_n,
    input  wire                              spi_mosi,
    output wire                              spi_miso
);

    localparam PTR_W = $clog2(DEPTH);

    wire        reg_clk;
    wire        reg_rst;
    wire        reg_wr_en;
    wire        reg_rd_en;
    wire [15:0] reg_addr;
    wire [31:0] reg_wdata;
    wire [31:0] reg_rdata;

    wire [PTR_W-1:0] burst_rd_addr_dummy = {PTR_W{1'b0}};
    wire [SAMPLE_W-1:0] burst_rd_data_unused;
    wire [((TIMESTAMP_W > 0) ? TIMESTAMP_W : 1)-1:0] burst_rd_ts_data_unused;
    wire burst_start_unused;
    wire burst_timestamp_unused;
    wire [PTR_W-1:0] burst_start_ptr_unused;
    wire trigger_out_unused;
    wire armed_out_unused;

    fcapz_spi_reg_iface u_spi (
        .spi_sck(spi_sck),
        .spi_cs_n(spi_cs_n),
        .spi_mosi(spi_mosi),
        .spi_miso(spi_miso),
        .reg_clk(reg_clk),
        .reg_rst(reg_rst),
        .reg_wr_en(reg_wr_en),
        .reg_rd_en(reg_rd_en),
        .reg_addr(reg_addr),
        .reg_wdata(reg_wdata),
        .reg_rdata(reg_rdata)
    );

    fcapz_ela #(
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH),
        .TRIG_STAGES(TRIG_STAGES),
        .STOR_QUAL(STOR_QUAL),
        .INPUT_PIPE(INPUT_PIPE),
        .NUM_CHANNELS(NUM_CHANNELS),
        .TIMESTAMP_W(TIMESTAMP_W),
        .STARTUP_ARM(STARTUP_ARM),
        .REL_COMPARE(REL_COMPARE),
        .DUAL_COMPARE(DUAL_COMPARE),
        .USER1_DATA_EN(USER1_DATA_EN)
    ) u_ela (
        .sample_clk(sample_clk),
        .sample_rst(sample_rst),
        .probe_in(probe_in),
        .trigger_in(1'b0),
        .trigger_out(trigger_out_unused),
        .armed_out(armed_out_unused),
        .jtag_clk(reg_clk),
        .jtag_rst(sample_rst | reg_rst),
        .jtag_wr_en(reg_wr_en),
        .jtag_rd_en(reg_rd_en),
        .jtag_addr(reg_addr),
        .jtag_wdata(reg_wdata),
        .jtag_rdata(reg_rdata),
        .burst_rd_addr(burst_rd_addr_dummy),
        .burst_rd_data(burst_rd_data_unused),
        .burst_rd_ts_data(burst_rd_ts_data_unused),
        .burst_start(burst_start_unused),
        .burst_timestamp(burst_timestamp_unused),
        .burst_start_ptr(burst_start_ptr_unused)
    );

endmodule
