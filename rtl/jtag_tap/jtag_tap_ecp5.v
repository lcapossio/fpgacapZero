// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Lattice ECP5 JTAG TAP wrapper (JTAGG).
// Presents the standard fpgacapZero TAP interface, except that it takes
// tdo_next (the scan's tdo after the next tck edge) instead of tdo.
//
// ECP5 has a single user DR (ER1/ER2). CHAIN selects which:
//   CHAIN=1 → ER1 (accessed via IR=0x32)
//   CHAIN=2 → ER2 (accessed via IR=0x38)
//
// JTAGG timing, which Lattice does not document (LiteX's ECP5JTAG and the
// Hazard3 ECP5 debug module, both used on hardware, rely on it):
//   - JTDI is TDI registered on the rising edge of TCK.
//   - JSHIFT, JUPDATE, JCE1/JCE2 and JRSTN follow the TAP state, which changes
//     on the rising edge.
//   - JTDO1/JTDO2 are registered on the falling edge and drive TDO.
// So the scan logic runs on the falling edge of JTCK (tck = ~JTCK), where
// JTDI and the state outputs have settled for half a period.  At that edge
// JTDI holds the bit taken at the rising edge before, but the state outputs
// already show the state that edge entered; registered once on tck they show
// the state the bit was taken in, which capture/shift/update/sel present.
// The scan logic then advances at the same falling edge where JTAGG samples
// JTDO, so JTDO must already carry the bit it is about to present: tdo_next,
// registered on the rising edge.
module jtag_tap_ecp5 #(
    parameter CHAIN = 1
) (
    output wire tck,
    output wire tdi,
    input  wire tdo_next,
    output wire capture,
    output wire shift,
    output wire update,
    output wire sel
);

    wire jtck, jtdi;
    wire jshift, jupdate, jce1, jce2;
    wire jrti1, jrti2;
    wire jrstn;
    reg  tdo_r;

    JTAGG u_jtagg (
        .JTCK    (jtck),
        .JTDI    (jtdi),
        .JTDO1   (CHAIN == 1 ? tdo_r : 1'b0),
        .JTDO2   (CHAIN == 2 ? tdo_r : 1'b0),
        .JSHIFT  (jshift),
        .JUPDATE (jupdate),
        .JRSTN   (jrstn),
        .JCE1    (jce1),
        .JCE2    (jce2),
        .JRTI1   (jrti1),
        .JRTI2   (jrti2)
    );

    assign tck = ~jtck;
    assign tdi = jtdi;

    // The state each JTDI bit was taken in.  JCE<n> is high in Capture-DR and
    // Shift-DR of the chain's instruction only, so it is low again by
    // Update-DR, where the register and pipe adapters act only while sel is
    // high.  Hold "this DR scan is ours" from Capture-DR to Update-DR and
    // select Update-DR with it; another instruction's Update-DR stays
    // unselected.  JRSTN is low in Test-Logic-Reset.
    wire ce = (CHAIN == 1) ? jce1 : jce2;
    reg  ce_q, shift_q, update_q, rstn_q;
    reg  scan_ours;
    initial begin
        ce_q      = 1'b0;
        shift_q   = 1'b0;
        update_q  = 1'b0;
        rstn_q    = 1'b1;
        scan_ours = 1'b0;
        tdo_r     = 1'b0;
    end

    always @(posedge tck) begin
        ce_q     <= ce;
        shift_q  <= jshift;
        update_q <= jupdate;
        rstn_q   <= jrstn;
        if (!rstn_q || update_q)
            scan_ours <= 1'b0;
        else if (ce_q)
            scan_ours <= 1'b1;
    end

    always @(negedge tck)
        tdo_r <= tdo_next;

    assign shift   = shift_q;
    assign update  = update_q;
    assign capture = ce_q & ~shift_q;
    assign sel     = ce_q | (update_q & scan_ours);

endmodule
