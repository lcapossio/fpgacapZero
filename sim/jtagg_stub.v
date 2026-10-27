// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

// Simulation stub for Lattice ECP5 JTAGG primitive.
// Provides a quiet, inactive TAP for RTL elaboration/lint; the outputs are
// regs so a cocotb bench can drive them.
`timescale 1ns/1ps

module JTAGG (
    output reg  JTCK    = 1'b0,
    output reg  JTDI    = 1'b0,
    input  wire JTDO1,
    input  wire JTDO2,
    output reg  JSHIFT  = 1'b0,
    output reg  JUPDATE = 1'b0,
    output reg  JRSTN   = 1'b1,
    output reg  JCE1    = 1'b0,
    output reg  JCE2    = 1'b0,
    output reg  JRTI1   = 1'b0,
    output reg  JRTI2   = 1'b0
);
    // Outputs stay de-asserted unless a testbench drives them.
    wire unused = JTDO1 | JTDO2;
endmodule
