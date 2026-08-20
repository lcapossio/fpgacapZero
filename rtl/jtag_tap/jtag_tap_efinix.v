// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Efinix Trion / Titanium JTAG User TAP adapter.
// Presents the standard fpgacapZero TAP interface.
//
// Unlike Xilinx BSCANE2 or Intel sld_virtual_jtag, the Efinix JTAG User TAP
// is NOT an RTL-instantiable primitive: it is added as a block in the Efinity
// Interface Designer, which surfaces its signals as top-level ports of the
// design (o_jtag_userN_* / i_jtag_userN_tdo). This module is therefore a thin
// name-mapping adapter, not a primitive wrapper -- the caller
// (fcapz_ela_efinix) exposes the User TAP signals as ports and wires them to
// the Interface Designer block at the top level.
//
// A Trion device has TWO hard JTAG User TAP blocks (USER1, USER2). Add one
// block per fcapz chain: USER1 carries the control register, USER2 the burst
// data. See the Trion Interfaces User Guide (JTAG User TAP) for the block's
// signal names and the JTAG Core User Guide (Figure 1) for the port set.
//
// Signal mapping (Efinix -> fcapz), mirroring the Xilinx/Intel wrappers:
//   user_tck      -> tck       free-running JTAG clock (runs through all
//                              TAP states; the shift/capture/update strobes
//                              below are qualified against it, exactly as
//                              TCK is on BSCANE2)
//   user_tdi      -> tdi       data shifted in from the host
//   tdo           -> user_tdo  data shifted back out to the host
//   user_capture  -> capture   Capture-DR strobe
//   user_shift    -> shift     Shift-DR strobe
//   user_update   -> update    Update-DR strobe
//   user_sel      -> sel        this User TAP's instruction is selected
//
// The block also provides a gated DR clock (o_jtag_userN_drck) and reset /
// runtest strobes; fcapz clocks on the free-running user_tck (like BSCANE2's
// TCK) and does not use them. user_drck is accepted as a port so top-level
// wiring can connect the full block, but it is intentionally left unused.
//
// Hardware-validation checkpoint (Trion T20): confirm that user_tck is
// presented free-running to fabric and that capture/update pulse against it
// as on Xilinx; if a given Efinity build only routes the gated user_drck,
// drive tck from user_drck instead.

module jtag_tap_efinix (
    // Efinix JTAG User TAP block signals (from the Interface Designer)
    input  wire user_tck,
    input  wire user_drck,   // gated DR clock -- unused (see note above)
    input  wire user_tdi,
    output wire user_tdo,
    input  wire user_capture,
    input  wire user_shift,
    input  wire user_update,
    input  wire user_sel,

    // fpgacapZero TAP interface
    output wire tck,
    output wire tdi,
    input  wire tdo,
    output wire capture,
    output wire shift,
    output wire update,
    output wire sel
);

    // Keep user_drck in the sensitivity of the design without driving logic;
    // an explicit unused tie keeps lint quiet about the accepted-but-unused
    // gated clock.
    wire _unused_drck = user_drck;

    assign tck      = user_tck;
    assign tdi      = user_tdi;
    assign capture  = user_capture;
    assign shift    = user_shift;
    assign update   = user_update;
    assign sel      = user_sel;

    assign user_tdo = tdo;

endmodule
