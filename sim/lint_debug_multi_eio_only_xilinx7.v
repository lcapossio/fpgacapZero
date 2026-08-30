// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

module lint_debug_multi_eio_only_xilinx7;
    wire eio_out;

    fcapz_debug_multi_xilinx7 #(
        .NUM_ELAS(0),
        .EIO_EN(1),
        .NUM_EIOS(1),
        .SAMPLE_W(1),
        .EIO_IN_W(1),
        .EIO_OUT_W(1)
    ) dut (
        .ela_sample_clk(1'b0),
        .ela_sample_rst(1'b0),
        .ela_probe_in(1'b0),
        .ela_trigger_in(1'b0),
        .ela_trigger_out(),
        .ela_armed_out(),
        .eio_probe_in(1'b0),
        .eio_probe_out(eio_out)
    );
endmodule
