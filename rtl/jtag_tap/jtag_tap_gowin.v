// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Gowin JTAG TAP wrapper.
// Presents the standard fpgacapZero TAP interface.
//
// Gowin GW1N/GW2A devices provide a JTAG primitive with up to 4
// user DR chains (similar to Xilinx BSCANE2).  CHAIN selects which
// user register (1-4).

module jtag_tap_gowin #(
    parameter CHAIN = 1
) (
    output wire tck,
    output wire tdi,
    input  wire tdo,
    output wire capture,
    output wire shift,
    output wire update,
    output wire sel
);

    wire jtck, jtdi, jrti, jshift, jupdate, jce;
    wire jrstn;

    JTAG u_jtag (
        .JTCK    (jtck),
        .JTDI    (jtdi),
        .JTDO    (tdo),
        .JSHIFT  (jshift),
        .JUPDATE (jupdate),
        .JRSTN   (jrstn),
        .JCE     (jce),
        .JRTI    (jrti)
    );

    // Note: Gowin's JTAG primitive supports a single user DR.
    // For multi-chain, the user logic must decode the instruction
    // register (not exposed here for simplicity).  CHAIN > 1 would
    // require a custom IR decode layer.

    assign tck     = jtck;
    assign tdi     = jtdi;
    assign shift   = jshift;
    assign update  = jupdate;
    assign sel     = jce;

    // Derive CAPTURE from CE edge (same approach as ECP5)
    reg sel_prev;
    always @(posedge jtck) sel_prev <= sel;
    assign capture = sel & ~sel_prev & ~jshift;

endmodule
