// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - www.bard0.com - <hello@bard0.com>
`timescale 1ns/1ps
// The debug block tools/fcapz_insert_vivado.tcl adds to a synthesized
// netlist: fcapz_debug_multi (ELAs, then one optional EIO, behind the core
// manager on one USER chain), plus the cross-triggers between its ELAs.
//
// Each ELA samples its own clock.  A cross-trigger carries one ELA's
// trigger_out pulse (one cycle of its clock) to another ELA's trigger_in:
// it flips a toggle in the source clock, the destination clock
// synchronizes the toggle and turns each change back into a one-cycle
// pulse, so no pulse is lost whichever clock is faster.  Two triggers
// closer than about three destination cycles count as one.
module fcapz_insert_wrap #(
    parameter NUM_ELAS = 1,
    // Probe bits per ELA slot in ela_probe_in: the widest ELA.
    parameter SAMPLE_W = 8,
    // The deepest ELA.
    parameter DEPTH = 1024,
    // Per ELA, 32 bits each, slot 0 lowest.
    parameter [NUM_ELAS*32-1:0] ELA_SAMPLE_WS = {NUM_ELAS{SAMPLE_W + 32'd0}},
    parameter [NUM_ELAS*32-1:0] ELA_DEPTHS = {NUM_ELAS{DEPTH + 32'd0}},
    parameter [NUM_ELAS*32-1:0] ELA_EXT_TRIG_ENS = {NUM_ELAS{32'd0}},
    // Per destination ELA, 8 bits each: source ELA slot + 1, or 0 for none.
    parameter [NUM_ELAS*8-1:0] XTRIG_SRCS = {NUM_ELAS{8'd0}},
    parameter EIO_EN = 0,
    parameter EIO_IN_W = 1,
    parameter EIO_OUT_W = 1,
    parameter CTRL_CHAIN = 1,
    // 1: UltraScale / UltraScale+ TAP wrapper, 0: 7-series.
    parameter ULTRASCALE = 0
) (
    input  wire [NUM_ELAS-1:0]          ela_sample_clk,
    input  wire [NUM_ELAS*SAMPLE_W-1:0] ela_probe_in,
    input  wire [NUM_ELAS-1:0]          ela_trigger_in,
    output wire [NUM_ELAS-1:0]          ela_trigger_out,
    output wire [NUM_ELAS-1:0]          ela_armed_out,
    input  wire [EIO_IN_W-1:0]          eio_probe_in,
    output wire [EIO_OUT_W-1:0]         eio_probe_out
);
    // ---- Cross-triggers ----------------------------------------------------
    // One toggle per ELA in its own clock, flipped by each trigger_out pulse.
    // Not reset: the destination only looks at changes.
    reg  [NUM_ELAS-1:0] xtrig_toggle = {NUM_ELAS{1'b0}};
    wire [NUM_ELAS-1:0] xtrig_pulse;

    genvar i;
    generate
        for (i = 0; i < NUM_ELAS; i = i + 1) begin : g_xtrig
            always @(posedge ela_sample_clk[i]) begin
                if (ela_trigger_out[i])
                    xtrig_toggle[i] <= ~xtrig_toggle[i];
            end

            localparam integer SRC = XTRIG_SRCS[i*8 +: 8];
            if (SRC == 0) begin : g_none
                assign xtrig_pulse[i] = 1'b0;
            end else begin : g_sync
                fcapz_xtrig_sync u_sync (
                    .clk(ela_sample_clk[i]),
                    .toggle_in(xtrig_toggle[SRC - 1]),
                    .pulse(xtrig_pulse[i])
                );
            end
        end
    endgenerate

    // The ELA synchronizes trigger_in itself: an external input may be in
    // any clock, and the cross-trigger pulse is already in this one.
    wire [NUM_ELAS-1:0] ela_trig = ela_trigger_in | xtrig_pulse;

    // ---- The debug block -----------------------------------------------------
    generate
        if (ULTRASCALE != 0) begin : g_us
            fcapz_debug_multi_xilinxus #(
                .NUM_ELAS(NUM_ELAS), .EIO_EN(EIO_EN), .NUM_EIOS(EIO_EN),
                .SAMPLE_W(SAMPLE_W), .DEPTH(DEPTH), .CTRL_CHAIN(CTRL_CHAIN),
                .EIO_IN_W(EIO_IN_W), .EIO_OUT_W(EIO_OUT_W),
                .ELA_SAMPLE_WS(ELA_SAMPLE_WS), .ELA_DEPTHS(ELA_DEPTHS),
                .ELA_EXT_TRIG_ENS(ELA_EXT_TRIG_ENS)
            ) u_multi (
                .ela_sample_clk(ela_sample_clk),
                .ela_sample_rst({NUM_ELAS{1'b0}}),
                .ela_probe_in(ela_probe_in),
                .ela_trigger_in(ela_trig),
                .ela_trigger_out(ela_trigger_out),
                .ela_armed_out(ela_armed_out),
                .eio_probe_in(eio_probe_in),
                .eio_probe_out(eio_probe_out)
            );
        end else begin : g_7
            fcapz_debug_multi_xilinx7 #(
                .NUM_ELAS(NUM_ELAS), .EIO_EN(EIO_EN), .NUM_EIOS(EIO_EN),
                .SAMPLE_W(SAMPLE_W), .DEPTH(DEPTH), .CTRL_CHAIN(CTRL_CHAIN),
                .EIO_IN_W(EIO_IN_W), .EIO_OUT_W(EIO_OUT_W),
                .ELA_SAMPLE_WS(ELA_SAMPLE_WS), .ELA_DEPTHS(ELA_DEPTHS),
                .ELA_EXT_TRIG_ENS(ELA_EXT_TRIG_ENS)
            ) u_multi (
                .ela_sample_clk(ela_sample_clk),
                .ela_sample_rst({NUM_ELAS{1'b0}}),
                .ela_probe_in(ela_probe_in),
                .ela_trigger_in(ela_trig),
                .ela_trigger_out(ela_trigger_out),
                .ela_armed_out(ela_armed_out),
                .eio_probe_in(eio_probe_in),
                .eio_probe_out(eio_probe_out)
            );
        end
    endgenerate
endmodule

// A toggle from another clock, back to a one-cycle pulse per change.
module fcapz_xtrig_sync (
    input  wire clk,
    input  wire toggle_in,
    output wire pulse
);
    (* ASYNC_REG = "TRUE" *) reg [1:0] xtrig_meta = 2'b00;
    reg last = 1'b0;
    always @(posedge clk) begin
        xtrig_meta <= {xtrig_meta[0], toggle_in};
        last <= xtrig_meta[1];
    end
    assign pulse = xtrig_meta[1] ^ last;
endmodule
