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
    parameter DEPTH    = 1024,
    parameter BURST_W  = 256
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
    input  wire [SAMPLE_W-1:0]      mem_data,

    // Control (tck domain, from ila_core via reg bus)
    input  wire                      burst_start,
    input  wire [$clog2(DEPTH)-1:0]  burst_ptr_in
);

    localparam PTR_W = $clog2(DEPTH);
    localparam SAMPLES_PER_SCAN = BURST_W / SAMPLE_W;
    localparam LOAD_CTR_W = $clog2(SAMPLES_PER_SCAN + 1);

    reg [BURST_W-1:0] sr;
    reg [BURST_W-1:0] staging;
    reg [PTR_W-1:0]   rd_ptr;
    reg [LOAD_CTR_W-1:0] load_cnt;
    reg loading;

    assign tdo      = sr[0];
    assign mem_addr  = rd_ptr;

    always @(posedge tck or posedge arst) begin
        if (arst) begin
            sr       <= {BURST_W{1'b0}};
            staging  <= {BURST_W{1'b0}};
            rd_ptr   <= {PTR_W{1'b0}};
            load_cnt <= {LOAD_CTR_W{1'b0}};
            loading  <= 1'b0;
        end else begin

            // Burst start: set read pointer and begin first staging fill
            if (burst_start) begin
                rd_ptr   <= burst_ptr_in;
                load_cnt <= {LOAD_CTR_W{1'b0}};
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

            // Staging buffer fill: read one sample per cycle from memory
            // mem_data is available 1 cycle after rd_ptr is set
            if (loading) begin
                if (load_cnt > 0) begin
                    staging[(load_cnt - 1) * SAMPLE_W +: SAMPLE_W] <= mem_data;
                end
                if (load_cnt == SAMPLES_PER_SCAN) begin
                    staging[(load_cnt - 1) * SAMPLE_W +: SAMPLE_W] <= mem_data;
                    loading <= 1'b0;
                end else begin
                    rd_ptr   <= rd_ptr + 1'b1;
                    load_cnt <= load_cnt + 1'b1;
                end
            end
        end
    end

endmodule
