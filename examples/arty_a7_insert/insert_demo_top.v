// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
//
// Arty A7 design with no fcapz RTL in it.  build.tcl inserts the debug
// cores into the synthesized netlist:
//
//   ELA on clk_IBUF_BUFG (100 MHz): count, lfsr, tick, u_gen/triple,
//                                   ctrl_q                (mark_debug)
//   ELA on clk_slow (62.5 MHz):     slow_count, slow_lfsr (mark_debug)
//   EIO in:  sw_q, ctrl_q, armed_flag     EIO out: ctrl
//   tick triggers the 62.5 MHz ELA; that ELA's trigger starts the 100 MHz
//   one; the 100 MHz ELA's armed level drives armed_flag.
//
// ctrl and armed_flag are placeholders: registers that hold 0, kept with
// dont_touch so they reach the netlist, whose drivers the insertion
// replaces.  ctrl_q registers ctrl back into the design, so the host can
// read back what it wrote.

`timescale 1ns/1ps
`default_nettype none

module insert_demo_top (
    input  wire       clk,
    input  wire [3:0] sw,
    output wire [3:0] led
);
    // ---- 100 MHz domain ----------------------------------------------------
    (* mark_debug = "true" *) reg [7:0]  count = 8'd0;
    (* mark_debug = "true" *) reg [15:0] lfsr  = 16'hACE1;
    // 4 cycles in 256, as count wraps.  It triggers the 62.5 MHz ELA, which
    // samples it as a level in its own clock: high for longer than two of
    // its cycles, or a pulse can fall between them.
    (* mark_debug = "true" *) reg        tick  = 1'b0;

    always @(posedge clk) begin
        count <= count + 8'd1;
        lfsr  <= {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        tick  <= (count[7:2] == 6'h3F);   // count 0xFC..0xFF, one cycle late
    end

    // A bus inside a submodule whose bits do not start at 0: it reaches the
    // .prob as "u_gen/triple", 8 bits wide.
    insert_demo_gen u_gen (.clk(clk), .count(count));

    // Placeholders the debug cores drive (EIO out, the ELA's armed level).
    (* dont_touch = "true" *) reg [3:0] ctrl       = 4'd0;
    (* dont_touch = "true" *) reg       armed_flag = 1'b0;
    always @(posedge clk) begin
        ctrl       <= 4'd0;
        armed_flag <= 1'b0;
    end

    // EIO outputs come in the JTAG clock: two flops into this one (the
    // value is static while it is read), then captured and read back.
    (* ASYNC_REG = "TRUE" *) reg [3:0] ctrl_meta = 4'd0;
    (* mark_debug = "true", dont_touch = "true" *) reg [3:0] ctrl_q = 4'd0;
    (* dont_touch = "true" *) reg [3:0] sw_q = 4'd0;
    always @(posedge clk) begin
        ctrl_meta <= ctrl;
        ctrl_q    <= ctrl_meta;
        sw_q      <= sw;
    end

    // ---- 62.5 MHz domain ---------------------------------------------------
    wire clk_fb, clk_slow_unbuf, clk_slow;
    MMCME2_BASE #(
        .CLKIN1_PERIOD(10.0),
        .CLKFBOUT_MULT_F(10.0),     // VCO 1000 MHz
        .CLKOUT0_DIVIDE_F(16.0)     // 62.5 MHz
    ) u_mmcm (
        .CLKIN1(clk), .CLKFBIN(clk_fb), .CLKFBOUT(clk_fb),
        .CLKOUT0(clk_slow_unbuf), .RST(1'b0), .PWRDWN(1'b0),
        .LOCKED(), .CLKOUT0B(), .CLKOUT1(), .CLKOUT1B(), .CLKOUT2(),
        .CLKOUT2B(), .CLKOUT3(), .CLKOUT3B(), .CLKOUT4(), .CLKOUT5(),
        .CLKOUT6(), .CLKFBOUTB()
    );
    BUFG u_bufg_slow (.I(clk_slow_unbuf), .O(clk_slow));

    (* mark_debug = "true" *) reg [7:0]  slow_count = 8'd0;
    (* mark_debug = "true" *) reg [15:0] slow_lfsr  = 16'h1D0F;
    always @(posedge clk_slow) begin
        slow_count <= slow_count + 8'd1;
        slow_lfsr  <= {slow_lfsr[14:0],
                       slow_lfsr[15] ^ slow_lfsr[13] ^ slow_lfsr[12] ^ slow_lfsr[10]};
    end

    assign led = {ctrl_q[1:0], armed_flag, slow_count[7]};
endmodule

module insert_demo_gen (
    input wire       clk,
    input wire [7:0] count
);
    (* mark_debug = "true" *) reg [11:4] triple = 8'd0;

    always @(posedge clk) triple <= count * 8'd3;
endmodule

`default_nettype wire
