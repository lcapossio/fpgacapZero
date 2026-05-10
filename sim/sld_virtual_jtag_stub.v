// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

// Simulation stub for Intel/Altera sld_virtual_jtag.
// Provides a quiet, inactive TAP for RTL elaboration/lint.
`timescale 1ns/1ps

module sld_virtual_jtag #(
    parameter sld_auto_instance_index = "NO",
    parameter integer sld_instance_index = 1,
    parameter integer sld_ir_width = 1
) (
    output wire tck,
    output wire tdi,
    input  wire tdo,
    output wire virtual_state_cdr,
    output wire virtual_state_sdr,
    output wire virtual_state_udr,
    output wire [sld_ir_width-1:0] ir_in,
    input  wire [sld_ir_width-1:0] ir_out
);
    assign tck = 1'b0;
    assign tdi = 1'b0;
    assign virtual_state_cdr = 1'b0;
    assign virtual_state_sdr = 1'b0;
    assign virtual_state_udr = 1'b0;
    assign ir_in = {sld_ir_width{1'b0}};

    wire unused = tdo | ^ir_out;
endmodule
