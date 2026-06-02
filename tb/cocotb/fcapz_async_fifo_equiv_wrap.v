// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
//
// NOTE: dut_b sets USE_BEHAV_ASYNC_FIFO=0, which selects xpm_fifo_async. In
// CI (and any non-vendor build) that symbol resolves to tb/xpm_fifo_async_stub.v,
// which itself re-instantiates fcapz_async_fifo with USE_BEHAV_ASYNC_FIFO=1.
// As a result, against the stub this test compares the behavioral FIFO with
// itself and cannot catch divergence from the real vendor xpm_fifo_async.
// It still catches port-list / parameter drift between fcapz_async_fifo's two
// branches and is meant to be re-run against the real XPM in a vendor flow.

`timescale 1ns/1ps

module fcapz_async_fifo_equiv_wrap #(
    parameter DATA_W = 8,
    parameter DEPTH = 16
) (
    input  wire              wr_clk,
    input  wire              rd_clk,
    input  wire              rst,
    input  wire              wr_en,
    input  wire [DATA_W-1:0] wr_data,
    input  wire              rd_en,
    output wire [DATA_W-1:0] rd_data_a,
    output wire [DATA_W-1:0] rd_data_b,
    output wire              rd_empty_a,
    output wire              rd_empty_b,
    output wire              wr_full_a,
    output wire              wr_full_b
);

    fcapz_async_fifo #(
        .DATA_W(DATA_W),
        .DEPTH(DEPTH),
        .USE_BEHAV_ASYNC_FIFO(1)
    ) dut_a (
        .wr_clk(wr_clk),
        .wr_rst(rst),
        .wr_en(wr_en),
        .wr_data(wr_data),
        .wr_full(wr_full_a),
        .wr_rst_busy(),
        .wr_count(),
        .rd_clk(rd_clk),
        .rd_rst(rst),
        .rd_en(rd_en),
        .rd_data(rd_data_a),
        .rd_empty(rd_empty_a),
        .rd_rst_busy(),
        .rd_count()
    );

    fcapz_async_fifo #(
        .DATA_W(DATA_W),
        .DEPTH(DEPTH),
        .USE_BEHAV_ASYNC_FIFO(0)
    ) dut_b (
        .wr_clk(wr_clk),
        .wr_rst(rst),
        .wr_en(wr_en),
        .wr_data(wr_data),
        .wr_full(wr_full_b),
        .wr_rst_busy(),
        .wr_count(),
        .rd_clk(rd_clk),
        .rd_rst(rst),
        .rd_en(rd_en),
        .rd_data(rd_data_b),
        .rd_empty(rd_empty_b),
        .rd_rst_busy(),
        .rd_count()
    );

endmodule
