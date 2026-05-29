// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

module lint_debug_multi_hetero_xilinx7;
    reg clk0 = 1'b0;
    reg clk1 = 1'b0;
    reg rst0 = 1'b0;
    reg rst1 = 1'b0;
    wire [1:0] trig_out;
    wire [1:0] armed;
    wire [31:0] eio_out;

    always #5 clk0 = ~clk0;
    always #7 clk1 = ~clk1;

    fcapz_debug_multi_xilinx7 #(
        .NUM_ELAS(2),
        .EIO_EN(1),
        .NUM_EIOS(2),
        .SAMPLE_W(32),
        .DEPTH(1024),
        .TIMESTAMP_W(32),
        .NUM_SEGMENTS(4),
        .EIO_IN_W(16),
        .EIO_OUT_W(16),
        .ELA_SAMPLE_WS({32'd32, 32'd16}),
        .ELA_DEPTHS({32'd1024, 32'd512}),
        .ELA_TIMESTAMP_WS({32'd32, 32'd0}),
        .ELA_NUM_SEGMENTS({32'd4, 32'd1}),
        .ELA_DECIM_ENS({32'd1, 32'd0}),
        .ELA_EXT_TRIG_ENS({32'd1, 32'd0}),
        .EIO_IN_WS({32'd12, 32'd8}),
        .EIO_OUT_WS({32'd16, 32'd4})
    ) dut (
        .ela_sample_clk({clk1, clk0}),
        .ela_sample_rst({rst1, rst0}),
        .ela_probe_in({32'h1234_5678, 16'h0000, 16'hCAFE}),
        .ela_trigger_in(2'b00),
        .ela_trigger_out(trig_out),
        .ela_armed_out(armed),
        .eio_probe_in({4'h0, 12'hABC, 8'h00, 8'h5A}),
        .eio_probe_out(eio_out)
    );
endmodule
