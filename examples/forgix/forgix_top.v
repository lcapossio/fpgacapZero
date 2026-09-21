// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero reference design for the Forgix board
// (Efinix Trion T8F49 + Raspberry Pi RP2354).
//
// The Forgix board has no JTAG path to the FPGA fabric at all -- the T8 is
// configured by the RP2354 over a write-only passive SPI link and its JTAG
// pins are not bonded out to a header, a test point, or the Tag-Connect
// footprint (which is ARM SWD for the RP2354).  So this design reaches the
// host through fcapz_ela_uart / fcapz_uart_tap over two header pins instead.
//
// See README.md in this folder for the jumper wiring, the RP2354 firmware
// patch, and how to connect from the host.
//
// The probe source here is a free-running counter, so the design is useful on
// its own as a bring-up check: arm a capture, and you should read back a ramp.

module forgix_top #(
    // Frequency of the board oscillator feeding clk_in.
    //
    // NOTE: the Forgix oscillator part (ECS-2520MV) is a stocked family rather
    // than a single frequency, so this MUST be set to what your board is
    // fitted with -- the UART baud divider is derived from it, and a wrong
    // value shows up as garbage on the link rather than as a build error.
    parameter CLK_HZ    = 50_000_000,
    parameter BAUD_RATE = 1_000_000,
    parameter SAMPLE_W  = 8,
    parameter DEPTH     = 1024
) (
    input  wire clk_in,
    input  wire rst_n_in,

    // Jumper these two to the RP2354's UART0 on the header:
    //   uart_rxd <- header pin 7  (RP.UART0_TX, RP2354 GPIO12)
    //   uart_txd -> header pin 8  (RP.UART0_RX, RP2354 GPIO13)
    input  wire uart_rxd,
    output wire uart_txd,

    output wire led_armed
);

    wire rst = ~rst_n_in;

    // ---- Probe source: a free-running counter ----
    reg [SAMPLE_W-1:0] counter;
    always @(posedge clk_in or posedge rst) begin
        if (rst) counter <= {SAMPLE_W{1'b0}};
        else     counter <= counter + 1'b1;
    end

    fcapz_ela_uart #(
        .CLK_HZ(CLK_HZ),
        .BAUD_RATE(BAUD_RATE),
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH),
        // Keep the footprint modest: the T8F49 has 7,384 LEs, and a
        // dual-comparator build costs roughly half of them.  Turn
        // DUAL_COMPARE back on if you need the richer trigger shapes and can
        // spare the logic.
        .DUAL_COMPARE(0),
        .TRIG_STAGES(1),
        .BURST_W(256)
    ) u_fcapz (
        .sample_clk(clk_in),
        .sample_rst(rst),
        .probe_in(counter),
        .trigger_in(1'b0),
        .trigger_out(),
        .armed_out(led_armed),
        .uart_rxd(uart_rxd),
        .uart_txd(uart_txd)
    );

endmodule
