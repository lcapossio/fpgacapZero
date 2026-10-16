// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

// Simulation stub for Intel/Altera sld_virtual_jtag.
// Provides a quiet, inactive TAP for RTL elaboration/lint; the outputs are
// regs so a testbench can drive them.
`timescale 1ns/1ps

module sld_virtual_jtag #(
    parameter sld_auto_instance_index = "NO",
    parameter integer sld_instance_index = 1,
    parameter integer sld_ir_width = 1
) (
    output reg  tck = 1'b0,
    output reg  tdi = 1'b0,
    input  wire tdo,
    output reg  virtual_state_cdr = 1'b0,
    output reg  virtual_state_sdr = 1'b0,
    output reg  virtual_state_udr = 1'b0,
    output reg  [sld_ir_width-1:0] ir_in = {sld_ir_width{1'b0}},
    input  wire [sld_ir_width-1:0] ir_out,
    output reg  jtag_state_tlr = 1'b0
);
    // Outputs stay de-asserted unless a testbench drives them.
    wire unused = tdo | ^ir_out;
endmodule
