// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Asynchronous FIFO with parameterized vendor implementation.
//
// ASYNC_FIFO_IMPL=0: portable behavioral gray-coded pointer FIFO.
// ASYNC_FIFO_IMPL=1: AMD/Xilinx xpm_fifo_async.
//
// USE_BEHAV_ASYNC_FIFO is kept for compatibility with older wrappers:
//   1 -> ASYNC_FIFO_IMPL=0
//   0 -> ASYNC_FIFO_IMPL=1
//
// Read mode is first-word fall-through (FWFT): rd_data is valid
// whenever rd_empty=0, without asserting rd_en first.  Asserting
// rd_en pops the current head and advances to the next entry.
//
// Reset: wr_rst resets write-domain state, rd_rst resets read-domain
// state.  Both are active-high async.  For clean CDC, each reset
// should be synchronous to its respective clock domain.  The XPM
// version has a single reset: either input resets the whole FIFO,
// synchronized to wr_clk inside.  wr_rst_busy / rd_rst_busy cover it
// (rd_rst_busy from rd_rst on, even if wr_clk is stopped), and the FIFO
// reads full / empty on a busy side.
//
// Parameters:
//   DATA_W  - data width in bits (default 32)
//   DEPTH   - FIFO depth in entries, must be power of 2 (default 16)
//   USE_BEHAV_ASYNC_FIFO - legacy selector, 1=behavioral, 0=XPM
//   ASYNC_FIFO_IMPL      - 0=behavioral, 1=AMD/Xilinx XPM
//   XPM_FIFO_MEMORY_TYPE - XPM storage selector ("auto", "block", "distributed")

module fcapz_async_fifo #(
    parameter DATA_W  = 32,
    parameter DEPTH   = 16,
    parameter USE_BEHAV_ASYNC_FIFO = 1,
    parameter ASYNC_FIFO_IMPL = (USE_BEHAV_ASYNC_FIFO ? 0 : 1),
    parameter XPM_FIFO_MEMORY_TYPE = "auto"
) (
    // Write side (wr_clk domain)
    input  wire                      wr_clk,
    input  wire                      wr_rst,    // active-high async reset
    input  wire                      wr_en,
    input  wire [DATA_W-1:0]         wr_data,
    output wire                      wr_full,
    output wire                      wr_rst_busy,

    // Read side (rd_clk domain)
    input  wire                      rd_clk,
    input  wire                      rd_rst,    // active-high async reset (rd_clk domain)
    input  wire                      rd_en,
    output wire [DATA_W-1:0]         rd_data,
    output wire                      rd_empty,
    output wire                      rd_rst_busy,

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
if (ASYNC_FIFO_IMPL == 1) begin : gen_xpm
    // =================================================================
    //  Vendor primitive (Xilinx XPM) implementation
    // =================================================================

    if (DEPTH < 16)
        XPM_FIFO_DEPTH_must_be_at_least_16 _xpm_depth_check_FAILED();
    initial begin
        if (DEPTH < 16)
            $error("fcapz_async_fifo: XPM FIFO depth must be >= 16 (got %0d)", DEPTH);
    end

    wire [AW:0] xpm_rd_count;
    wire [AW:0] xpm_wr_count;
    wire        xpm_wr_rst_busy;
    wire        xpm_rd_rst_busy;
    wire        xpm_full;
    wire        xpm_empty;

    // XPM has one rst, which must be synchronous to wr_clk, while wr_rst and
    // rd_rst come from different domains. Either one (a pulse of the other
    // clock included) sets xpm_req_cap at once; a plain synchronizer turns
    // that into xpm_req, and xpm_rst is a two-cycle wr_clk pulse started from
    // it. XPM ignores a reset that starts while it is still busy with the
    // previous one, so the request waits (and stays captured) until XPM's
    // busy falls. Everything writers see is registered on wr_clk.
    reg xpm_req_cap;
    (* ASYNC_REG = "TRUE" *) reg [1:0] xpm_req_sync;
    reg xpm_rst;
    reg xpm_rst_d;
    // High from the reset request until XPM's reset sequence is over; XPM
    // keeps its wr_rst_busy up until its read side is out of reset too.
    reg xpm_rst_pend;
    initial begin
        xpm_req_cap = 1'b1;
        xpm_req_sync = 2'b11;
        xpm_rst = 1'b1;
        xpm_rst_d = 1'b0;
        xpm_rst_pend = 1'b1;
    end
    wire xpm_arst = wr_rst | rd_rst;
    wire xpm_req = xpm_req_sync[1];
    wire xpm_rst_start = xpm_req && !xpm_rst && !xpm_rst_d && !xpm_wr_rst_busy;
    always @(posedge wr_clk or posedge xpm_arst) begin
        if (xpm_arst) begin
            xpm_req_cap  <= 1'b1;
            xpm_rst_pend <= 1'b1;
        end else begin
            if (xpm_rst)
                xpm_req_cap <= 1'b0;
            xpm_rst_pend <= xpm_req_cap | xpm_req | xpm_rst | xpm_wr_rst_busy;
        end
    end
    always @(posedge wr_clk) begin
        xpm_req_sync <= {xpm_req_sync[0], xpm_req_cap};
        xpm_rst_d    <= xpm_rst;
        if (xpm_rst_start)
            xpm_rst <= 1'b1;
        else if (xpm_rst_d)
            xpm_rst <= 1'b0;
    end

    // wr_clk can stop (TCK between scans) before XPM has seen the reset, so
    // the read side keeps its own view: rd_rst stops reads at once, and they
    // resume only once xpm_rst_pend has fallen, seen through rd_clk.
    (* ASYNC_REG = "TRUE" *) reg [1:0] rd_rst_pend_sync;
    initial rd_rst_pend_sync = 2'b11;
    always @(posedge rd_clk or posedge rd_rst) begin
        if (rd_rst)
            rd_rst_pend_sync <= 2'b11;
        else
            rd_rst_pend_sync <= {rd_rst_pend_sync[0], xpm_rst_pend};
    end

    // Writes stop once the request is through the synchronizer and stay
    // stopped until XPM is out of reset. Each side reads full / empty while
    // busy, so callers that check only wr_full / rd_empty neither lose writes
    // nor read stale words.
    assign wr_rst_busy = xpm_req | xpm_rst | xpm_rst_d | xpm_wr_rst_busy;
    assign rd_rst_busy = rd_rst_pend_sync[1] | xpm_rd_rst_busy;
    assign wr_full     = xpm_full | wr_rst_busy;
    assign rd_empty    = xpm_empty | rd_rst_busy;

    xpm_fifo_async #(
        .CDC_SYNC_STAGES     (2),
        .FIFO_MEMORY_TYPE    (XPM_FIFO_MEMORY_TYPE),
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
        .rst            (xpm_rst),
        .wr_en          (wr_en && !wr_rst_busy),
        .din            (wr_data),
        .full           (xpm_full),

        .rd_clk         (rd_clk),
        .rd_en          (rd_en && !rd_rst_busy),
        .dout           (rd_data),
        .empty          (xpm_empty),
        .rd_data_count  (xpm_rd_count),

        .wr_data_count  (xpm_wr_count),
        .wr_rst_busy    (xpm_wr_rst_busy),
        .rd_rst_busy    (xpm_rd_rst_busy),
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

    // ---- Read side (rd_clk) ----------------------------------------
    reg [AW:0] rptr_gray;       // gray-coded read pointer
    wire [AW:0] rptr_bin = gray2bin(rptr_gray);

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
    assign wr_rst_busy = 1'b0;
    assign rd_rst_busy = 1'b0;

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
