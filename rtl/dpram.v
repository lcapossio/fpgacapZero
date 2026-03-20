// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// True dual-port RAM with independent clocks.
// Infers BRAM on Xilinx, Lattice, Intel, Gowin when DEPTH × WIDTH
// exceeds the distributed RAM threshold.
//
// Port A: read + write (sample_clk domain)
// Port B: read-only    (jtag_clk domain)

module dpram #(
    parameter WIDTH = 8,
    parameter DEPTH = 1024
) (
    // Port A (read/write)
    input  wire                     clk_a,
    input  wire                     we_a,
    input  wire [$clog2(DEPTH)-1:0] addr_a,
    input  wire [WIDTH-1:0]         din_a,
    output reg  [WIDTH-1:0]         dout_a,

    // Port B (read-only)
    input  wire                     clk_b,
    input  wire [$clog2(DEPTH)-1:0] addr_b,
    output reg  [WIDTH-1:0]         dout_b
);

    (* ram_style = "auto" *)
    reg [WIDTH-1:0] mem [0:DEPTH-1];

    // Port A: write-first read
    always @(posedge clk_a) begin
        if (we_a)
            mem[addr_a] <= din_a;
        dout_a <= mem[addr_a];
    end

    // Port B: read-only
    always @(posedge clk_b) begin
        dout_b <= mem[addr_b];
    end

endmodule
