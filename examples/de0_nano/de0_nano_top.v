// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
// Copyright (c) 2026 Khush Patil

// Terasic DE0-Nano (Cyclone IV E EP4CE22F17C6) reference design.
//
// ELA (instances 1 + 2) samples a free-running 8-bit counter and KEY[1:0];
// EIO (instance 3) reads SW[3:0] and KEY[1:0] and drives LED[7:0].
module de0_nano_top (
    input  wire       CLOCK_50,
    input  wire [1:0] KEY,
    input  wire [3:0] SW,
    output wire [7:0] LED
);
    localparam SAMPLE_W = 10;    // {KEY[1:0], counter[7:0]}
    localparam DEPTH    = 1024;
    localparam EIO_IN_W = 8;     // {2'b00, KEY[1:0], SW[3:0]}
    localparam EIO_OUT_W = 8;    // LED[7:0]

    reg [3:0] por = 4'd0;
    always @(posedge CLOCK_50) if (por != 4'hF) por <= por + 4'd1;
    wire por_rst = (por != 4'hF);

    reg [7:0] counter = 8'd0;
    always @(posedge CLOCK_50) counter <= counter + 8'd1;

    fcapz_ela_intel #(
        .SAMPLE_W(SAMPLE_W), .DEPTH(DEPTH),
        .CTRL_CHAIN(1), .DATA_CHAIN(2), .INPUT_PIPE(1)
    ) u_ela (
        .sample_clk(CLOCK_50), .sample_rst(por_rst),
        .probe_in({KEY, counter}),
        .trigger_in(1'b0), .trigger_out(), .armed_out()
    );

    wire [EIO_OUT_W-1:0] eio_out;
    fcapz_eio_intel #(.IN_W(EIO_IN_W), .OUT_W(EIO_OUT_W), .CHAIN(3)) u_eio (
        .probe_in({2'b00, KEY, SW}), .probe_out(eio_out)
    );
    assign LED = eio_out;
endmodule
