// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Intel/Altera JTAG TAP wrapper (sld_virtual_jtag).
// Presents the standard fpgacapZero TAP interface.
//
// Each instance gets its own virtual IR index. CHAIN parameter maps
// to sld_instance_index (1-based).

module jtag_tap_intel #(
    parameter CHAIN = 1
) (
    output wire tck,
    output wire tdi,
    input  wire tdo,
    output wire capture,
    output wire shift,
    output wire update,
    output wire sel
);

    wire virtual_state_cdr;
    wire virtual_state_sdr;
    wire virtual_state_udr;

    sld_virtual_jtag #(
        .sld_auto_instance_index ("NO"),
        .sld_instance_index      (CHAIN),
        .sld_ir_width             (1)
    ) u_vjtag (
        .tck                (tck),
        .tdi                (tdi),
        .tdo                (tdo),
        .virtual_state_cdr  (virtual_state_cdr),
        .virtual_state_sdr  (virtual_state_sdr),
        .virtual_state_udr  (virtual_state_udr),
        .ir_in              (),
        .ir_out             (1'b0)
    );

    assign capture = virtual_state_cdr;
    assign shift   = virtual_state_sdr;
    assign update  = virtual_state_udr;
    // sld_virtual_jtag always selected when its IR matches
    assign sel     = 1'b1;

endmodule
