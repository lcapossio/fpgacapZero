// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero EIO wrapper for Gowin GW1N / GW2A (standalone).
//
// WARNING: Gowin has limited user JTAG chains.  This standalone EIO
// wrapper defaults to ER1 and CANNOT coexist with fcapz_ela_gowin on
// the same chain.
// To use ELA + EIO together on Gowin, set EIO_EN=1 on the
// fcapz_ela_gowin wrapper instead.
//
// This standalone wrapper is temporarily disabled while the Gowin TAP wrapper
// is being reworked. Use fcapz_ela_gowin with EIO_EN=1 for Gowin ELA+EIO.

module fcapz_eio_gowin #(
    parameter IN_W  = 32,
    parameter OUT_W = 32,
    parameter CHAIN = 1    // Gowin ER1 by default (ER2 with CHAIN=2)
) (
    input  wire [IN_W-1:0]  probe_in,
    output wire [OUT_W-1:0] probe_out
);

    assign probe_out = {OUT_W{1'b0}};

    wire unused = &{1'b0, probe_in};

endmodule
