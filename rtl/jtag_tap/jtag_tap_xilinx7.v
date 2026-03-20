// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Xilinx 7-series JTAG TAP wrapper (BSCANE2).
// Presents the standard fpgacapZero TAP interface.
//
// Verified IR codes on xc7a100t (Arty A7):
//   CHAIN=1 → USER1 (IR=0x02)
//   CHAIN=2 → USER2 (IR=0x03)
//   CHAIN=3 → USER3 (IR=0x22)
//   CHAIN=4 → USER4 (IR=0x23)

module jtag_tap_xilinx7 #(
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

    BSCANE2 #(.JTAG_CHAIN(CHAIN)) u_bscan (
        .TCK     (tck),
        .TDI     (tdi),
        .TDO     (tdo),
        .CAPTURE (capture),
        .SHIFT   (shift),
        .UPDATE  (update),
        .SEL     (sel),
        .DRCK    (),
        .RUNTEST (),
        .RESET   ()
    );

endmodule
