// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Burst data readout interface (vendor-agnostic).
//
// TAP signals are provided by an external vendor-specific wrapper.
// Provides a wide DR (256-bit default) that packs multiple samples
// per scan, reducing the number of JTAG scans by 8-32x.
//
// Protocol:
//   1. Host writes BURST_PTR via the control interface.
//   2. Host selects this TAP and performs DR scans.
//   3. Each CAPTURE loads SAMPLES_PER_SCAN samples from the buffer.
//   4. Each SHIFT outputs BURST_W bits of packed sample data (LSB first).
//   5. Read pointer auto-increments after each scan.
//
// Timing: the staging buffer is pre-loaded during the SHIFT phase of
// the current scan, so data is ready before the next CAPTURE.

module jtag_burst_read #(
    parameter SAMPLE_W = 8,
    parameter TIMESTAMP_W = 0,
    parameter DEPTH    = 1024,
    parameter BURST_W  = 256,
    // Ring depth for read pointer (DEPTH when one segment; DEPTH/NUM_SEGMENTS when split)
    parameter SEG_DEPTH = DEPTH
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

    // Dual-port memory read (tck domain)
    output wire [$clog2(DEPTH)-1:0] mem_addr,
    input  wire [SAMPLE_W-1:0]      sample_data,
    input  wire [((TIMESTAMP_W > 0) ? TIMESTAMP_W : 1)-1:0] timestamp_data,

    // Control (tck domain, from ila_core via reg bus)
    input  wire                      burst_start,
    input  wire                      burst_timestamp,
    input  wire [$clog2(DEPTH)-1:0]  burst_ptr_in
);

    localparam PTR_W = $clog2(DEPTH);
    localparam SEG_PTR_W = $clog2(SEG_DEPTH);
    localparam SAMPLES_PER_SCAN = BURST_W / SAMPLE_W;
    localparam TS_W_SAFE = (TIMESTAMP_W > 0) ? TIMESTAMP_W : 1;
    localparam TS_PER_SCAN = BURST_W / TS_W_SAFE;
    localparam MAX_PER_SCAN = (SAMPLES_PER_SCAN > TS_PER_SCAN) ? SAMPLES_PER_SCAN : TS_PER_SCAN;
    localparam LOAD_CTR_W = $clog2(MAX_PER_SCAN + 1);
    localparam [LOAD_CTR_W-1:0] SAMPLES_PER_SCAN_C = SAMPLES_PER_SCAN;
    localparam [LOAD_CTR_W-1:0] TS_PER_SCAN_C = TS_PER_SCAN;

    // Static assert: SEG_DEPTH must be a power-of-two
    generate
        if (SEG_DEPTH != 0 && (SEG_DEPTH & (SEG_DEPTH - 1)) != 0) begin : g_bad_seg_depth
            SEG_DEPTH_must_be_power_of_two invalid();
        end
    endgenerate

    reg [BURST_W-1:0] sr;
    reg [BURST_W-1:0] staging;
    reg [PTR_W-1:0]   rd_ptr;
    reg [PTR_W-1:0]   burst_seg_base;
    reg [LOAD_CTR_W-1:0] load_cnt;
    reg burst_timestamp_r;
    reg loading;
    wire [LOAD_CTR_W-1:0] words_per_scan =
        burst_timestamp_r ? TS_PER_SCAN_C : SAMPLES_PER_SCAN_C;
    wire [BURST_W-1:0] load_word = burst_timestamp_r
        ? {{(BURST_W-TS_W_SAFE){1'b0}}, timestamp_data}
        : {{(BURST_W-SAMPLE_W){1'b0}}, sample_data};
    wire [LOAD_CTR_W-1:0] store_slot = load_cnt - 1'b1;

    // Segment base address derived from burst_ptr_in (generate avoids zero-width slice)
    wire [PTR_W-1:0] seg_base_of_ptr;
    generate
        if (SEG_DEPTH >= DEPTH) begin : g_seg_base_flat
            assign seg_base_of_ptr = {PTR_W{1'b0}};
        end else begin : g_seg_base_split
            assign seg_base_of_ptr = {burst_ptr_in[PTR_W-1:SEG_PTR_W], {SEG_PTR_W{1'b0}}};
        end
    endgenerate

    assign tdo      = sr[0];
    assign mem_addr  = rd_ptr;

    always @(posedge tck or posedge arst) begin
        if (arst) begin
            sr       <= {BURST_W{1'b0}};
            staging  <= {BURST_W{1'b0}};
            rd_ptr   <= {PTR_W{1'b0}};
            burst_seg_base <= {PTR_W{1'b0}};
            load_cnt <= {LOAD_CTR_W{1'b0}};
            burst_timestamp_r <= 1'b0;
            loading  <= 1'b0;
        end else begin

            // Burst start: set read pointer and begin first staging fill
            if (burst_start) begin
                rd_ptr   <= burst_ptr_in;
                burst_seg_base <= seg_base_of_ptr;
                load_cnt <= {LOAD_CTR_W{1'b0}};
                burst_timestamp_r <= burst_timestamp;
                loading  <= 1'b1;
            end

            if (sel) begin
                if (capture) begin
                    // Load shift register from staging buffer
                    sr <= staging;
                    // Start filling staging for next scan
                    load_cnt <= {LOAD_CTR_W{1'b0}};
                    loading  <= 1'b1;
                end else if (shift_en) begin
                    sr <= {tdi, sr[BURST_W-1:1]};
                end
            end

            // Staging buffer fill: read one word per cycle from memory.
            // memory data is available 1 cycle after rd_ptr is set
            if (loading) begin
                if (load_cnt > 0) begin
                    if (burst_timestamp_r)
                        staging[store_slot * TS_W_SAFE +: TS_W_SAFE] <= load_word[TS_W_SAFE-1:0];
                    else
                        staging[store_slot * SAMPLE_W +: SAMPLE_W] <= load_word[SAMPLE_W-1:0];
                end
                if (load_cnt == words_per_scan) begin
                    loading <= 1'b0;
                end else begin
                    // Wrap within segment (bitmask; SEG_DEPTH is power-of-two).
                    rd_ptr <= burst_seg_base
                        + ((rd_ptr - burst_seg_base + 1'b1) & (SEG_DEPTH - 1));
                    load_cnt <= load_cnt + 1'b1;
                end
            end
        end
    end

endmodule
