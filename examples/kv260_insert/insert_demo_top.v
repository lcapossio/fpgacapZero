// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
//
// KV260 (Zynq UltraScale+) design with no fcapz RTL in it.  build.tcl
// inserts the debug cores into the synthesized netlist, as for the Arty A7
// demo in examples/arty_a7_insert (same signals, minus the switches):
//
//   ELA on clk (pl_clk0):          count, lfsr, tick, u_gen/triple, ctrl_q
//   ELA on clk_div (pl_clk0 / 3):  slow_count, slow_lfsr
//   EIO in:  ctrl_q, armed_flag     EIO out: ctrl
//   tick triggers the clk_div ELA; that ELA's trigger starts the clk one;
//   the clk ELA's armed level drives armed_flag.
//
// The KV260 has no PL oscillator: pl_clk0 comes from the PS at whatever
// rate the boot firmware set (see examples/kv260/README.md).  The design
// has no PL I/O; mark_debug and dont_touch keep its logic in the netlist.

`timescale 1ns/1ps
`default_nettype none

module insert_demo_top;
    wire clk, clk_div;
    kv260_ps_wrapper u_ps (.pl_clk0(clk));
    BUFGCE_DIV #(.BUFGCE_DIVIDE(3)) u_div (
        .I(clk), .CE(1'b1), .CLR(1'b0), .O(clk_div)
    );

    // ---- pl_clk0 domain ----------------------------------------------------
    (* mark_debug = "true" *) reg [7:0]  count = 8'd0;
    (* mark_debug = "true" *) reg [15:0] lfsr  = 16'hACE1;
    // 8 cycles in 256: it triggers the clk_div ELA, which samples it as a
    // level every 3 clk cycles, so it must outlast two of those.
    (* mark_debug = "true" *) reg        tick  = 1'b0;

    always @(posedge clk) begin
        count <= count + 8'd1;
        lfsr  <= {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        tick  <= (count[7:3] == 5'h1F);   // count 0xF8..0xFF, one cycle late
    end

    insert_demo_gen u_gen (.clk(clk), .count(count));

    // Placeholders the debug cores drive (EIO out, the ELA's armed level).
    (* dont_touch = "true" *) reg [3:0] ctrl       = 4'd0;
    (* dont_touch = "true" *) reg       armed_flag = 1'b0;
    always @(posedge clk) begin
        ctrl       <= 4'd0;
        armed_flag <= 1'b0;
    end

    // EIO outputs come in the JTAG clock: two flops into this one.
    (* ASYNC_REG = "TRUE" *) reg [3:0] ctrl_meta = 4'd0;
    (* mark_debug = "true", dont_touch = "true" *) reg [3:0] ctrl_q = 4'd0;
    always @(posedge clk) begin
        ctrl_meta <= ctrl;
        ctrl_q    <= ctrl_meta;
    end

    // ---- clk_div domain ----------------------------------------------------
    (* mark_debug = "true" *) reg [7:0]  slow_count = 8'd0;
    (* mark_debug = "true" *) reg [15:0] slow_lfsr  = 16'h1D0F;
    always @(posedge clk_div) begin
        slow_count <= slow_count + 8'd1;
        slow_lfsr  <= {slow_lfsr[14:0],
                       slow_lfsr[15] ^ slow_lfsr[13] ^ slow_lfsr[12] ^ slow_lfsr[10]};
    end
endmodule

module insert_demo_gen (
    input wire       clk,
    input wire [7:0] count
);
    (* mark_debug = "true" *) reg [11:4] triple = 8'd0;

    always @(posedge clk) triple <= count * 8'd3;
endmodule

`default_nettype wire
