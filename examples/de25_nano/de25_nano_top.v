// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// DE25-Nano hardware-validation top-level for fpgacapZero Intel/Altera
// USB-Blaster transport.
//
// The design is self-stimulating:
// - ELA on sld_virtual_jtag instance 1 captures an 8-bit 50 MHz counter.
// - ELA burst readout uses sld_virtual_jtag instance 2.
// - EIO on sld_virtual_jtag instance 3 exposes switches/buttons/counter bits
//   and drives the eight active-low user LEDs.

module de25_nano_top (
    input  wire       CLOCK1_50,
    input  wire [1:0] KEY,
    input  wire [3:0] SW,
    output wire [7:0] LEDR
);

    localparam SAMPLE_W = 8;
    localparam DEPTH = 1024;

    reg [SAMPLE_W-1:0] counter = {SAMPLE_W{1'b0}};
    reg [25:0] heartbeat_div = 26'd0;
    reg heartbeat = 1'b0;
    wire [7:0] eio_probe_in;
    wire [7:0] eio_probe_out;

    always @(posedge CLOCK1_50) begin
        counter <= counter + 1'b1;
        if (heartbeat_div == 26'd24_999_999) begin
            heartbeat_div <= 26'd0;
            heartbeat <= ~heartbeat;
        end else begin
            heartbeat_div <= heartbeat_div + 1'b1;
        end
    end

    assign eio_probe_in = {SW, ~KEY, counter[1:0]};

    fcapz_ela_intel #(
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH),
        .CTRL_CHAIN(1),
        .DATA_CHAIN(2),
        .INPUT_PIPE(1),
        .TIMESTAMP_W(32)
    ) u_ela (
        .sample_clk(CLOCK1_50),
        .sample_rst(1'b0),
        .probe_in(counter)
    );

    fcapz_eio_intel #(
        .IN_W(8),
        .OUT_W(8),
        .CHAIN(3)
    ) u_eio (
        .probe_in(eio_probe_in),
        .probe_out(eio_probe_out)
    );

    // DE25-Nano user LEDs are active-low. LEDR[0] shows heartbeat unless
    // overridden by EIO bit 0; other LEDs are direct EIO outputs.
    assign LEDR = ~({eio_probe_out[7:1], eio_probe_out[0] | heartbeat});

endmodule
