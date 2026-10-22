// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
//
// Arty A7 design with no fcapz RTL in it.  The signals to capture carry
// mark_debug; build.tcl inserts the ELA into the synthesized netlist.

`timescale 1ns/1ps
`default_nettype none

module insert_demo_top (
    input  wire       clk,
    output wire [3:0] led
);
    (* mark_debug = "true" *) reg [7:0]  count = 8'd0;
    (* mark_debug = "true" *) reg [15:0] lfsr  = 16'hACE1;

    always @(posedge clk) begin
        count <= count + 8'd1;
        lfsr  <= {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
    end

    // A bus inside a submodule whose bits do not start at 0: it reaches the
    // .prob as "u_gen/triple", 8 bits wide.
    insert_demo_gen u_gen (.clk(clk), .count(count));

    reg [26:0] blink = 27'd0;
    always @(posedge clk) blink <= blink + 27'd1;

    assign led = {blink[26], lfsr[0], count[7], blink[25]};
endmodule

module insert_demo_gen (
    input wire       clk,
    input wire [7:0] count
);
    (* mark_debug = "true" *) reg [11:4] triple = 8'd0;

    always @(posedge clk) triple <= count * 8'd3;
endmodule

`default_nettype wire
