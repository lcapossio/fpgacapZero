// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
//
// Simulation stub for Xilinx xpm_fifo_async.
//
// Wraps the same behavioral gray-coded FIFO used by USE_BEHAV_ASYNC_FIFO=1 so
// that the equivalence testbench can elaborate and simulate the
// USE_BEHAV_ASYNC_FIFO=0 branch of fcapz_async_fifo without a vendor install.
//
// Only the ports used by fcapz_async_fifo are implemented.  Unused inputs
// are ignored; unused outputs are left unconnected.

`timescale 1ns/1ps

module xpm_fifo_async #(
    parameter integer CDC_SYNC_STAGES     = 2,
    parameter         FIFO_MEMORY_TYPE    = "auto",
    parameter integer FIFO_READ_LATENCY   = 0,
    parameter integer FIFO_WRITE_DEPTH    = 16,
    parameter integer READ_DATA_WIDTH     = 32,
    parameter         READ_MODE           = "fwft",
    parameter integer WRITE_DATA_WIDTH    = 32,
    parameter integer FULL_RESET_VALUE    = 0,
    parameter integer RD_DATA_COUNT_WIDTH = 5,
    parameter integer WR_DATA_COUNT_WIDTH = 5,
    parameter         USE_ADV_FEATURES    = "0707"
) (
    input  wire                           wr_clk,
    input  wire                           rst,
    input  wire                           wr_en,
    input  wire [WRITE_DATA_WIDTH-1:0]    din,
    output wire                           full,

    input  wire                           rd_clk,
    input  wire                           rd_en,
    output wire [READ_DATA_WIDTH-1:0]     dout,
    output wire                           empty,
    output wire [RD_DATA_COUNT_WIDTH-1:0] rd_data_count,
    output wire [WR_DATA_COUNT_WIDTH-1:0] wr_data_count,

    // Unused outputs
    output wire wr_rst_busy,
    output wire rd_rst_busy,
    output wire almost_full,
    output wire almost_empty,
    output wire data_valid,
    output wire overflow,
    output wire underflow,
    output wire prog_full,
    output wire prog_empty,

    // Unused inputs
    input  wire sleep,
    input  wire injectsbiterr,
    input  wire injectdbiterr,
    output wire sbiterr,
    output wire dbiterr
);

    localparam AW = $clog2(FIFO_WRITE_DEPTH);

    // Tie off unused outputs
    assign wr_rst_busy  = 1'b0;
    assign rd_rst_busy  = 1'b0;
    assign almost_full  = 1'b0;
    assign almost_empty = 1'b0;
    assign data_valid   = 1'b0;
    assign overflow     = 1'b0;
    assign underflow    = 1'b0;
    assign prog_full    = 1'b0;
    assign prog_empty   = 1'b0;
    assign sbiterr      = 1'b0;
    assign dbiterr      = 1'b0;

    // Instantiate the behavioral FIFO directly
    fcapz_async_fifo #(
        .DATA_W                (WRITE_DATA_WIDTH),
        .DEPTH                 (FIFO_WRITE_DEPTH),
        .USE_BEHAV_ASYNC_FIFO  (1)
    ) u_behav (
        .wr_clk   (wr_clk),
        .wr_rst   (rst),
        .wr_en    (wr_en),
        .wr_data  (din),
        .wr_full  (full),
        .wr_count (wr_data_count[AW:0]),

        .rd_clk   (rd_clk),
        .rd_rst   (rst),
        .rd_en    (rd_en),
        .rd_data  (dout),
        .rd_empty (empty),
        .rd_count (rd_data_count[AW:0])
    );

endmodule
