// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

// Simulation stub for the Microchip PolarFire / PolarFire SoC UJTAG primitive.
// Port list matches Libero's polarfire/comps.v.  Provides a quiet, inactive
// TAP — enough for iverilog elaboration/lint of the PolarFire wrappers.
`timescale 1ns/1ps

module UJTAG (
    input            TCK,
    input            TMS,
    input            TDI,
    input            TRSTB,
    output           TDO,
    output reg [7:0] UIREG  = 8'h00,
    output reg       UTDI   = 1'b0,
    output reg       UDRCK  = 1'b0,
    output reg       UDRCAP = 1'b0,
    output reg       UDRSH  = 1'b0,
    output reg       UDRUPD = 1'b0,
    output reg       URSTB  = 1'b1,
    input            UTDO
);
    // All user-side outputs remain de-asserted in simulation.
    assign TDO = 1'b0;
endmodule
