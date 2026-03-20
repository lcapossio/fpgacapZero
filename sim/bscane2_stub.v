// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

// Simulation stub for Xilinx BSCANE2 primitive.
// Provides a quiet, inactive TAP — enough for iverilog elaboration/lint.
`timescale 1ns/1ps

module BSCANE2 #(
    parameter integer JTAG_CHAIN = 1
) (
    output reg TCK     = 0,
    output reg TDI     = 0,
    input      TDO,
    output reg CAPTURE = 0,
    output reg SHIFT   = 0,
    output reg UPDATE  = 0,
    output reg SEL     = 0,
    output reg DRCK    = 0,
    output reg RUNTEST = 0,
    output reg RESET   = 0
);
    // synthesis translate_off
    // All outputs remain de-asserted in simulation.
    // synthesis translate_on
endmodule
