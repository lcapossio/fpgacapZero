// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

// Simulation stub for Lattice ECP5 JTAGG primitive.
// Provides a quiet, inactive TAP for RTL elaboration/lint.
`timescale 1ns/1ps

module JTAGG (
    output wire JTCK,
    output wire JTDI,
    input  wire JTDO1,
    input  wire JTDO2,
    output wire JSHIFT,
    output wire JUPDATE,
    output wire JRSTN,
    output wire JCE1,
    output wire JCE2,
    output wire JRTI1,
    output wire JRTI2
);
    assign JTCK = 1'b0;
    assign JTDI = 1'b0;
    assign JSHIFT = 1'b0;
    assign JUPDATE = 1'b0;
    assign JRSTN = 1'b1;
    assign JCE1 = 1'b0;
    assign JCE2 = 1'b0;
    assign JRTI1 = 1'b0;
    assign JRTI2 = 1'b0;

    wire unused = JTDO1 | JTDO2;
endmodule
