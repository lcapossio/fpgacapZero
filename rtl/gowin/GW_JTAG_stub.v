// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Synthesis black-box declaration for the Gowin GW_JTAG primitive.
//
// Gowin EDA generates an equivalent declaration when GAO is used.  Include
// this file in non-GAO builds so synthesis can elaborate the primitive and
// let place-and-route bind it to the device JTAG resource.
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
) /* synthesis syn_black_box */;
endmodule
