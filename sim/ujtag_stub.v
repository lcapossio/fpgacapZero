// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

// Simulation stub for Microchip / Microsemi UJTAG primitive.
// Provides a quiet, inactive TAP — enough for iverilog elaboration/lint
// of the PolarFire / PolarFire SoC / SmartFusion2 / IGLOO2 wrappers.
`timescale 1ns/1ps

module UJTAG (
    output reg UIREG0 = 0,
    output reg UIREG1 = 0,
    output reg UIREG2 = 0,
    output reg UIREG3 = 0,
    output reg UIREG4 = 0,
    output reg UIREG5 = 0,
    output reg UIREG6 = 0,
    output reg UIREG7 = 0,
    output reg UTDI   = 0,
    output reg UDRCK  = 0,
    output reg UDRCAP = 0,
    output reg UDRSH  = 0,
    output reg UDRUPD = 0,
    output reg URSTB  = 1,
    input      UTDO
);
    // synthesis translate_off
    // All outputs remain de-asserted in simulation.
    // synthesis translate_on
endmodule
