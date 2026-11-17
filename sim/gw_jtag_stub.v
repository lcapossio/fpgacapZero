// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

// Simulation stub for Gowin GW_JTAG primitive.
// Provides a quiet, inactive TAP for iverilog elaboration/lint; the outputs
// are regs so a cocotb bench can drive them.
`timescale 1ns/1ps

module GW_JTAG (
    input  wire tck_pad_i,
    input  wire tms_pad_i,
    input  wire tdi_pad_i,
    output wire tdo_pad_o,
    output reg  tck_o                 = 1'b0,
    output reg  tdi_o                 = 1'b0,
    output reg  test_logic_reset_o    = 1'b0,
    output reg  run_test_idle_er1_o   = 1'b0,
    output reg  run_test_idle_er2_o   = 1'b0,
    output reg  shift_dr_capture_dr_o = 1'b0,
    output reg  pause_dr_o            = 1'b0,
    output reg  update_dr_o           = 1'b0,
    output reg  enable_er1_o          = 1'b0,
    output reg  enable_er2_o          = 1'b0,
    input  wire tdo_er1_i,
    input  wire tdo_er2_i
);
    // Outputs stay de-asserted unless a testbench drives them.
    assign tdo_pad_o = 1'b0;
    wire unused = tdo_er1_i | tdo_er2_i | tck_pad_i | tms_pad_i | tdi_pad_i;
endmodule
