// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

// Simulation stub for Gowin GW_JTAG primitive.
// Provides a quiet, inactive TAP for iverilog elaboration/lint.
`timescale 1ns/1ps

module GW_JTAG (
    output wire tck_o,
    output wire tdi_o,
    output wire test_logic_reset_o,
    output wire run_test_idle_er1_o,
    output wire run_test_idle_er2_o,
    output wire shift_dr_capture_dr_o,
    output wire pause_dr_o,
    output wire update_dr_o,
    output wire enable_er1_o,
    output wire enable_er2_o,
    input  wire tdo_er1_i,
    input  wire tdo_er2_i
);
    assign tck_o = 1'b0;
    assign tdi_o = 1'b0;
    assign test_logic_reset_o = 1'b0;
    assign run_test_idle_er1_o = 1'b0;
    assign run_test_idle_er2_o = 1'b0;
    assign shift_dr_capture_dr_o = 1'b0;
    assign pause_dr_o = 1'b0;
    assign update_dr_o = 1'b0;
    assign enable_er1_o = 1'b0;
    assign enable_er2_o = 1'b0;

    wire unused = tdo_er1_i | tdo_er2_i;
endmodule
