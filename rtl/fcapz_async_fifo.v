// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Asynchronous FIFO with parameterized vendor implementation.
//
// USE_BEHAV_ASYNC_FIFO=1 (default): portable behavioral gray-coded pointer FIFO.
// USE_BEHAV_ASYNC_FIFO=0:           vendor primitive (Xilinx xpm_fifo_async).
//
// Read mode is first-word fall-through (FWFT): rd_data is valid
// whenever rd_empty=0, without asserting rd_en first.  Asserting
// rd_en pops the current head and advances to the next entry.
//
// Reset: wr_rst resets write-domain state, rd_rst resets read-domain
// state.  Both are active-high async.  For clean CDC, each reset
// should be synchronous to its respective clock domain.
//
// Parameters:
//   DATA_W  - data width in bits (default 32)
//   DEPTH   - FIFO depth in entries, must be power of 2 (default 16)
//   USE_BEHAV_ASYNC_FIFO - 1=portable behavioral (default), 0=vendor primitive

module fcapz_async_fifo #(
    parameter DATA_W  = 32,
    parameter DEPTH   = 16,
    parameter USE_BEHAV_ASYNC_FIFO = 1
) (
    // Write side (wr_clk domain)
    input  wire                      wr_clk,
    input  wire                      wr_rst,    // active-high async reset
    input  wire                      wr_en,
    input  wire [DATA_W-1:0]         wr_data,
    output wire                      wr_full,

    // Read side (rd_clk domain)
    input  wire                      rd_clk,
    input  wire                      rd_rst,    // active-high async reset (rd_clk domain)
    input  wire                      rd_en,
    output wire [DATA_W-1:0]         rd_data,
    output wire                      rd_empty,

    // Approximate count in rd_clk domain
    output wire [$clog2(DEPTH):0]    rd_count,

    // Approximate count in wr_clk domain
    output wire [$clog2(DEPTH):0]    wr_count
);

    localparam AW = $clog2(DEPTH);

    // ---- Parameter assertions -------------------------------------------------
    // Synthesis-safe: undefined module reference forces an elaboration error.
    generate
        if (DEPTH & (DEPTH - 1))
            DEPTH_must_be_power_of_2 _depth_check_FAILED();
    endgenerate

    // Simulation-friendly versions of the same checks.
    initial begin
        if (DEPTH & (DEPTH - 1))
            $error("fcapz_async_fifo: DEPTH must be a power of 2 (got %0d)", DEPTH);
        if (DATA_W < 1)
            $error("fcapz_async_fifo: DATA_W must be >= 1");
    end

generate
if (!USE_BEHAV_ASYNC_FIFO) begin : gen_xpm
    // =================================================================
    //  Vendor primitive (Xilinx XPM) implementation
    // =================================================================

    wire [AW:0] xpm_rd_count;
    wire [AW:0] xpm_wr_count;

    xpm_fifo_async #(
        .CDC_SYNC_STAGES     (2),
        .FIFO_MEMORY_TYPE    ("auto"),
        .FIFO_READ_LATENCY   (0),
        .FIFO_WRITE_DEPTH    (DEPTH),
        .READ_DATA_WIDTH     (DATA_W),
        .READ_MODE           ("fwft"),
        .WRITE_DATA_WIDTH    (DATA_W),
        .FULL_RESET_VALUE    (0),
        .RD_DATA_COUNT_WIDTH (AW + 1),
        .WR_DATA_COUNT_WIDTH (AW + 1),
        .USE_ADV_FEATURES    ("0404")   // enable rd_data_count + wr_data_count
    ) u_xpm_fifo (
        .wr_clk         (wr_clk),
        .rst            (wr_rst | rd_rst),
        .wr_en          (wr_en),
        .din            (wr_data),
        .full           (wr_full),

        .rd_clk         (rd_clk),
        .rd_en          (rd_en),
        .dout           (rd_data),
        .empty          (rd_empty),
        .rd_data_count  (xpm_rd_count),

        .wr_data_count  (xpm_wr_count),
        .wr_rst_busy    (),
        .rd_rst_busy    (),
        .almost_full    (),
        .almost_empty   (),
        .data_valid     (),
        .overflow       (),
        .underflow      (),
        .prog_full      (),
        .prog_empty     (),

        // Unused inputs
        .sleep          (1'b0),
        .injectsbiterr  (1'b0),
        .injectdbiterr  (1'b0),
        .sbiterr        (),
        .dbiterr        ()
    );

    assign rd_count = xpm_rd_count;
    assign wr_count = xpm_wr_count;

end else begin : gen_behavioral
    // =================================================================
    //  Behavioral gray-coded pointer implementation
    // =================================================================

    // ---- Gray code helpers -----------------------------------------
    function [AW:0] bin2gray;
        input [AW:0] b;
        begin
            bin2gray = b ^ (b >> 1);
        end
    endfunction

    function [AW:0] gray2bin;
        input [AW:0] g;
        integer k;
        begin
            gray2bin[AW] = g[AW];
            for (k = AW - 1; k >= 0; k = k - 1)
                gray2bin[k] = gray2bin[k+1] ^ g[k];
        end
    endfunction

    // ---- Storage ---------------------------------------------------
    reg [DATA_W-1:0] mem [0:DEPTH-1];

    // ---- Write side (wr_clk) ---------------------------------------
    reg [AW:0] wptr_bin;        // binary write pointer
    reg [AW:0] wptr_gray;       // gray-coded write pointer (read by rd_clk)

    // Sync read pointer into write domain
    (* ASYNC_REG = "TRUE" *) reg [AW:0] rptr_sync1_w, rptr_sync2_w;

    always @(posedge wr_clk or posedge wr_rst) begin
        if (wr_rst) begin
            rptr_sync1_w <= {(AW+1){1'b0}};
            rptr_sync2_w <= {(AW+1){1'b0}};
        end else begin
            rptr_sync1_w <= rptr_gray;
            rptr_sync2_w <= rptr_sync1_w;
        end
    end

    // Full: gray-coded MSBs differ, rest matches
    assign wr_full = (wptr_gray == {~rptr_sync2_w[AW:AW-1],
                                     rptr_sync2_w[AW-2:0]});

    always @(posedge wr_clk or posedge wr_rst) begin
        if (wr_rst) begin
            wptr_bin  <= {(AW+1){1'b0}};
            wptr_gray <= {(AW+1){1'b0}};
        end else if (wr_en && !wr_full) begin
            mem[wptr_bin[AW-1:0]] <= wr_data;
            wptr_bin  <= wptr_bin + 1;
            wptr_gray <= bin2gray(wptr_bin + 1);
        end
    end

    // ---- Read side (rd_clk) ----------------------------------------
    reg [AW:0] rptr_gray;       // gray-coded read pointer
    wire [AW:0] rptr_bin = gray2bin(rptr_gray);

    // Sync write pointer into read domain
    (* ASYNC_REG = "TRUE" *) reg [AW:0] wptr_sync1_r, wptr_sync2_r;

    always @(posedge rd_clk or posedge rd_rst) begin
        if (rd_rst) begin
            wptr_sync1_r <= {(AW+1){1'b0}};
            wptr_sync2_r <= {(AW+1){1'b0}};
        end else begin
            wptr_sync1_r <= wptr_gray;
            wptr_sync2_r <= wptr_sync1_r;
        end
    end

    assign rd_empty = (rptr_gray == wptr_sync2_r);

    // FWFT: rd_data always shows head of FIFO
    assign rd_data = mem[rptr_bin[AW-1:0]];

    always @(posedge rd_clk or posedge rd_rst) begin
        if (rd_rst) begin
            rptr_gray <= {(AW+1){1'b0}};
        end else if (rd_en && !rd_empty) begin
            rptr_gray <= bin2gray(rptr_bin + 1);
        end
    end

    // ---- Approximate count (rd_clk domain) -------------------------
    wire [AW:0] wptr_bin_rd = gray2bin(wptr_sync2_r);
    assign rd_count = wptr_bin_rd - rptr_bin;

    // ---- Approximate count (wr_clk domain) -------------------------
    wire [AW:0] rptr_bin_wr = gray2bin(rptr_sync2_w);
    assign wr_count = wptr_bin - rptr_bin_wr;

    // ---- Initial values (for simulation) ---------------------------
    initial begin
        wptr_bin     = {(AW+1){1'b0}};
        wptr_gray    = {(AW+1){1'b0}};
        rptr_gray    = {(AW+1){1'b0}};
        rptr_sync1_w = {(AW+1){1'b0}};
        rptr_sync2_w = {(AW+1){1'b0}};
        wptr_sync1_r = {(AW+1){1'b0}};
        wptr_sync2_r = {(AW+1){1'b0}};
    end

end
endgenerate

endmodule
