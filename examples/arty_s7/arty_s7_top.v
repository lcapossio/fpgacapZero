// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
// Copyright (c) 2026 Khush Patil

// Digilent Arty S7-25 (Spartan-7 XC7S25-1CSGA324) reference design.
//
// ELA (USER1, control and burst readout) samples a free-running 8-bit counter and btn[3:0];
// EIO (USER3) reads sw[2:0] and btn[3:0] and drives led[3:0].
// sw[3] (M5) is on the 1.35 V bank 34 and is not used.
module arty_s7_top (
    input  wire       clk,      // 12 MHz
    input  wire [3:0] btn,
    input  wire [2:0] sw,
    output wire [3:0] led
);
    localparam SAMPLE_W  = 12;   // {btn[3:0], counter[7:0]}
    localparam DEPTH     = 1024;
    localparam EIO_IN_W  = 8;    // {btn[3:0], 1'b0, sw[2:0]}
    localparam EIO_OUT_W = 8;    // led[3:0] in bits 3:0

    reg [3:0] por = 4'd0;
    always @(posedge clk) if (por != 4'hF) por <= por + 4'd1;
    wire por_rst = (por != 4'hF);

    reg [7:0] counter = 8'd0;
    always @(posedge clk) counter <= counter + 8'd1;

    fcapz_ela_xilinx7 #(
        .SAMPLE_W(SAMPLE_W), .DEPTH(DEPTH),
        .CTRL_CHAIN(1), .DATA_CHAIN(2), .INPUT_PIPE(1)
    ) u_ela (
        .sample_clk(clk), .sample_rst(por_rst), .probe_in({btn, counter}),
        .trigger_in(1'b0), .trigger_out(), .armed_out()
    );

    wire [EIO_OUT_W-1:0] eio_out;
    fcapz_eio_xilinx7 #(.IN_W(EIO_IN_W), .OUT_W(EIO_OUT_W), .CHAIN(3)) u_eio (
        .probe_in({btn, 1'b0, sw}), .probe_out(eio_out)
    );
    assign led = eio_out[3:0];
endmodule
