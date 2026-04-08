// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero EIO wrapper for Xilinx UltraScale / UltraScale+.
//
// Thin shim over fcapz_eio_xilinx7 -- BSCANE2 is the same primitive on
// 7-series, UltraScale, and UltraScale+, so there is no point in
// duplicating the wrapper internals.  See jtag_tap_xilinxus.v for the
// list of confirmed device families.
//
// Usage:
//   fcapz_eio_xilinxus #(.IN_W(32), .OUT_W(32)) u_eio (
//       .probe_in(fabric_signals), .probe_out(driven_signals)
//   );

module fcapz_eio_xilinxus #(
    parameter IN_W  = 32,
    parameter OUT_W = 32,
    parameter CHAIN = 3
) (
    input  wire [IN_W-1:0]  probe_in,
    output wire [OUT_W-1:0] probe_out
);

    fcapz_eio_xilinx7 #(
        .IN_W(IN_W), .OUT_W(OUT_W), .CHAIN(CHAIN)
    ) u_inner (
        .probe_in(probe_in), .probe_out(probe_out)
    );

endmodule
