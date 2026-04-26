// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Single-chain JTAG register + burst pipe.
//
// This keeps the existing 49-bit register protocol for normal CSR accesses,
// then reuses the same USER chain for 256-bit packed capture reads after the
// host writes BURST_PTR.  One BSCAN chain carries both control packets and
// high-throughput data packets.

module jtag_pipe_iface #(
    parameter SAMPLE_W = 8,
    parameter TIMESTAMP_W = 0,
    parameter DEPTH = 1024,
    parameter BURST_W = 256,
    parameter SEG_DEPTH = DEPTH,
    parameter BURST_PTR_ADDR = 16'h002C
) (
    input  wire        arst,

    // TAP signals (from vendor-specific wrapper)
    input  wire        tck,
    input  wire        tdi,
    output wire        tdo,
    input  wire        capture,
    input  wire        shift_en,
    input  wire        update,
    input  wire        sel,

    // Register bus
    output wire        reg_clk,
    output wire        reg_rst,
    output reg         reg_wr_en,
    output reg         reg_rd_en,
    output reg  [15:0] reg_addr,
    output reg  [31:0] reg_wdata,
    input  wire [31:0] reg_rdata,

    // Dual-port memory read (tck domain)
    output wire [$clog2(DEPTH)-1:0] mem_addr,
    input  wire [SAMPLE_W-1:0]      sample_data,
    input  wire [((TIMESTAMP_W > 0) ? TIMESTAMP_W : 1)-1:0] timestamp_data,

    // Control (tck domain, from ELA core via reg bus)
    input  wire                      burst_start,
    input  wire                      burst_timestamp,
    input  wire [$clog2(DEPTH)-1:0]  burst_ptr_in
);

    localparam PTR_W = $clog2(DEPTH);
    localparam SEG_PTR_W = $clog2(SEG_DEPTH);
    localparam TS_W_SAFE = (TIMESTAMP_W > 0) ? TIMESTAMP_W : 1;
    localparam SAMPLES_PER_SCAN = BURST_W / SAMPLE_W;
    localparam TS_PER_SCAN = BURST_W / TS_W_SAFE;
    localparam MAX_PER_SCAN = (SAMPLES_PER_SCAN > TS_PER_SCAN) ? SAMPLES_PER_SCAN : TS_PER_SCAN;
    localparam LOAD_CTR_W = $clog2(MAX_PER_SCAN + 1);
    localparam SHIFT_CTR_W = $clog2(BURST_W + 1);
    localparam [LOAD_CTR_W-1:0] SAMPLES_PER_SCAN_C = SAMPLES_PER_SCAN;
    localparam [LOAD_CTR_W-1:0] TS_PER_SCAN_C = TS_PER_SCAN;
    localparam [SHIFT_CTR_W-1:0] REG_SCAN_BITS = 49;
    localparam [SHIFT_CTR_W-1:0] BURST_SCAN_BITS = BURST_W;

    generate
        if (SEG_DEPTH != 0 && (SEG_DEPTH & (SEG_DEPTH - 1)) != 0) begin : g_bad_seg_depth
            SEG_DEPTH_must_be_power_of_two invalid();
        end
    endgenerate

    reg [BURST_W-1:0] sr;
    reg [48:0] cmd_sr;
    reg [BURST_W-1:0] staging;
    reg [SEG_PTR_W-1:0] rd_off;
    reg [SEG_PTR_W-1:0] next_off;
    reg [PTR_W-1:0] burst_seg_base;
    reg [LOAD_CTR_W-1:0] load_cnt;
    reg [SHIFT_CTR_W-1:0] shift_cnt;
    reg burst_timestamp_r;
    reg burst_start_seen;
    reg burst_mode;
    reg loading;

    wire [LOAD_CTR_W-1:0] words_per_scan =
        burst_timestamp_r ? TS_PER_SCAN_C : SAMPLES_PER_SCAN_C;
    wire [LOAD_CTR_W-1:0] start_words_per_scan =
        burst_timestamp ? TS_PER_SCAN_C : SAMPLES_PER_SCAN_C;

    wire [PTR_W-1:0] seg_base_of_ptr;
    wire [SEG_PTR_W-1:0] burst_ptr_off;
    generate
        if (SEG_DEPTH >= DEPTH) begin : g_seg_base_flat
            assign seg_base_of_ptr = {PTR_W{1'b0}};
            assign burst_ptr_off = burst_ptr_in;
        end else begin : g_seg_base_split
            assign seg_base_of_ptr = {burst_ptr_in[PTR_W-1:SEG_PTR_W], {SEG_PTR_W{1'b0}}};
            assign burst_ptr_off = burst_ptr_in[SEG_PTR_W-1:0];
        end
    endgenerate

    assign tdo = sr[0];
    assign reg_clk = tck;
    assign reg_rst = arst;

    generate
        if (SEG_DEPTH >= DEPTH) begin : g_mem_addr_flat
            assign mem_addr = rd_off;
        end else begin : g_mem_addr_split
            assign mem_addr = {burst_seg_base[PTR_W-1:SEG_PTR_W], rd_off};
        end
    endgenerate

    always @(posedge tck or posedge arst) begin
        if (arst) begin
            sr <= {BURST_W{1'b0}};
            cmd_sr <= 49'h0;
            staging <= {BURST_W{1'b0}};
            rd_off <= {SEG_PTR_W{1'b0}};
            next_off <= {SEG_PTR_W{1'b0}};
            burst_seg_base <= {PTR_W{1'b0}};
            load_cnt <= {LOAD_CTR_W{1'b0}};
            shift_cnt <= {SHIFT_CTR_W{1'b0}};
            burst_timestamp_r <= 1'b0;
            burst_start_seen <= 1'b0;
            burst_mode <= 1'b0;
            loading <= 1'b0;
            reg_wr_en <= 1'b0;
            reg_rd_en <= 1'b0;
            reg_addr <= 16'h0;
            reg_wdata <= 32'h0;
        end else begin
            reg_wr_en <= 1'b0;
            reg_rd_en <= 1'b0;

            if (sel) begin
                if (capture) begin
                    shift_cnt <= {SHIFT_CTR_W{1'b0}};
                    cmd_sr <= 49'h0;
                    if (burst_start ^ burst_start_seen) begin
                        burst_start_seen <= burst_start;
                        burst_mode <= 1'b1;
                        burst_seg_base <= seg_base_of_ptr;
                        rd_off <= burst_ptr_off + start_words_per_scan - 1'b1;
                        next_off <= burst_ptr_off + start_words_per_scan;
                        load_cnt <= {LOAD_CTR_W{1'b0}};
                        burst_timestamp_r <= burst_timestamp;
                        loading <= 1'b1;
                    end else if (burst_mode) begin
                        sr <= staging;
                        rd_off <= next_off + words_per_scan - 1'b1;
                        next_off <= next_off + words_per_scan;
                        load_cnt <= {LOAD_CTR_W{1'b0}};
                        loading <= 1'b1;
                    end else begin
                        sr[31:0] <= reg_rdata;
                    end
                end else if (shift_en) begin
                    sr <= {tdi, sr[BURST_W-1:1]};
                    cmd_sr <= {tdi, cmd_sr[48:1]};
                    if (shift_cnt != BURST_SCAN_BITS)
                        shift_cnt <= shift_cnt + 1'b1;
                end else if (update) begin
                    if (shift_cnt == REG_SCAN_BITS) begin
                        if (cmd_sr[48]) begin
                            reg_addr <= cmd_sr[47:32];
                            reg_wdata <= cmd_sr[31:0];
                            reg_wr_en <= 1'b1;
                            if (cmd_sr[47:32] == BURST_PTR_ADDR)
                                burst_mode <= 1'b1;
                            else
                                burst_mode <= 1'b0;
                        end else begin
                            reg_addr <= cmd_sr[47:32];
                            reg_rd_en <= 1'b1;
                            burst_mode <= 1'b0;
                        end
                    end
                end
            end

            if (loading && !(sel && capture)) begin
                if (load_cnt > 0) begin
                    if (burst_timestamp_r)
                        staging <= (staging << TS_W_SAFE)
                            | {{(BURST_W-TS_W_SAFE){1'b0}}, timestamp_data};
                    else
                        staging <= (staging << SAMPLE_W)
                            | {{(BURST_W-SAMPLE_W){1'b0}}, sample_data};
                end
                if (load_cnt == words_per_scan) begin
                    loading <= 1'b0;
                end else begin
                    rd_off <= rd_off - 1'b1;
                    load_cnt <= load_cnt + 1'b1;
                end
            end
        end
    end

endmodule
