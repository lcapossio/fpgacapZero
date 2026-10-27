// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Lattice ECP5 JTAG TAP wrapper (JTAGG).
// Presents the standard fpgacapZero TAP interface.
//
// ECP5 has a single user DR (ER1/ER2). CHAIN selects which:
//   CHAIN=1 → ER1 (accessed via IR=0x32)
//   CHAIN=2 → ER2 (accessed via IR=0x38)

module jtag_tap_ecp5 #(
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

    wire jtck, jtdi;
    wire jshift, jupdate, jce1, jce2;
    wire jrti1, jrti2;
    wire jrstn;

    JTAGG u_jtagg (
        .JTCK    (jtck),
        .JTDI    (jtdi),
        .JTDO1   (CHAIN == 1 ? tdo : 1'b0),
        .JTDO2   (CHAIN == 2 ? tdo : 1'b0),
        .JSHIFT  (jshift),
        .JUPDATE (jupdate),
        .JRSTN   (jrstn),
        .JCE1    (jce1),
        .JCE2    (jce2),
        .JRTI1   (jrti1),
        .JRTI2   (jrti2)
    );

    // JCE<n> is high in Capture-DR and Shift-DR of the chain's instruction
    // only, so it is low again by Update-DR, where the register and pipe
    // adapters act only while sel is high.  Hold "this DR scan is ours" from
    // Capture-DR to Update-DR and select JUPDATE with it; the Update-DR of
    // another instruction's scan stays unselected.  JRSTN is low in
    // Test-Logic-Reset.
    wire ce = (CHAIN == 1) ? jce1 : jce2;
    reg  scan_ours;
    initial scan_ours = 1'b0;
    always @(posedge jtck) begin
        if (!jrstn || jupdate)
            scan_ours <= 1'b0;
        else if (ce)
            scan_ours <= 1'b1;
    end

    assign tck     = jtck;
    assign tdi     = jtdi;
    assign shift   = jshift;
    assign update  = jupdate;
    assign sel     = ce | (jupdate & scan_ours);
    // ECP5 doesn't have a dedicated CAPTURE output; derive from
    // CE rising edge when not shifting (CE asserts at CAPTURE-DR
    // and remains through SHIFT-DR).
    reg ce_prev;
    always @(posedge jtck) ce_prev <= ce;
    assign capture = ce & ~ce_prev & ~jshift;

endmodule
