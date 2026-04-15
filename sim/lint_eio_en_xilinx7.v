// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

// Lint-only harness that instantiates fcapz_ela_xilinx7 with EIO_EN=1
// so the address-mux generate branch (g_shared) actually elaborates.
// Without this, default-parameter lint (EIO_EN=0) dead-code-eliminates
// the new branch and any mismatch between fcapz_regbus_mux / fcapz_ela /
// fcapz_eio ports would slip through CI.
`timescale 1ns/1ps

module lint_eio_en_xilinx7 (
    input  wire        clk,
    input  wire        rst,
    input  wire [7:0]  probe_in,
    input  wire [3:0]  eio_probe_in,
    output wire [3:0]  eio_probe_out
);
    fcapz_ela_xilinx7 #(
        .SAMPLE_W   (8),
        .DEPTH      (1024),
        .EIO_EN     (1),
        .EIO_IN_W   (4),
        .EIO_OUT_W  (4)
    ) u_ela (
        .sample_clk    (clk),
        .sample_rst    (rst),
        .probe_in      (probe_in),
        .trigger_in    (1'b0),
        .trigger_out   (),
        .eio_probe_in  (eio_probe_in),
        .eio_probe_out (eio_probe_out)
    );
endmodule
